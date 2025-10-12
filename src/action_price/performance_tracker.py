"""
Performance Tracker для Action Price сигналов
"""
import asyncio
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import pytz
import logging

from src.database.models import ActionPriceSignal
from src.database.db import db
from src.binance.client import BinanceClient

logger = logging.getLogger(__name__)


class ActionPricePerformanceTracker:
    """Отслеживание производительности Action Price сигналов с частичными выходами"""
    
    def __init__(self, binance_client: BinanceClient, db,
                 check_interval: int = 60, on_signal_closed_callback=None):
        """
        Args:
            binance_client: Binance клиент
            db: Database экземпляр
            check_interval: Интервал проверки в секундах
            on_signal_closed_callback: Callback для разблокировки символа
        """
        self.binance_client = binance_client
        self.db = db
        self.check_interval = check_interval
        self.running = False
        self.on_signal_closed_callback = on_signal_closed_callback
    
    async def start(self):
        """Запустить фоновую задачу трекинга"""
        self.running = True
        logger.info("🎯 Action Price Performance Tracker started")
        
        while self.running:
            try:
                await self._check_active_signals()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in AP tracker: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)
    
    async def stop(self):
        """Остановить трекер"""
        self.running = False
        logger.info("Action Price Performance Tracker stopped")
    
    async def _check_active_signals(self):
        """Проверить все активные Action Price сигналы"""
        session = self.db.get_session()
        try:
            active_signals = session.query(ActionPriceSignal).filter(
                ActionPriceSignal.status.in_(['PENDING', 'ACTIVE'])
            ).all()
            
            if not active_signals:
                return
            
            logger.debug(f"Checking {len(active_signals)} active AP signals")
            
            for signal in active_signals:
                try:
                    await self._check_signal(signal, session)
                except Exception as e:
                    logger.error(f"Error checking AP signal {signal.id}: {e}", exc_info=True)
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error checking active AP signals: {e}", exc_info=True)
        finally:
            session.close()
    
    async def _check_signal(self, signal: ActionPriceSignal, session):
        """Проверить один сигнал на выход"""
        try:
            symbol_str = str(signal.symbol)
            price_data = await self.binance_client.get_mark_price(symbol_str)
            current_price = float(price_data['markPrice'])
            
            exit_result = await self._check_exit_conditions(signal, current_price)
            
            if exit_result:
                signal.exit_price = exit_result['exit_price']
                signal.exit_reason = exit_result['reason']
                signal.pnl = exit_result.get('pnl', 0.0)
                signal.pnl_percent = exit_result.get('pnl_percent', 0.0)
                signal.status = exit_result['status']
                signal.closed_at = datetime.now(pytz.UTC)
                
                logger.info(f"🎯 AP Signal closed: {signal.symbol} {signal.pattern_type} "
                          f"{signal.direction} | Reason: {exit_result['reason']} | "
                          f"PnL: {exit_result.get('pnl_percent', 0):.2f}%")
                
                # Callback для разблокировки символа
                if self.on_signal_closed_callback:
                    try:
                        await self.on_signal_closed_callback(signal.symbol)
                    except Exception as e:
                        logger.error(f"Error in AP close callback: {e}")
        
        except Exception as e:
            logger.error(f"Error checking AP signal {signal.id}: {e}", exc_info=True)
    
    async def _check_exit_conditions(self, signal: ActionPriceSignal, 
                                     current_price: float) -> Optional[Dict]:
        """
        Проверить условия выхода для сигнала с частичными фиксациями
        
        Args:
            signal: ActionPriceSignal
            current_price: Текущая цена
            
        Returns:
            Dict с данными выхода или None
        """
        direction = signal.direction
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
        
        # Проверка TP1 (частичный выход)
        if tp1 and not signal.partial_exit_1_at:
            if direction == 'LONG' and current_price >= tp1:
                signal.partial_exit_1_at = datetime.now(pytz.UTC)
                signal.partial_exit_1_price = tp1
                logger.info(f"🎯 AP TP1 hit: {signal.symbol} {signal.pattern_type} at {tp1}")
                # Не закрываем сигнал, продолжаем на TP2
                return None
            elif direction == 'SHORT' and current_price <= tp1:
                signal.partial_exit_1_at = datetime.now(pytz.UTC)
                signal.partial_exit_1_price = tp1
                logger.info(f"🎯 AP TP1 hit: {signal.symbol} {signal.pattern_type} at {tp1}")
                return None
        
        # Проверка TP2 (полный выход)
        if tp2:
            if direction == 'LONG' and current_price >= tp2:
                # Рассчитываем общий PnL с учётом частичных выходов
                total_pnl = self._calculate_total_pnl(signal, tp2, entry)
                return {
                    'exit_price': tp2,
                    'reason': 'TAKE_PROFIT_2',
                    'pnl_percent': total_pnl,
                    'pnl': total_pnl,
                    'status': 'WIN'
                }
            elif direction == 'SHORT' and current_price <= tp2:
                total_pnl = self._calculate_total_pnl(signal, tp2, entry)
                return {
                    'exit_price': tp2,
                    'reason': 'TAKE_PROFIT_2',
                    'pnl_percent': total_pnl,
                    'pnl': total_pnl,
                    'status': 'WIN'
                }
        
        # Если TP1 достигнут но нет TP2, закрываем по TP1
        if tp1 and signal.partial_exit_1_at and not tp2:
            total_pnl = self._calculate_total_pnl(signal, tp1, entry)
            return {
                'exit_price': tp1,
                'reason': 'TAKE_PROFIT_1',
                'pnl_percent': total_pnl,
                'pnl': total_pnl,
                'status': 'WIN'
            }
        
        return None
    
    def _calculate_total_pnl(self, signal: ActionPriceSignal, 
                            final_exit_price: float, entry: float) -> float:
        """
        Рассчитать общий PnL с учётом частичных фиксаций
        
        Args:
            signal: Сигнал
            final_exit_price: Финальная цена выхода
            entry: Цена входа
            
        Returns:
            Общий PnL в процентах
        """
        direction = signal.direction
        
        # Если есть частичный выход на TP1
        if signal.partial_exit_1_at and signal.partial_exit_1_price:
            tp1_price = float(signal.partial_exit_1_price)
            partial_pct = 0.5  # 50% на TP1
            
            if direction == 'LONG':
                pnl_tp1 = ((tp1_price - entry) / entry) * 100 * partial_pct
                pnl_tp2 = ((final_exit_price - entry) / entry) * 100 * (1 - partial_pct)
            else:  # SHORT
                pnl_tp1 = ((entry - tp1_price) / entry) * 100 * partial_pct
                pnl_tp2 = ((entry - final_exit_price) / entry) * 100 * (1 - partial_pct)
            
            return pnl_tp1 + pnl_tp2
        else:
            # Полный выход без частичных фиксаций
            if direction == 'LONG':
                return ((final_exit_price - entry) / entry) * 100
            else:
                return ((entry - final_exit_price) / entry) * 100
    
    async def get_performance_stats(self, days: int = 7, 
                                    pattern_type: Optional[str] = None) -> Dict:
        """
        Получить статистику производительности Action Price
        
        Args:
            days: Период в днях
            pattern_type: Фильтр по типу паттерна (опционально)
            
        Returns:
            Dict со статистикой
        """
        session = self.db.get_session()
        try:
            start_date = datetime.now(pytz.UTC) - timedelta(days=days)
            
            query = session.query(ActionPriceSignal).filter(
                ActionPriceSignal.created_at >= start_date
            )
            
            if pattern_type:
                query = query.filter(ActionPriceSignal.pattern_type == pattern_type)
            
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
                    'avg_loss': 0.0,
                    'partial_exits': 0
                }
            
            total = len(signals)
            closed = [s for s in signals if s.status in ['WIN', 'LOSS']]
            wins = [s for s in closed if s.status == 'WIN']
            losses = [s for s in closed if s.status == 'LOSS']
            partial_exits = len([s for s in signals if s.partial_exit_1_at is not None])
            
            win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
            
            closed_with_pnl = [s for s in closed if s.pnl_percent is not None]
            avg_pnl = sum(float(s.pnl_percent) for s in closed_with_pnl) / len(closed_with_pnl) if closed_with_pnl else 0.0
            total_pnl = sum(float(s.pnl_percent) for s in closed_with_pnl)
            
            wins_with_pnl = [s for s in wins if s.pnl_percent is not None]
            losses_with_pnl = [s for s in losses if s.pnl_percent is not None]
            
            return {
                'total_signals': total,
                'closed_signals': len(closed),
                'active_signals': total - len(closed),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': round(win_rate, 2),
                'avg_pnl': round(avg_pnl, 2),
                'total_pnl': round(total_pnl, 2),
                'avg_win': round(sum(float(s.pnl_percent) for s in wins_with_pnl) / len(wins_with_pnl), 2) if wins_with_pnl else 0.0,
                'avg_loss': round(sum(float(s.pnl_percent) for s in losses_with_pnl) / len(losses_with_pnl), 2) if losses_with_pnl else 0.0,
                'partial_exits': partial_exits
            }
            
        finally:
            session.close()
    
    async def get_pattern_breakdown(self, days: int = 7) -> Dict:
        """
        Получить разбивку по паттернам
        
        Args:
            days: Период в днях
            
        Returns:
            Dict с статистикой по каждому паттерну
        """
        pattern_types = ['pin_bar', 'engulfing', 'inside_bar', 'fakey', 'ppr']
        breakdown = {}
        
        for pattern in pattern_types:
            stats = await self.get_performance_stats(days, pattern)
            breakdown[pattern] = stats
        
        return breakdown
