"""
Gluk Performance Tracker - отслеживание сигналов Legacy системы

КРИТИЧНО: Полностью независимо от Action Price tracker!
- Использует таблицу gluk_signals
- Отдельная логика MFE/MAE tracking
- Независимый от AP
"""
import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta
import pytz
import logging

from src.database.models import GlukSignal
from src.binance.client import BinanceClient

logger = logging.getLogger('gluk')


class GlukPerformanceTracker:
    """Отслеживание производительности Глюк сигналов"""
    
    def __init__(self, binance_client: BinanceClient, db,
                 check_interval: int = 60, on_signal_closed_callback=None):
        """
        Args:
            binance_client: Binance клиент
            db: Database instance
            check_interval: Интервал проверки в секундах
            on_signal_closed_callback: Callback для разблокировки символа
        """
        self.binance_client = binance_client
        self.db = db
        self.check_interval = check_interval
        self.running = False
        self.on_signal_closed_callback = on_signal_closed_callback
        
        # MFE/MAE tracking
        self.signal_mfe_mae = {}  # {signal_id: {'mfe_r': float, 'mae_r': float}}
    
    async def start(self):
        """Запустить фоновую задачу трекинга"""
        self.running = True
        logger.info("🟡 Gluk Performance Tracker started")
        
        while self.running:
            try:
                await self._check_active_signals()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in Gluk tracker: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)
    
    async def stop(self):
        """Остановить трекер"""
        self.running = False
        logger.info("Gluk Performance Tracker stopped")
    
    async def _check_active_signals(self):
        """Проверить все активные Глюк сигналы"""
        session = self.db.get_session()
        try:
            active_signals = session.query(GlukSignal).filter(
                GlukSignal.status.in_(['PENDING', 'ACTIVE'])
            ).all()
            
            if not active_signals:
                return
            
            logger.debug(f"🟡 Checking {len(active_signals)} active Gluk signals")
            
            for signal in active_signals:
                try:
                    await self._check_signal(signal, session)
                except Exception as e:
                    logger.error(f"Error checking Gluk signal {signal.id}: {e}", exc_info=True)
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error checking active Gluk signals: {e}", exc_info=True)
        finally:
            session.close()
    
    async def _check_signal(self, signal: GlukSignal, session):
        """Проверить один сигнал на выход"""
        try:
            symbol_str = str(signal.symbol)
            price_data = await self.binance_client.get_mark_price(symbol_str)
            current_price = float(price_data['markPrice'])
            
            # Обновить MFE/MAE
            self._update_mfe_mae(signal, current_price)
            
            exit_result = await self._check_exit_conditions(signal, current_price)
            
            if exit_result:
                signal.exit_price = exit_result['exit_price']
                signal.exit_reason = exit_result['reason']
                signal.pnl = exit_result.get('pnl', 0.0)
                signal.pnl_percent = exit_result.get('pnl_percent', 0.0)
                signal.status = exit_result['status']
                signal.closed_at = datetime.now(pytz.UTC)
                
                # MFE/MAE
                mfe_mae = self.signal_mfe_mae.get(signal.id, {'mfe_r': 0.0, 'mae_r': 0.0})
                
                logger.info(f"🟡 Gluk Signal closed: {signal.symbol} {signal.pattern_type} "
                          f"{signal.direction} | Reason: {exit_result['reason']} | "
                          f"PnL: {exit_result.get('pnl_percent', 0):.2f}% | "
                          f"MFE: {mfe_mae['mfe_r']:.2f}R | MAE: {mfe_mae['mae_r']:.2f}R")
                
                # Удалить из tracking
                if signal.id in self.signal_mfe_mae:
                    del self.signal_mfe_mae[signal.id]
                
                # Callback для разблокировки
                if self.on_signal_closed_callback:
                    try:
                        self.on_signal_closed_callback(signal.symbol)
                    except Exception as e:
                        logger.error(f"Error in Gluk close callback: {e}")
        
        except Exception as e:
            logger.error(f"Error checking Gluk signal {signal.id}: {e}", exc_info=True)
    
    def _update_mfe_mae(self, signal: GlukSignal, current_price: float):
        """Обновить Maximum Favorable/Adverse Excursion"""
        entry = float(signal.entry_price)
        sl = float(signal.stop_loss)
        direction = signal.direction.upper() if signal.direction else 'LONG'
        risk_r = abs(entry - sl)
        
        if risk_r < 0.0001:
            return
        
        # Рассчитать текущий P&L в R
        if direction == 'LONG':
            current_pnl_r = (current_price - entry) / risk_r
        else:
            current_pnl_r = (entry - current_price) / risk_r
        
        # Инициализировать если новый
        if signal.id not in self.signal_mfe_mae:
            self.signal_mfe_mae[signal.id] = {'mfe_r': 0.0, 'mae_r': 0.0}
        
        # Обновить MFE
        if current_pnl_r > self.signal_mfe_mae[signal.id]['mfe_r']:
            self.signal_mfe_mae[signal.id]['mfe_r'] = current_pnl_r
        
        # Обновить MAE
        if current_pnl_r < self.signal_mfe_mae[signal.id]['mae_r']:
            self.signal_mfe_mae[signal.id]['mae_r'] = current_pnl_r
    
    async def _check_exit_conditions(self, signal: GlukSignal, 
                                     current_price: float) -> Optional[Dict]:
        """Проверить условия выхода для сигнала"""
        direction = signal.direction.upper() if signal.direction else 'LONG'
        entry = float(signal.entry_price)
        sl = float(signal.stop_loss)
        tp1 = float(signal.take_profit_1) if signal.take_profit_1 else None
        tp2 = float(signal.take_profit_2) if signal.take_profit_2 else None
        
        # Проверка SL
        if direction == 'LONG' and current_price <= sl:
            pnl_pct = ((current_price - entry) / entry) * 100
            return {
                'exit_price': sl,
                'reason': 'STOP_LOSS',
                'pnl_percent': pnl_pct,
                'pnl': pnl_pct,
                'status': 'LOSS'
            }
        elif direction == 'SHORT' and current_price >= sl:
            pnl_pct = ((entry - current_price) / entry) * 100
            return {
                'exit_price': sl,
                'reason': 'STOP_LOSS',
                'pnl_percent': pnl_pct,
                'pnl': pnl_pct,
                'status': 'LOSS'
            }
        
        # Проверка TP1
        if tp1 and not signal.partial_exit_1_at:
            if direction == 'LONG' and current_price >= tp1:
                signal.partial_exit_1_at = datetime.now(pytz.UTC)
                signal.partial_exit_1_price = tp1
                signal.stop_loss = entry  # Breakeven
                logger.info(f"🟡 Gluk TP1 hit: {signal.symbol} at {tp1}, SL moved to breakeven")
                return None
            elif direction == 'SHORT' and current_price <= tp1:
                signal.partial_exit_1_at = datetime.now(pytz.UTC)
                signal.partial_exit_1_price = tp1
                signal.stop_loss = entry  # Breakeven
                logger.info(f"🟡 Gluk TP1 hit: {signal.symbol} at {tp1}, SL moved to breakeven")
                return None
        
        # Проверка TP2
        if tp2:
            if direction == 'LONG' and current_price >= tp2:
                signal.partial_exit_2_at = datetime.now(pytz.UTC)
                signal.partial_exit_2_price = tp2
                total_pnl = self._calculate_total_pnl(signal, tp2, entry)
                return {
                    'exit_price': tp2,
                    'reason': 'TAKE_PROFIT_2',
                    'pnl_percent': total_pnl,
                    'pnl': total_pnl,
                    'status': 'WIN'
                }
            elif direction == 'SHORT' and current_price <= tp2:
                signal.partial_exit_2_at = datetime.now(pytz.UTC)
                signal.partial_exit_2_price = tp2
                total_pnl = self._calculate_total_pnl(signal, tp2, entry)
                return {
                    'exit_price': tp2,
                    'reason': 'TAKE_PROFIT_2',
                    'pnl_percent': total_pnl,
                    'pnl': total_pnl,
                    'status': 'WIN'
                }
        
        # Time stop (7 дней)
        created_time = signal.created_at
        if created_time.tzinfo is None:
            created_time = pytz.UTC.localize(created_time)
        
        hours_since_created = (datetime.now(pytz.UTC) - created_time).total_seconds() / 3600
        if hours_since_created > 168:  # 7 дней
            if direction == 'LONG':
                pnl_pct = ((current_price - entry) / entry) * 100
            else:
                pnl_pct = ((entry - current_price) / entry) * 100
            
            return {
                'exit_price': current_price,
                'reason': 'TIME_STOP',
                'pnl_percent': pnl_pct,
                'pnl': pnl_pct,
                'status': 'WIN' if pnl_pct > 0 else 'LOSS'
            }
        
        return None
    
    def _calculate_total_pnl(self, signal: GlukSignal, 
                            final_exit_price: float, entry: float) -> float:
        """Рассчитать общий PnL с учётом частичных фиксаций"""
        direction = signal.direction.upper() if signal.direction else 'LONG'
        
        if signal.partial_exit_1_at and signal.partial_exit_1_price:
            tp1_price = float(signal.partial_exit_1_price)
            tp1_pct = 0.30
            tp2_pct = 0.70
            
            if direction == 'LONG':
                pnl_tp1 = ((tp1_price - entry) / entry) * 100 * tp1_pct
                pnl_remainder = ((final_exit_price - entry) / entry) * 100 * tp2_pct
            else:
                pnl_tp1 = ((entry - tp1_price) / entry) * 100 * tp1_pct
                pnl_remainder = ((entry - final_exit_price) / entry) * 100 * tp2_pct
            
            return pnl_tp1 + pnl_remainder
        else:
            if direction == 'LONG':
                return ((final_exit_price - entry) / entry) * 100
            else:
                return ((entry - final_exit_price) / entry) * 100
    
    async def get_performance_stats(self, days: int = 7) -> Dict:
        """Получить статистику производительности Глюк"""
        session = self.db.get_session()
        try:
            start_date = datetime.now(pytz.UTC) - timedelta(days=days)
            
            signals = session.query(GlukSignal).filter(
                GlukSignal.created_at >= start_date
            ).all()
            
            if not signals:
                return {
                    'total_signals': 0,
                    'closed_signals': 0,
                    'wins': 0,
                    'losses': 0,
                    'win_rate': 0.0,
                    'avg_pnl': 0.0
                }
            
            total = len(signals)
            closed = [s for s in signals if s.status in ['WIN', 'LOSS']]
            wins = [s for s in closed if s.status == 'WIN']
            losses = [s for s in closed if s.status == 'LOSS']
            
            win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
            
            closed_with_pnl = [s for s in closed if s.pnl_percent is not None]
            avg_pnl = sum(float(s.pnl_percent) for s in closed_with_pnl) / len(closed_with_pnl) if closed_with_pnl else 0.0
            
            return {
                'total_signals': total,
                'closed_signals': len(closed),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': round(win_rate, 2),
                'avg_pnl': round(avg_pnl, 2)
            }
            
        finally:
            session.close()
