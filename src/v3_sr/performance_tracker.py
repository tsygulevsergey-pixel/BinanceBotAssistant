"""
V3 S/R Performance Tracker

Monitors active V3 S/R signals, checks exit conditions (TP1, TP2, SL, BE, Trailing),
tracks MFE/MAE, and logs results to database and JSONL.
"""

import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta
import pytz

from src.database.models import V3SRSignal
from src.binance.client import BinanceClient
from src.v3_sr.logger import get_v3_sr_logger
from src.v3_sr.helpers import calculate_r_multiple


class V3SRPerformanceTracker:
    """Performance tracker for V3 S/R signals with partial exits and trailing"""
    
    def __init__(self, binance_client: BinanceClient, db,
                 check_interval: int = 60, on_signal_closed_callback=None,
                 signal_logger=None, config: dict = None):
        """
        Args:
            binance_client: Binance client
            db: Database instance
            check_interval: Check interval in seconds
            on_signal_closed_callback: Callback for unlocking symbol
            signal_logger: V3SRSignalLogger for JSONL logging
            config: V3 strategy config
        """
        self.binance_client = binance_client
        self.db = db
        self.check_interval = check_interval
        self.running = False
        self.on_signal_closed_callback = on_signal_closed_callback
        self.signal_logger = signal_logger
        self.config = config or {}
        
        # ✅ FIX БАГ #5: Get logger instance (lazy initialization)
        self.logger = get_v3_sr_logger()
        
        # MFE/MAE tracking (in-memory)
        self.signal_mfe_mae = {}  # {signal_id: {'mfe_r': float, 'mae_r': float}}
    
    async def start(self):
        """Start background tracking task"""
        self.running = True
        self.logger.info("🎯 V3 S/R Performance Tracker started")
        
        while self.running:
            try:
                await self._check_active_signals()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                self.logger.error(f"Error in V3 SR tracker: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)
    
    async def stop(self):
        """Stop tracker"""
        self.running = False
        self.logger.info("V3 S/R Performance Tracker stopped")
    
    async def _check_active_signals(self):
        """Check all active V3 S/R signals"""
        session = self.db.get_session()
        try:
            active_signals = session.query(V3SRSignal).filter(
                V3SRSignal.status.in_(['PENDING', 'ACTIVE'])
            ).all()
            
            if not active_signals:
                self.logger.debug("No active V3 SR signals to check")
                return
            
            self.logger.info(f"🔍 Checking {len(active_signals)} active V3 SR signals for exit conditions")
            
            for signal in active_signals:
                try:
                    await self._check_signal(signal, session)
                    
                    # ✅ FIX БАГ #16: Commit ПОСЛЕ КАЖДОГО сигнала
                    # Гарантирует что tp1_hit, moved_to_be, trailing_active сохраняются в БД
                    # даже если следующий сигнал вызовет ошибку
                    session.commit()
                    
                except asyncio.TimeoutError:
                    # Network timeout - skip this signal, rollback changes
                    session.rollback()
                    self.logger.warning(f"⏱️ Timeout checking V3 SR signal {signal.id} ({signal.symbol}) - skipping")
                except asyncio.CancelledError:
                    # Request cancelled - skip this signal, rollback changes
                    session.rollback()
                    self.logger.debug(f"Request cancelled for V3 SR signal {signal.id} - skipping")
                except Exception as e:
                    # Any other error - rollback changes for this signal
                    session.rollback()
                    self.logger.error(f"Error checking V3 SR signal {signal.id}: {e}", exc_info=True)
            
        except Exception as e:
            self.logger.error(f"Error in _check_active_signals: {e}", exc_info=True)
        finally:
            session.close()
    
    async def _check_signal(self, signal: V3SRSignal, session):
        """Check one signal for exit with MFE/MAE tracking"""
        # ✅ FIX БАГ #16: Убрана обработка ошибок - теперь она в _check_active_signals
        # Это позволяет корректно делать rollback для каждого сигнала отдельно
        
        symbol_str = str(signal.symbol)
        price_data = await self.binance_client.get_mark_price(symbol_str)
        current_price = float(price_data['markPrice'])
        
        # Update MFE/MAE
        self._update_mfe_mae(signal, current_price)
        
        # Check validity timeout
        if await self._check_validity_timeout(signal):
            await self._close_signal(signal, current_price, 'TIMEOUT', 'Validity timeout expired', session)
            return
        
        # Check exit conditions
        exit_result = await self._check_exit_conditions(signal, current_price)
        
        if exit_result:
            await self._close_signal(
                signal, 
                exit_result['exit_price'],
                exit_result['reason'],
                exit_result['reason'],
                session,
                pnl_override=exit_result.get('pnl_override')  # Use saved TP1 PnL if breakeven
            )
    
    def _update_mfe_mae(self, signal: V3SRSignal, current_price: float):
        """
        Update Maximum Favorable/Adverse Excursion in R
        
        Args:
            signal: V3SRSignal
            current_price: Current price
        """
        entry = float(signal.entry_price)
        sl = float(signal.stop_loss)
        direction = signal.direction.upper() if signal.direction else 'LONG'
        risk_r = signal.risk_r if signal.risk_r else abs(entry - sl)
        
        # Skip if SL at breakeven (risk_r = 0)
        if risk_r < 0.0001:
            return
        
        # Calculate current P&L in R
        if direction == 'LONG':
            current_pnl_r = (current_price - entry) / risk_r
        else:  # SHORT
            current_pnl_r = (entry - current_price) / risk_r
        
        # Initialize if new
        if signal.id not in self.signal_mfe_mae:
            self.signal_mfe_mae[signal.id] = {
                'mfe_r': 0.0,
                'mae_r': 0.0
            }
        
        # Update MFE (max favorable)
        if current_pnl_r > self.signal_mfe_mae[signal.id]['mfe_r']:
            self.signal_mfe_mae[signal.id]['mfe_r'] = current_pnl_r
        
        # Update MAE (max adverse)
        if current_pnl_r < self.signal_mfe_mae[signal.id]['mae_r']:
            self.signal_mfe_mae[signal.id]['mae_r'] = current_pnl_r
    
    async def _check_validity_timeout(self, signal: V3SRSignal) -> bool:
        """
        Check if signal validity timeout expired
        
        Args:
            signal: V3SRSignal
            
        Returns:
            True if timeout expired
        """
        if not signal.valid_until_ts:
            return False
        
        now = datetime.now(pytz.UTC)
        
        # Ensure signal.valid_until_ts is timezone-aware
        if signal.valid_until_ts.tzinfo is None:
            signal_valid_until = pytz.UTC.localize(signal.valid_until_ts)
        else:
            signal_valid_until = signal.valid_until_ts
        
        return now >= signal_valid_until
    
    async def _check_exit_conditions(self, signal: V3SRSignal, 
                                     current_price: float) -> Optional[Dict]:
        """
        Check exit conditions for signal with partial exits and trailing
        
        Args:
            signal: V3SRSignal
            current_price: Current price
            
        Returns:
            Dict with exit data or None
        """
        direction = signal.direction.upper() if signal.direction else 'LONG'
        entry = float(signal.entry_price)
        sl = float(signal.stop_loss)
        tp1 = float(signal.take_profit_1) if signal.take_profit_1 else None
        tp2 = float(signal.take_profit_2) if signal.take_profit_2 else None
        
        # Check TP1 (50% exit - VIRTUAL partial close)
        if tp1 and not signal.tp1_hit:
            if (direction == 'LONG' and current_price >= tp1) or \
               (direction == 'SHORT' and current_price <= tp1):
                # TP1 hit - VIRTUAL partial close of 50%
                signal.tp1_hit = True
                signal.tp1_hit_at = datetime.now(pytz.UTC)
                
                # Calculate PnL from TP1 for 50% of position
                tp1_size = 0.50  # 50% exit at TP1 (virtual)
                if direction == 'LONG':
                    tp1_pnl_full = (tp1 - entry) / entry * 100
                else:
                    tp1_pnl_full = (entry - tp1) / entry * 100
                
                # Store PnL for VIRTUAL 50% exit
                signal.tp1_pnl_percent = tp1_pnl_full * tp1_size
                signal.tp1_size = tp1_size
                
                # Move to BE
                if self.config.get('sl_tp', {}).get('move_to_be_after_tp1', True):
                    signal.stop_loss = entry
                    signal.moved_to_be = True
                    signal.moved_to_be_at = datetime.now(pytz.UTC)
                
                # Activate trailing for remaining 50%
                if self.config.get('sl_tp', {}).get('trail_after_tp1', True):
                    signal.trailing_active = True
                    signal.trailing_high_water_mark = current_price
                
                self.logger.info(
                    f"📈 V3 SR TP1 HIT (50%): {signal.symbol} {signal.direction} "
                    f"| Virtual partial close at {tp1:.4f} (+{signal.tp1_pnl_percent:.2f}%) "
                    f"| SL moved to BE {entry:.4f} | Trailing activated for remaining 50%"
                )
                
                # Don't close yet - continue to TP2 with remaining 50%
                return None
        
        # Check TP2 (remaining 50%)
        if tp2 and signal.tp1_hit and not signal.tp2_hit:
            if (direction == 'LONG' and current_price >= tp2) or \
               (direction == 'SHORT' and current_price <= tp2):
                # TP2 hit - close full position
                signal.tp2_hit = True
                signal.tp2_hit_at = datetime.now(pytz.UTC)
                signal.tp2_pnl_percent = ((tp2 - entry) / entry * 100) if direction == 'LONG' else \
                                        ((entry - tp2) / entry * 100)
                
                return {
                    'exit_price': tp2,
                    'reason': 'TP2'
                }
        
        # Check Trailing Stop (after TP1 hit)
        if signal.trailing_active and signal.trailing_high_water_mark:
            trail_atr = self.config.get('sl_tp', {}).get('trail_atr_mult', 0.5)
            atr = signal.atr_value if signal.atr_value else (signal.risk_r * 0.5)
            
            # Update high water mark
            if direction == 'LONG':
                if current_price > signal.trailing_high_water_mark:
                    signal.trailing_high_water_mark = current_price
                
                # Check if price dropped below trail
                trail_sl = signal.trailing_high_water_mark - (trail_atr * atr)
                if current_price <= trail_sl:
                    return {
                        'exit_price': trail_sl,
                        'reason': 'TRAIL'
                    }
            else:  # SHORT
                if current_price < signal.trailing_high_water_mark:
                    signal.trailing_high_water_mark = current_price
                
                # Check if price rose above trail
                trail_sl = signal.trailing_high_water_mark + (trail_atr * atr)
                if current_price >= trail_sl:
                    return {
                        'exit_price': trail_sl,
                        'reason': 'TRAIL'
                    }
        
        # Check Stop Loss
        if direction == 'LONG' and current_price <= sl:
            # Breakeven exit if SL was moved to BE after TP1
            if signal.moved_to_be:
                # Use saved PnL from TP1 (50% virtual exit)
                saved_tp1_pnl = signal.tp1_pnl_percent if signal.tp1_pnl_percent else 0.0
                return {
                    'exit_price': sl,
                    'reason': 'BE',
                    'pnl_override': saved_tp1_pnl  # Return TP1 profit from 50% that was closed
                }
            else:
                return {
                    'exit_price': sl,
                    'reason': 'SL'
                }
        
        if direction == 'SHORT' and current_price >= sl:
            # Breakeven exit if SL was moved to BE after TP1
            if signal.moved_to_be:
                # Use saved PnL from TP1 (50% virtual exit)
                saved_tp1_pnl = signal.tp1_pnl_percent if signal.tp1_pnl_percent else 0.0
                return {
                    'exit_price': sl,
                    'reason': 'BE',
                    'pnl_override': saved_tp1_pnl  # Return TP1 profit from 50% that was closed
                }
            else:
                return {
                    'exit_price': sl,
                    'reason': 'SL'
                }
        
        return None
    
    async def _close_signal(self, signal: V3SRSignal, exit_price: float,
                          exit_reason: str, exit_type: str, session,
                          pnl_override: Optional[float] = None):
        """
        Close signal and log results
        
        Args:
            signal: V3SRSignal
            exit_price: Exit price
            exit_reason: Exit reason
            exit_type: Exit type
            session: DB session
            pnl_override: Optional PnL override (for breakeven exits with saved TP1 profit)
        """
        # Calculate P&L
        entry = float(signal.entry_price)
        direction = signal.direction.upper() if signal.direction else 'LONG'
        risk = float(signal.risk_r) if signal.risk_r else abs(entry - float(signal.stop_loss))
        
        # DEBUG LOGGING
        self.logger.info(f"🔍 CLOSING V3 SIGNAL: {signal.symbol} {direction}")
        self.logger.info(f"  Entry: {entry:.4f} | Exit: {exit_price:.4f} | SL: {signal.stop_loss:.4f}")
        self.logger.info(f"  Exit Reason: {exit_reason} | TP1 Hit: {signal.tp1_hit} | Moved to BE: {signal.moved_to_be}")
        self.logger.info(f"  PnL Override: {pnl_override}")
        
        # Use saved TP1 PnL if provided (breakeven exit after TP1)
        if pnl_override is not None:
            pnl_percent = pnl_override
            self.logger.info(f"  Using PnL override: {pnl_percent:.2f}%")
        else:
            # Calculate full exit PnL
            if direction == 'LONG':
                full_exit_pnl = ((exit_price - entry) / entry) * 100
            else:
                full_exit_pnl = ((entry - exit_price) / entry) * 100
            
            self.logger.info(f"  Full exit PnL calculation: {full_exit_pnl:.2f}%")
            
            # If TP1 was hit, combine virtual TP1 exit + remaining position exit
            if signal.tp1_hit:
                tp1_pnl_saved = signal.tp1_pnl_percent if signal.tp1_pnl_percent else 0.0
                tp1_size = signal.tp1_size if signal.tp1_size else 0.50
                remaining_size = 1.0 - tp1_size  # Remaining 50%
                
                # Combined PnL: TP1 virtual exit + remaining position
                pnl_percent = tp1_pnl_saved + (remaining_size * full_exit_pnl)
                self.logger.info(f"  Combined PnL: TP1 saved {tp1_pnl_saved:.2f}% + remaining {remaining_size*100:.0f}% * {full_exit_pnl:.2f}% = {pnl_percent:.2f}%")
            else:
                # No TP1 hit - use full exit PnL
                pnl_percent = full_exit_pnl
                self.logger.info(f"  No TP1 hit, using full exit PnL: {pnl_percent:.2f}%")
        
        # Calculate final R-multiple (use original risk_r, not moved BE SL)
        if signal.tp1_hit:
            # Calculate R for combined exits using original risk
            if risk > 0:
                if direction == 'LONG':
                    # TP1 R-multiple
                    tp1 = float(signal.take_profit_1) if signal.take_profit_1 else entry
                    tp1_r_full = (tp1 - entry) / risk
                    tp1_r_weighted = tp1_r_full * (signal.tp1_size if signal.tp1_size else 0.50)
                    
                    # Exit R-multiple for remaining
                    exit_r_full = (exit_price - entry) / risk
                    remaining_size = 1.0 - (signal.tp1_size if signal.tp1_size else 0.50)
                    exit_r_weighted = exit_r_full * remaining_size
                    
                    final_r = tp1_r_weighted + exit_r_weighted
                else:  # SHORT
                    # TP1 R-multiple
                    tp1 = float(signal.take_profit_1) if signal.take_profit_1 else entry
                    tp1_r_full = (entry - tp1) / risk
                    tp1_r_weighted = tp1_r_full * (signal.tp1_size if signal.tp1_size else 0.50)
                    
                    # Exit R-multiple for remaining
                    exit_r_full = (entry - exit_price) / risk
                    remaining_size = 1.0 - (signal.tp1_size if signal.tp1_size else 0.50)
                    exit_r_weighted = exit_r_full * remaining_size
                    
                    final_r = tp1_r_weighted + exit_r_weighted
            else:
                final_r = 0.0
        else:
            # No TP1 - calculate R using original risk
            if risk > 0:
                if direction == 'LONG':
                    final_r = (exit_price - entry) / risk
                else:
                    final_r = (entry - exit_price) / risk
            else:
                final_r = 0.0
        
        # Calculate duration
        created_at = signal.created_at if signal.created_at else datetime.now(pytz.UTC)
        
        # Ensure created_at is timezone-aware
        if created_at.tzinfo is None:
            created_at = pytz.UTC.localize(created_at)
        
        closed_at = datetime.now(pytz.UTC)
        duration_minutes = int((closed_at - created_at).total_seconds() / 60)
        
        # Update signal
        signal.exit_price = exit_price
        signal.exit_reason = exit_reason
        signal.exit_type = exit_type
        signal.pnl_percent = pnl_percent
        signal.final_r_multiple = final_r
        signal.status = 'CLOSED'
        signal.closed_at = closed_at
        signal.duration_minutes = duration_minutes
        
        # Get MFE/MAE
        mfe_mae = self.signal_mfe_mae.get(signal.id, {'mfe_r': 0.0, 'mae_r': 0.0})
        signal.max_favorable_excursion = mfe_mae['mfe_r']
        signal.max_adverse_excursion = mfe_mae['mae_r']
        
        # Log to JSONL
        await self._log_signal_exit(signal, mfe_mae)
        
        # Remove from tracking
        if signal.id in self.signal_mfe_mae:
            del self.signal_mfe_mae[signal.id]
        
        self.logger.info(f"🎯 V3 SR Signal closed: {signal.symbol} {signal.setup_type} "
                   f"{signal.direction} | Reason: {exit_reason} | "
                   f"PnL: {pnl_percent:.2f}% | Final R: {final_r:.2f}R | "
                   f"MFE: {mfe_mae['mfe_r']:.2f}R | MAE: {mfe_mae['mae_r']:.2f}R")
        
        # Callback to unblock symbol
        if self.on_signal_closed_callback:
            try:
                self.on_signal_closed_callback(signal.symbol, signal.direction)
            except Exception as e:
                self.logger.error(f"Error in V3 SR close callback: {e}")
    
    async def _log_signal_exit(self, signal: V3SRSignal, mfe_mae: Dict[str, float]):
        """
        Log signal exit to JSONL
        
        Args:
            signal: V3SRSignal
            mfe_mae: Dict with mfe_r and mae_r
        """
        try:
            if self.signal_logger:
                # Update signal with exit data in JSONL
                self.signal_logger.update_signal_exit(
                    signal_id=signal.signal_id if signal.signal_id else str(signal.id),
                    exit_reason=signal.exit_reason if signal.exit_reason else 'UNKNOWN',
                    timestamp_exit=signal.closed_at if signal.closed_at else datetime.now(pytz.UTC),
                    exit_price=float(signal.exit_price) if signal.exit_price else 0.0,
                    pnl=0.0,  # Not tracking absolute P&L
                    pnl_percent=signal.pnl_percent if signal.pnl_percent else 0.0,
                    final_r_multiple=signal.final_r_multiple if signal.final_r_multiple else 0.0,
                    mfe_r=mfe_mae['mfe_r'],
                    mae_r=mfe_mae['mae_r'],
                    tp1_hit=signal.tp1_hit if signal.tp1_hit else False,
                    tp2_hit=signal.tp2_hit if signal.tp2_hit else False,
                    bars_to_exit=signal.bars_to_exit if signal.bars_to_exit else 0,
                    duration_minutes=signal.duration_minutes if signal.duration_minutes else 0,
                    zone_reaction_occurred=signal.zone_reaction_occurred,
                    zone_reaction_atr=signal.zone_reaction_atr
                )
                self.logger.debug(f"✅ JSONL logged exit: {signal.signal_id} - MFE: {mfe_mae['mfe_r']:.2f}R, MAE: {mfe_mae['mae_r']:.2f}R")
        
        except Exception as e:
            self.logger.error(f"Error logging V3 SR signal exit: {e}", exc_info=True)
