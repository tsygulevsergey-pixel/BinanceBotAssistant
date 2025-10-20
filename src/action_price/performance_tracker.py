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
from src.action_price.logger import ap_logger

logger = ap_logger  # Используем Action Price logger для консистентности


class ActionPricePerformanceTracker:
    """Отслеживание производительности Action Price сигналов с частичными выходами"""
    
    def __init__(self, binance_client: BinanceClient, db,
                 check_interval: int = 60, on_signal_closed_callback=None, signal_logger=None):
        """
        Args:
            binance_client: Binance клиент
            db: Database экземпляр
            check_interval: Интервал проверки в секундах
            on_signal_closed_callback: Callback для разблокировки символа
            signal_logger: ActionPriceSignalLogger для JSONL логирования
        """
        self.binance_client = binance_client
        self.db = db
        self.check_interval = check_interval
        self.running = False
        self.on_signal_closed_callback = on_signal_closed_callback
        self.signal_logger = signal_logger  # JSONL logger
        
        # MFE/MAE tracking (в памяти)
        self.signal_mfe_mae = {}  # {signal_id: {'mfe_r': float, 'mae_r': float}}
    
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
                logger.debug("No active AP signals to check")
                return
            
            logger.info(f"🔍 Checking {len(active_signals)} active AP signals for exit conditions")
            
            for signal in active_signals:
                await self._check_signal(signal, session)
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error checking active AP signals: {e}", exc_info=True)
        finally:
            session.close()
    
    async def _check_signal(self, signal: ActionPriceSignal, session):
        """Проверить один сигнал на выход с MFE/MAE tracking"""
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
                
                # Получить MFE/MAE для логирования
                mfe_mae = self.signal_mfe_mae.get(signal.id, {'mfe_r': 0.0, 'mae_r': 0.0})
                
                # Записать в JSONL лог (если есть signal_id в context_hash)
                await self._log_signal_exit(signal, mfe_mae)
                
                # Удалить из tracking
                if signal.id in self.signal_mfe_mae:
                    del self.signal_mfe_mae[signal.id]
                
                logger.info(f"🎯 AP Signal closed: {signal.symbol} {signal.pattern_type} "
                          f"{signal.direction} | Reason: {exit_result['reason']} | "
                          f"PnL: {exit_result.get('pnl_percent', 0):.2f}% | "
                          f"MFE: {mfe_mae['mfe_r']:.2f}R | MAE: {mfe_mae['mae_r']:.2f}R")
                
                # Callback для разблокировки символа
                if self.on_signal_closed_callback:
                    try:
                        self.on_signal_closed_callback(signal.symbol)
                    except Exception as e:
                        logger.error(f"Error in AP close callback: {e}")
        
        except asyncio.TimeoutError:
            # Network timeout - skip this check cycle, will retry on next iteration
            logger.warning(f"⏱️ Timeout checking AP signal {signal.id} ({signal.symbol}) - will retry next cycle")
        except asyncio.CancelledError:
            # Request was cancelled - skip without logging
            logger.debug(f"Request cancelled for AP signal {signal.id}")
        except Exception as e:
            logger.error(f"Error checking AP signal {signal.id}: {e}", exc_info=True)
    
    def _update_mfe_mae(self, signal: ActionPriceSignal, current_price: float):
        """
        Обновить Maximum Favorable/Adverse Excursion в R
        
        Args:
            signal: Сигнал
            current_price: Текущая цена
        """
        entry = float(signal.entry_price)
        sl = float(signal.stop_loss)
        direction = signal.direction.upper() if signal.direction else 'LONG'
        risk_r = abs(entry - sl)
        
        # КРИТИЧНО: Если SL в breakeven (risk_r = 0), пропускаем MFE/MAE update
        if risk_r < 0.0001:
            return
        
        # Рассчитать текущий P&L в R
        if direction == 'LONG':
            current_pnl_r = (current_price - entry) / risk_r
        else:  # SHORT
            current_pnl_r = (entry - current_price) / risk_r
        
        # Инициализировать если новый
        if signal.id not in self.signal_mfe_mae:
            self.signal_mfe_mae[signal.id] = {
                'mfe_r': 0.0,
                'mae_r': 0.0
            }
        
        # Обновить MFE (максимальная благоприятная)
        if current_pnl_r > self.signal_mfe_mae[signal.id]['mfe_r']:
            self.signal_mfe_mae[signal.id]['mfe_r'] = current_pnl_r
        
        # Обновить MAE (максимальная неблагоприятная)
        if current_pnl_r < self.signal_mfe_mae[signal.id]['mae_r']:
            self.signal_mfe_mae[signal.id]['mae_r'] = current_pnl_r
    
    async def _log_signal_exit(self, signal: ActionPriceSignal, mfe_mae: Dict[str, float]):
        """
        Записать выход из сделки в JSONL лог
        
        Args:
            signal: Сигнал
            mfe_mae: Dict с mfe_r и mae_r
        """
        try:
            if self.signal_logger:
                # Обновить сигнал выходом в JSONL
                self.signal_logger.update_signal_exit(
                    signal_id=signal.id,
                    exit_reason=signal.exit_reason if signal.exit_reason else 'UNKNOWN',
                    timestamp_exit=signal.closed_at if signal.closed_at else datetime.now(pytz.UTC),
                    exit_price=float(signal.exit_price) if signal.exit_price else 0.0,
                    mfe_r=mfe_mae['mfe_r'],
                    mae_r=mfe_mae['mae_r']
                )
                logger.debug(f"✅ JSONL logged exit: {signal.id} - MFE: {mfe_mae['mfe_r']:.2f}R, MAE: {mfe_mae['mae_r']:.2f}R")
            else:
                logger.debug(f"Signal {signal.id} exit logged - MFE: {mfe_mae['mfe_r']:.2f}R, MAE: {mfe_mae['mae_r']:.2f}R (JSONL disabled)")
            
        except Exception as e:
            logger.error(f"Error logging signal exit: {e}", exc_info=True)
    
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
        direction = signal.direction.upper() if signal.direction else 'LONG'
        entry = float(signal.entry_price)
        sl = float(signal.stop_loss)
        tp1 = float(signal.take_profit_1) if signal.take_profit_1 else None
        tp2 = float(signal.take_profit_2) if signal.take_profit_2 else None
        
        # DEBUG: Логируем для первых 3 сигналов чтобы понять почему не срабатывает
        if len(self.signal_mfe_mae) <= 3:
            logger.debug(f"  [{signal.symbol}] Price: {current_price} | Dir: {direction} | Entry: {entry} | SL: {sl} | TP1: {tp1} | TP2: {tp2} | TP1_hit: {signal.partial_exit_1_at is not None}")
        
        # Проверка SL
        if direction == 'LONG' and current_price <= sl:
            # Если TP1 уже достигнут и SL = entry (breakeven), считаем TP1 PnL
            if signal.partial_exit_1_at and abs(sl - entry) < 0.0001:
                # Breakeven exit - сохраняем TP1 прибыль
                total_pnl = self._calculate_total_pnl(signal, sl, entry, is_breakeven=True)
                return {
                    'exit_price': sl,
                    'reason': 'BREAKEVEN',
                    'pnl_percent': total_pnl,
                    'pnl': total_pnl,
                    'status': 'WIN'  # Breakeven считается WIN (сохранили TP1 прибыль)
                }
            else:
                # Обычный SL
                pnl_pct = ((current_price - entry) / entry) * 100
                return {
                    'exit_price': sl,
                    'reason': 'STOP_LOSS',
                    'pnl_percent': pnl_pct,
                    'pnl': pnl_pct,
                    'status': 'LOSS'
                }
        elif direction == 'SHORT' and current_price >= sl:
            # Если TP1 уже достигнут и SL = entry (breakeven), считаем TP1 PnL
            if signal.partial_exit_1_at and abs(sl - entry) < 0.0001:
                # Breakeven exit - сохраняем TP1 прибыль
                total_pnl = self._calculate_total_pnl(signal, sl, entry, is_breakeven=True)
                return {
                    'exit_price': sl,
                    'reason': 'BREAKEVEN',
                    'pnl_percent': total_pnl,
                    'pnl': total_pnl,
                    'status': 'WIN'  # Breakeven считается WIN (сохранили TP1 прибыль)
                }
            else:
                # Обычный SL
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
                # КРИТИЧНО: Переносим SL в breakeven (entry price) для защиты прибыли
                signal.stop_loss = entry
                logger.info(f"🎯 AP TP1 hit: {signal.symbol} {signal.pattern_type} at {tp1}, SL moved to breakeven {entry}")
                # Не закрываем сигнал, продолжаем на TP2
                return None
            elif direction == 'SHORT' and current_price <= tp1:
                signal.partial_exit_1_at = datetime.now(pytz.UTC)
                signal.partial_exit_1_price = tp1
                # КРИТИЧНО: Переносим SL в breakeven (entry price) для защиты прибыли
                signal.stop_loss = entry
                logger.info(f"🎯 AP TP1 hit: {signal.symbol} {signal.pattern_type} at {tp1}, SL moved to breakeven {entry}")
                return None
        
        # Проверка TP2 (частичный выход 40%, остаток на trailing)
        if tp2 and not signal.partial_exit_2_at:
            if direction == 'LONG' and current_price >= tp2:
                # Записываем TP2 hit
                signal.partial_exit_2_at = datetime.now(pytz.UTC)
                signal.partial_exit_2_price = tp2
                logger.info(f"🎯🎯 AP TP2 hit: {signal.symbol} {signal.pattern_type} at {tp2}, trailing stop active for 30% remainder")
                # НЕ закрываем сигнал - остаток 30% на trailing stop
                return None
            elif direction == 'SHORT' and current_price <= tp2:
                # Записываем TP2 hit
                signal.partial_exit_2_at = datetime.now(pytz.UTC)
                signal.partial_exit_2_price = tp2
                logger.info(f"🎯🎯 AP TP2 hit: {signal.symbol} {signal.pattern_type} at {tp2}, trailing stop active for 30% remainder")
                # НЕ закрываем сигнал - остаток 30% на trailing stop
                return None
        
        # НОВОЕ: Trailing stop после TP2 (для остатка 30%)
        if signal.partial_exit_2_at:
            # Получить ATR из meta_data
            atr = None
            if signal.meta_data and 'atr_15m' in signal.meta_data:
                atr = signal.meta_data['atr_15m']
            
            if atr:
                # Trailing distance из config (1.2 ATR по умолчанию)
                trail_distance = atr * 1.2  # Можно взять из config если нужно
                
                # КРИТИЧНО: Используем БД поле для персистентности
                if signal.trailing_peak_price is None:
                    # Первая проверка после TP2 - установить пик и сохранить в БД
                    signal.trailing_peak_price = current_price
                    logger.debug(f"🎯 Trailing stop initialized: {signal.symbol} peak={current_price:.4f}")
                
                if direction == 'LONG':
                    # Обновить пик если цена выше (сохраняем в БД!)
                    if current_price > signal.trailing_peak_price:
                        signal.trailing_peak_price = current_price
                        logger.debug(f"📈 New peak (LONG): {signal.symbol} peak={current_price:.4f}")
                    
                    # Проверить trailing stop: откат от пика >= trail_distance
                    if signal.trailing_peak_price - current_price >= trail_distance:
                        total_pnl = self._calculate_total_pnl(signal, current_price, entry)
                        logger.info(f"🛑 AP Trailing Stop: {signal.symbol} peak {signal.trailing_peak_price:.4f} → current {current_price:.4f} (pullback {signal.trailing_peak_price - current_price:.4f} >= {trail_distance:.4f})")
                        return {
                            'exit_price': current_price,
                            'reason': 'TRAILING_STOP',
                            'pnl_percent': total_pnl,
                            'pnl': total_pnl,
                            'status': 'WIN'
                        }
                else:  # SHORT
                    # Обновить пик (минимум для SHORT) и сохранить в БД!
                    if current_price < signal.trailing_peak_price:
                        signal.trailing_peak_price = current_price
                        logger.debug(f"📉 New peak (SHORT): {signal.symbol} peak={current_price:.4f}")
                    
                    # Проверить trailing stop: откат от пика >= trail_distance
                    if current_price - signal.trailing_peak_price >= trail_distance:
                        total_pnl = self._calculate_total_pnl(signal, current_price, entry)
                        logger.info(f"🛑 AP Trailing Stop: {signal.symbol} peak {signal.trailing_peak_price:.4f} → current {current_price:.4f} (pullback {current_price - signal.trailing_peak_price:.4f} >= {trail_distance:.4f})")
                        return {
                            'exit_price': current_price,
                            'reason': 'TRAILING_STOP',
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
        
        # КРИТИЧНО: Time stop после TP2 (закрываем если висит > 72 часов после TP2)
        if signal.partial_exit_2_at:
            # Убедимся что partial_exit_2_at имеет timezone
            tp2_time = signal.partial_exit_2_at
            if tp2_time.tzinfo is None:
                tp2_time = pytz.UTC.localize(tp2_time)
            
            hours_since_tp2 = (datetime.now(pytz.UTC) - tp2_time).total_seconds() / 3600
            if hours_since_tp2 > 72:  # 3 дня после TP2
                # Закрываем остаток по текущей цене
                total_pnl = self._calculate_total_pnl(signal, current_price, entry)
                return {
                    'exit_price': current_price,
                    'reason': 'TIME_STOP_AFTER_TP2',
                    'pnl_percent': total_pnl,
                    'pnl': total_pnl,
                    'status': 'WIN' if total_pnl > 0 else 'LOSS'
                }
        
        # КРИТИЧНО: Time stop после TP1 (закрываем если висит > 48 часов после TP1)
        elif signal.partial_exit_1_at:
            # Убедимся что partial_exit_1_at имеет timezone
            tp1_time = signal.partial_exit_1_at
            if tp1_time.tzinfo is None:
                tp1_time = pytz.UTC.localize(tp1_time)
            
            hours_since_tp1 = (datetime.now(pytz.UTC) - tp1_time).total_seconds() / 3600
            if hours_since_tp1 > 48:
                # Закрываем по текущей цене (остаток 70%)
                total_pnl = self._calculate_total_pnl(signal, current_price, entry)
                return {
                    'exit_price': current_price,
                    'reason': 'TIME_STOP_AFTER_TP1',
                    'pnl_percent': total_pnl,
                    'pnl': total_pnl,
                    'status': 'WIN' if total_pnl > 0 else 'LOSS'
                }
        
        # Обычный time stop (7 дней максимум без TP1)
        # Убедимся что created_at имеет timezone
        created_time = signal.created_at
        if created_time.tzinfo is None:
            created_time = pytz.UTC.localize(created_time)
        
        hours_since_created = (datetime.now(pytz.UTC) - created_time).total_seconds() / 3600
        if hours_since_created > 168:  # 7 дней
            # Закрываем по текущей цене
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
    
    def _calculate_total_pnl(self, signal: ActionPriceSignal, 
                            final_exit_price: float, entry: float,
                            is_breakeven: bool = False) -> float:
        """
        Рассчитать общий PnL с учётом частичных фиксаций (30/40/30)
        
        Args:
            signal: Сигнал
            final_exit_price: Финальная цена выхода
            entry: Цена входа
            is_breakeven: True если выход по breakeven (SL=entry после TP1)
            
        Returns:
            Общий PnL в процентах
        """
        direction = signal.direction.upper() if signal.direction else 'LONG'
        
        # НОВАЯ СИСТЕМА 30/40/30
        tp1_size = 0.30  # 30% на TP1
        tp2_size = 0.40  # 40% на TP2
        trail_size = 0.30  # 30% на trailing
        
        # Проверяем наличие частичных выходов
        has_tp1 = signal.partial_exit_1_at and signal.partial_exit_1_price
        has_tp2 = signal.partial_exit_2_at and signal.partial_exit_2_price
        
        if has_tp1:
            tp1_price = float(signal.partial_exit_1_price)
            
            if has_tp2:
                # ВСЕ 3 УРОВНЯ: TP1 (30%) + TP2 (40%) + Trail (30%)
                tp2_price = float(signal.partial_exit_2_price)
                
                if direction == 'LONG':
                    pnl_tp1 = ((tp1_price - entry) / entry) * 100 * tp1_size
                    pnl_tp2 = ((tp2_price - entry) / entry) * 100 * tp2_size
                    
                    if is_breakeven:
                        pnl_trail = 0.0  # Breakeven после TP2
                    else:
                        pnl_trail = ((final_exit_price - entry) / entry) * 100 * trail_size
                else:  # SHORT
                    pnl_tp1 = ((entry - tp1_price) / entry) * 100 * tp1_size
                    pnl_tp2 = ((entry - tp2_price) / entry) * 100 * tp2_size
                    
                    if is_breakeven:
                        pnl_trail = 0.0
                    else:
                        pnl_trail = ((entry - final_exit_price) / entry) * 100 * trail_size
                
                total_pnl = pnl_tp1 + pnl_tp2 + pnl_trail
                logger.debug(f"PnL calc (3 levels): {signal.symbol} {direction} | TP1: {pnl_tp1:.2f}% (30%) + TP2: {pnl_tp2:.2f}% (40%) + Trail: {pnl_trail:.2f}% (30%) = Total: {total_pnl:.2f}%")
                return total_pnl
            else:
                # ТОЛЬКО TP1 + ОСТАТОК (70%): TP1 (30%) + Remainder (70%)
                remainder_size = tp2_size + trail_size  # 70%
                
                if direction == 'LONG':
                    pnl_tp1 = ((tp1_price - entry) / entry) * 100 * tp1_size
                    
                    if is_breakeven:
                        pnl_remainder = 0.0
                    else:
                        pnl_remainder = ((final_exit_price - entry) / entry) * 100 * remainder_size
                else:  # SHORT
                    pnl_tp1 = ((entry - tp1_price) / entry) * 100 * tp1_size
                    
                    if is_breakeven:
                        pnl_remainder = 0.0
                    else:
                        pnl_remainder = ((entry - final_exit_price) / entry) * 100 * remainder_size
                
                total_pnl = pnl_tp1 + pnl_remainder
                logger.debug(f"PnL calc (2 levels): {signal.symbol} {direction} | TP1: {pnl_tp1:.2f}% (30%) + Remainder: {pnl_remainder:.2f}% (70%) = Total: {total_pnl:.2f}%")
                return total_pnl
        else:
            # Полный выход без частичных фиксаций (100%)
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
                    'tp1_count': 0,
                    'tp2_count': 0,
                    'trailing_stop_count': 0,
                    'breakeven_count': 0,
                    'time_stop_count': 0
                }
            
            total = len(signals)
            closed = [s for s in signals if s.status in ['WIN', 'LOSS']]
            wins = [s for s in closed if s.status == 'WIN']
            losses = [s for s in closed if s.status == 'LOSS']
            
            # Подсчет exit reasons (взаимоисключающие)
            tp1_count = len([s for s in closed if s.exit_reason == 'TAKE_PROFIT_1'])
            tp2_count = len([s for s in closed if s.exit_reason == 'TAKE_PROFIT_2'])
            trailing_stop_count = len([s for s in closed if s.exit_reason == 'TRAILING_STOP'])
            breakeven_count = len([s for s in closed if s.exit_reason == 'BREAKEVEN'])
            time_stop_count = len([s for s in closed if 'TIME_STOP' in (s.exit_reason or '')])
            
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
                'tp1_count': tp1_count,
                'tp2_count': tp2_count,
                'trailing_stop_count': trailing_stop_count,  # НОВОЕ: Трейлинг стоп для 30% остатка
                'breakeven_count': breakeven_count,
                'time_stop_count': time_stop_count
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
