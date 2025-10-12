import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import pytz
from sqlalchemy import and_
from src.database.models import Signal
from src.database.db import Database
from src.binance.client import BinanceClient
from src.utils.signal_lock import SignalLockManager
from src.utils.logger import logger


class SignalPerformanceTracker:
    """Отслеживание производительности активных сигналов (PnL, win rate, exit tracking)"""
    
    def __init__(self, binance_client: BinanceClient, db: Database, 
                 lock_manager: SignalLockManager, check_interval: int = 60,
                 on_signal_closed_callback = None):
        self.binance_client = binance_client
        self.db = db
        self.lock_manager = lock_manager
        self.check_interval = check_interval
        self.running = False
        self.on_signal_closed_callback = on_signal_closed_callback
        
    async def start(self):
        """Запустить фоновую задачу трекинга"""
        self.running = True
        logger.info("📊 Signal Performance Tracker started")
        
        while self.running:
            try:
                await self._check_active_signals()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in signal tracker: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)
    
    async def stop(self):
        """Остановить трекер"""
        self.running = False
        logger.info("Signal Performance Tracker stopped")
    
    async def _check_active_signals(self):
        """Проверить все активные сигналы"""
        session = self.db.get_session()
        try:
            active_signals = session.query(Signal).filter(
                Signal.status == 'ACTIVE'
            ).all()
            
            if not active_signals:
                return
            
            logger.debug(f"Checking {len(active_signals)} active signals")
            
            for signal in active_signals:
                try:
                    await self._check_signal(signal, session)
                except Exception as e:
                    logger.error(f"Error checking signal {signal.id}: {e}", exc_info=True)
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error checking active signals: {e}", exc_info=True)
        finally:
            session.close()
    
    async def _check_signal(self, signal: Signal, session):
        """Проверить один сигнал на выход"""
        try:
            symbol_str = str(signal.symbol)
            price_data = await self.binance_client.get_mark_price(symbol_str)
            current_price = float(price_data['markPrice'])
            
            exit_result = self._check_exit_conditions(signal, current_price)
            
            if exit_result:
                exit_reason, exit_price, pnl_percent = exit_result
                
                signal.status = exit_reason  # type: ignore
                signal.exit_price = exit_price  # type: ignore
                signal.exit_reason = exit_reason  # type: ignore
                signal.pnl_percent = pnl_percent  # type: ignore
                signal.closed_at = datetime.now(pytz.UTC)  # type: ignore
                
                self.lock_manager.release_lock(symbol_str)
                
                # Вызвать callback для разблокировки символа
                if self.on_signal_closed_callback:
                    self.on_signal_closed_callback(symbol_str)
                
                status_emoji = "✅" if exit_reason == "WIN" else "❌" if exit_reason == "LOSS" else "⏱️"
                logger.info(
                    f"{status_emoji} Signal closed: {signal.symbol} {signal.direction} "
                    f"| Entry: {signal.entry_price:.4f} → Exit: {exit_price:.4f} "
                    f"| PnL: {pnl_percent:+.2f}% | Reason: {exit_reason}"
                )
                
        except Exception as e:
            logger.error(f"Error checking signal {signal.id} ({signal.symbol}): {e}")
    
    def _check_exit_conditions(self, signal: Signal, current_price: float) -> Optional[tuple]:
        """
        Проверить условия выхода для сигнала
        
        Returns:
            tuple (exit_reason, exit_price, pnl_percent) или None если выхода нет
        """
        entry = float(signal.entry_price)  # type: ignore
        sl = float(signal.stop_loss)  # type: ignore
        tp1 = float(signal.take_profit_1) if signal.take_profit_1 else None  # type: ignore
        tp2 = float(signal.take_profit_2) if signal.take_profit_2 else None  # type: ignore
        direction = str(signal.direction)  # type: ignore
        
        if direction == "LONG":
            # Проверка SL (используем точный уровень SL для exit_price)
            if current_price <= sl:
                pnl_percent = ((sl - entry) / entry) * 100
                return ("LOSS", sl, pnl_percent)
            
            # Проверка TP2 (используем точный уровень TP2)
            if tp2 and current_price >= tp2:
                pnl_percent = ((tp2 - entry) / entry) * 100
                return ("WIN", tp2, pnl_percent)
            
            # Проверка TP1 (используем точный уровень TP1)
            if tp1 and current_price >= tp1:
                pnl_percent = ((tp1 - entry) / entry) * 100
                return ("WIN", tp1, pnl_percent)
        
        elif direction == "SHORT":
            # Проверка SL (используем точный уровень SL для exit_price)
            if current_price >= sl:
                pnl_percent = ((entry - sl) / entry) * 100
                return ("LOSS", sl, pnl_percent)
            
            # Проверка TP2 (используем точный уровень TP2)
            if tp2 and current_price <= tp2:
                pnl_percent = ((entry - tp2) / entry) * 100
                return ("WIN", tp2, pnl_percent)
            
            # Проверка TP1 (используем точный уровень TP1)
            if tp1 and current_price <= tp1:
                pnl_percent = ((entry - tp1) / entry) * 100
                return ("WIN", tp1, pnl_percent)
        
        time_stop_result = self._check_time_stop(signal, current_price)
        if time_stop_result:
            return time_stop_result
        
        return None
    
    def _check_time_stop(self, signal: Signal, current_price: float) -> Optional[tuple]:
        """Проверить time-stop (выход по времени если нет прогресса)"""
        now = datetime.now(pytz.UTC)
        
        # Ensure signal.created_at is timezone-aware
        created_at = signal.created_at  # type: ignore
        if created_at.tzinfo is None:
            created_at = pytz.UTC.localize(created_at)
        
        signal_age = (now - created_at).total_seconds() / 60
        
        timeframe_minutes = {
            '1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240
        }
        tf_str = str(signal.timeframe)  # type: ignore
        tf_minutes = timeframe_minutes.get(tf_str, 15)
        
        max_bars = 8
        max_minutes = tf_minutes * max_bars
        
        if signal_age < max_minutes:
            return None
        
        entry = float(signal.entry_price)  # type: ignore
        direction = str(signal.direction)  # type: ignore
        
        atr_threshold = 0.5
        meta = signal.meta_data or {}  # type: ignore
        
        if direction == "LONG":
            required_move = entry * (atr_threshold / 100)
            if current_price < entry + required_move:
                pnl_percent = ((current_price - entry) / entry) * 100
                return ("TIME_STOP", current_price, pnl_percent)
        
        elif direction == "SHORT":
            required_move = entry * (atr_threshold / 100)
            if current_price > entry - required_move:
                pnl_percent = ((entry - current_price) / entry) * 100
                return ("TIME_STOP", current_price, pnl_percent)
        
        return None
    
    async def get_strategy_performance(self, strategy_id: Optional[int] = None, 
                                      days: int = 7) -> Dict:
        """Получить статистику производительности стратегии"""
        session = self.db.get_session()
        try:
            start_date = datetime.now(pytz.UTC) - timedelta(days=days)
            
            query = session.query(Signal).filter(
                Signal.created_at >= start_date
            )
            
            if strategy_id:
                query = query.filter(Signal.strategy_id == strategy_id)
            
            signals = query.all()
            
            if not signals:
                return {
                    'total_signals': 0,
                    'closed_signals': 0,
                    'active_signals': 0,
                    'wins': 0,
                    'losses': 0,
                    'win_rate': 0.0,
                    'avg_pnl': 0.0,
                    'total_pnl': 0.0,
                    'avg_win': 0.0,
                    'avg_loss': 0.0
                }
            
            total = len(signals)
            closed = [s for s in signals if str(s.status) in ['WIN', 'LOSS', 'TIME_STOP']]  # type: ignore
            wins = [s for s in closed if str(s.status) == 'WIN']  # type: ignore
            losses = [s for s in closed if str(s.status) in ['LOSS', 'TIME_STOP']]  # type: ignore
            
            win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
            
            closed_with_pnl = [s for s in closed if s.pnl_percent is not None]  # type: ignore
            avg_pnl = sum(float(s.pnl_percent) for s in closed_with_pnl) / len(closed_with_pnl) if closed_with_pnl else 0.0  # type: ignore
            total_pnl = sum(float(s.pnl_percent) for s in closed_with_pnl)  # type: ignore
            
            wins_with_pnl = [s for s in wins if s.pnl_percent is not None]  # type: ignore
            losses_with_pnl = [s for s in losses if s.pnl_percent is not None]  # type: ignore
            
            return {
                'total_signals': total,
                'closed_signals': len(closed),
                'active_signals': total - len(closed),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': round(win_rate, 2),
                'avg_pnl': round(avg_pnl, 2),
                'total_pnl': round(total_pnl, 2),
                'avg_win': round(sum(float(s.pnl_percent) for s in wins_with_pnl) / len(wins_with_pnl), 2) if wins_with_pnl else 0.0,  # type: ignore
                'avg_loss': round(sum(float(s.pnl_percent) for s in losses_with_pnl) / len(losses_with_pnl), 2) if losses_with_pnl else 0.0  # type: ignore
            }
            
        finally:
            session.close()
    
    async def get_all_strategies_performance(self, days: int = 7) -> List[Dict]:
        """Получить статистику по всем стратегиям"""
        session = self.db.get_session()
        try:
            start_date = datetime.now(pytz.UTC) - timedelta(days=days)
            
            signals = session.query(Signal).filter(
                Signal.created_at >= start_date
            ).all()
            
            strategies = {}
            for signal in signals:
                if signal.strategy_id not in strategies:
                    strategies[signal.strategy_id] = {
                        'strategy_id': signal.strategy_id,
                        'strategy_name': signal.strategy_name,
                        'signals': []
                    }
                strategies[signal.strategy_id]['signals'].append(signal)
            
            results = []
            for strategy_id, data in strategies.items():
                perf = await self._calculate_performance(data['signals'])
                perf['strategy_id'] = strategy_id
                perf['strategy_name'] = data['strategy_name']
                results.append(perf)
            
            results.sort(key=lambda x: x['win_rate'], reverse=True)
            return results
            
        finally:
            session.close()
    
    async def _calculate_performance(self, signals: List[Signal]) -> Dict:
        """Вычислить производительность для списка сигналов"""
        if not signals:
            return {
                'total_signals': 0,
                'win_rate': 0.0,
                'avg_pnl': 0.0
            }
        
        total = len(signals)
        closed = [s for s in signals if str(s.status) in ['WIN', 'LOSS', 'TIME_STOP']]  # type: ignore
        wins = [s for s in closed if str(s.status) == 'WIN']  # type: ignore
        
        win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
        
        closed_with_pnl = [s for s in closed if s.pnl_percent is not None]  # type: ignore
        avg_pnl = sum(float(s.pnl_percent) for s in closed_with_pnl) / len(closed_with_pnl) if closed_with_pnl else 0.0  # type: ignore
        
        return {
            'total_signals': total,
            'closed_signals': len(closed),
            'wins': len(wins),
            'losses': len(closed) - len(wins),
            'win_rate': round(win_rate, 2),
            'avg_pnl': round(avg_pnl, 2)
        }
