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
        
        # Первая проверка - закрыть старые сигналы по историческим свечам
        try:
            await self._backfill_check()
        except Exception as e:
            logger.error(f"Error in backfill check: {e}", exc_info=True)
        
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
    
    async def _backfill_check(self):
        """Проверить все активные сигналы по историческим свечам (закрыть старые)"""
        session = self.db.get_session()
        try:
            active_signals = session.query(Signal).filter(
                Signal.status.in_(['ACTIVE', 'PENDING'])
            ).all()
            
            if not active_signals:
                return
            
            logger.info(f"🔍 Backfill check: checking {len(active_signals)} active signals against historical candles")
            closed_count = 0
            
            for signal in active_signals:
                try:
                    closed = await self._check_signal_historical(signal, session)
                    if closed:
                        closed_count += 1
                except Exception as e:
                    logger.error(f"Error in backfill check for signal {signal.id}: {e}", exc_info=True)
            
            session.commit()
            
            if closed_count > 0:
                logger.info(f"✅ Backfill complete: closed {closed_count}/{len(active_signals)} signals")
            else:
                logger.info(f"✅ Backfill complete: all signals still active")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error in backfill check: {e}", exc_info=True)
        finally:
            session.close()
    
    async def _check_signal_historical(self, signal: Signal, session) -> bool:
        """Проверить сигнал по историческим свечам с trailing stop-loss"""
        try:
            symbol = str(signal.symbol)
            timeframe = str(signal.timeframe)
            entry = float(signal.entry_price)
            original_sl = float(signal.stop_loss)
            tp1 = float(signal.take_profit_1) if signal.take_profit_1 else None
            tp2 = float(signal.take_profit_2) if signal.take_profit_2 else None
            direction = str(signal.direction)
            tp1_hit = bool(signal.tp1_hit) if hasattr(signal, 'tp1_hit') and signal.tp1_hit is not None else False
            risk = abs(entry - original_sl)
            
            # Текущий SL (может быть изменен после TP1)
            current_sl = float(signal.stop_loss)
            
            # Ensure created_at is timezone-aware
            created_at = signal.created_at
            if created_at.tzinfo is None:
                created_at = pytz.UTC.localize(created_at)
            
            # Получить свечи с момента создания сигнала
            now = datetime.now(pytz.UTC)
            
            # Получаем данные из БД
            from src.database.models import Candle
            klines = session.query(Candle).filter(
                and_(
                    Candle.symbol == symbol,
                    Candle.timeframe == timeframe,
                    Candle.open_time >= created_at,
                    Candle.open_time <= now
                )
            ).order_by(Candle.open_time).all()
            
            if not klines:
                return False
            
            # Проверить каждую свечу на SL/TP с trailing логикой
            for kline in klines:
                high = float(kline.high)
                low = float(kline.low)
                
                if direction == "LONG":
                    # Если TP1 УЖЕ достигнут - проверяем TP2 и breakeven
                    if tp1_hit:
                        # Проверка TP2
                        if tp2 and high >= tp2:
                            pnl_percent = (tp2 - entry) / entry * 100
                            signal.status = "WIN"
                            signal.exit_price = tp2
                            signal.exit_reason = "WIN"
                            signal.exit_type = "TP2"
                            signal.pnl_percent = pnl_percent
                            signal.closed_at = kline.open_time
                            
                            self.lock_manager.release_lock(symbol)
                            if self.on_signal_closed_callback:
                                self.on_signal_closed_callback(symbol)
                            
                            logger.info(f"✅ Signal closed (historical): {symbol} LONG | TP2 (+{pnl_percent:.2f}%)")
                            return True
                        
                        # Проверка breakeven (SL = entry)
                        if low <= entry:
                            pnl_percent = 0.0
                            signal.status = "WIN"
                            signal.exit_price = entry
                            signal.exit_reason = "WIN"
                            signal.exit_type = "TP1"
                            signal.pnl_percent = pnl_percent
                            signal.closed_at = kline.open_time
                            
                            self.lock_manager.release_lock(symbol)
                            if self.on_signal_closed_callback:
                                self.on_signal_closed_callback(symbol)
                            
                            logger.info(f"✅ Signal closed (historical): {symbol} LONG | Breakeven after TP1 (+{pnl_percent:.2f}%)")
                            return True
                    
                    # Если TP1 ЕЩЁ НЕ достигнут
                    else:
                        # Проверка SL
                        if low <= current_sl:
                            pnl_percent = (current_sl - entry) / entry * 100
                            signal.status = "LOSS"
                            signal.exit_price = current_sl
                            signal.exit_reason = "LOSS"
                            signal.exit_type = "SL"
                            signal.pnl_percent = pnl_percent
                            signal.closed_at = kline.open_time
                            
                            self.lock_manager.release_lock(symbol)
                            if self.on_signal_closed_callback:
                                self.on_signal_closed_callback(symbol)
                            
                            logger.info(f"❌ Signal closed (historical): {symbol} LONG | SL ({pnl_percent:.2f}%)")
                            return True
                        
                        # Проверка TP2 (достигли сразу без TP1)
                        if tp2 and high >= tp2:
                            pnl_percent = (tp2 - entry) / entry * 100
                            signal.status = "WIN"
                            signal.exit_price = tp2
                            signal.exit_reason = "WIN"
                            signal.exit_type = "TP2"
                            signal.pnl_percent = pnl_percent
                            signal.closed_at = kline.open_time
                            
                            self.lock_manager.release_lock(symbol)
                            if self.on_signal_closed_callback:
                                self.on_signal_closed_callback(symbol)
                            
                            logger.info(f"✅ Signal closed (historical): {symbol} LONG | TP2 direct (+{pnl_percent:.2f}%)")
                            return True
                        
                        # Проверка TP1 - ЧАСТИЧНОЕ ЗАКРЫТИЕ
                        if tp1 and high >= tp1:
                            signal.tp1_hit = True
                            signal.tp1_closed_at = kline.open_time
                            signal.stop_loss = entry  # ПЕРЕНОС SL В BREAKEVEN
                            current_sl = entry
                            tp1_hit = True
                            
                            logger.info(f"📈 TP1 HIT (historical): {symbol} LONG | SL moved to breakeven")
                            # НЕ закрываем сигнал, продолжаем проверку
                
                elif direction == "SHORT":
                    # Если TP1 УЖЕ достигнут - проверяем TP2 и breakeven
                    if tp1_hit:
                        # Проверка TP2
                        if tp2 and low <= tp2:
                            pnl_percent = (entry - tp2) / entry * 100
                            signal.status = "WIN"
                            signal.exit_price = tp2
                            signal.exit_reason = "WIN"
                            signal.exit_type = "TP2"
                            signal.pnl_percent = pnl_percent
                            signal.closed_at = kline.open_time
                            
                            self.lock_manager.release_lock(symbol)
                            if self.on_signal_closed_callback:
                                self.on_signal_closed_callback(symbol)
                            
                            logger.info(f"✅ Signal closed (historical): {symbol} SHORT | TP2 (+{pnl_percent:.2f}%)")
                            return True
                        
                        # Проверка breakeven (SL = entry)
                        if high >= entry:
                            pnl_percent = 0.0
                            signal.status = "WIN"
                            signal.exit_price = entry
                            signal.exit_reason = "WIN"
                            signal.exit_type = "TP1"
                            signal.pnl_percent = pnl_percent
                            signal.closed_at = kline.open_time
                            
                            self.lock_manager.release_lock(symbol)
                            if self.on_signal_closed_callback:
                                self.on_signal_closed_callback(symbol)
                            
                            logger.info(f"✅ Signal closed (historical): {symbol} SHORT | Breakeven after TP1 (+{pnl_percent:.2f}%)")
                            return True
                    
                    # Если TP1 ЕЩЁ НЕ достигнут
                    else:
                        # Проверка SL
                        if high >= current_sl:
                            pnl_percent = (entry - current_sl) / entry * 100
                            signal.status = "LOSS"
                            signal.exit_price = current_sl
                            signal.exit_reason = "LOSS"
                            signal.exit_type = "SL"
                            signal.pnl_percent = pnl_percent
                            signal.closed_at = kline.open_time
                            
                            self.lock_manager.release_lock(symbol)
                            if self.on_signal_closed_callback:
                                self.on_signal_closed_callback(symbol)
                            
                            logger.info(f"❌ Signal closed (historical): {symbol} SHORT | SL ({pnl_percent:.2f}%)")
                            return True
                        
                        # Проверка TP2 (достигли сразу без TP1)
                        if tp2 and low <= tp2:
                            pnl_percent = (entry - tp2) / entry * 100
                            signal.status = "WIN"
                            signal.exit_price = tp2
                            signal.exit_reason = "WIN"
                            signal.exit_type = "TP2"
                            signal.pnl_percent = pnl_percent
                            signal.closed_at = kline.open_time
                            
                            self.lock_manager.release_lock(symbol)
                            if self.on_signal_closed_callback:
                                self.on_signal_closed_callback(symbol)
                            
                            logger.info(f"✅ Signal closed (historical): {symbol} SHORT | TP2 direct (+{pnl_percent:.2f}%)")
                            return True
                        
                        # Проверка TP1 - ЧАСТИЧНОЕ ЗАКРЫТИЕ
                        if tp1 and low <= tp1:
                            signal.tp1_hit = True
                            signal.tp1_closed_at = kline.open_time
                            signal.stop_loss = entry  # ПЕРЕНОС SL В BREAKEVEN
                            current_sl = entry
                            tp1_hit = True
                            
                            logger.info(f"📉 TP1 HIT (historical): {symbol} SHORT | SL moved to breakeven")
                            # НЕ закрываем сигнал, продолжаем проверку
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking signal {signal.id} historical: {e}", exc_info=True)
            return False
    
    async def _check_active_signals(self):
        """Проверить все активные сигналы"""
        session = self.db.get_session()
        try:
            active_signals = session.query(Signal).filter(
                Signal.status.in_(['ACTIVE', 'PENDING'])
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
                exit_reason, exit_price, pnl_r, exit_type = exit_result
                
                signal.status = exit_reason  # type: ignore
                signal.exit_price = exit_price  # type: ignore
                signal.exit_reason = exit_reason  # type: ignore
                signal.pnl_percent = pnl_r  # type: ignore
                signal.exit_type = exit_type  # type: ignore
                signal.closed_at = datetime.now(pytz.UTC)  # type: ignore
                
                self.lock_manager.release_lock(symbol_str)
                
                # Вызвать callback для разблокировки символа
                if self.on_signal_closed_callback:
                    self.on_signal_closed_callback(symbol_str)
                
                status_emoji = "✅" if exit_reason == "WIN" else "❌" if exit_reason == "LOSS" else "⏱️"
                logger.info(
                    f"{status_emoji} Signal closed: {signal.symbol} {signal.direction} "
                    f"| Entry: {signal.entry_price:.4f} → Exit: {exit_price:.4f} "
                    f"| PnL: {pnl_r:+.2f}% ({exit_type})"
                )
                
        except Exception as e:
            logger.error(f"Error checking signal {signal.id} ({signal.symbol}): {e}")
    
    def _check_exit_conditions(self, signal: Signal, current_price: float) -> Optional[tuple]:
        """
        Проверить условия выхода для сигнала с trailing stop-loss
        
        Логика:
        1. Если TP1 не достигнут:
           - Проверить SL, TP2, TP1
           - При достижении TP1: перенести SL в breakeven, записать 0.5R, продолжить
        2. Если TP1 уже достигнут:
           - Проверить breakeven (новый SL) -> закрыть с 0.5R
           - Проверить TP2 -> закрыть с 1.5R
        
        Returns:
            tuple (exit_reason, exit_price, pnl_percent, exit_type) или None если выхода нет
        """
        entry = float(signal.entry_price)  # type: ignore
        sl = float(signal.stop_loss)  # type: ignore
        tp1 = float(signal.take_profit_1) if signal.take_profit_1 else None  # type: ignore
        tp2 = float(signal.take_profit_2) if signal.take_profit_2 else None  # type: ignore
        direction = str(signal.direction)  # type: ignore
        tp1_hit = bool(signal.tp1_hit) if hasattr(signal, 'tp1_hit') and signal.tp1_hit is not None else False  # type: ignore
        
        # Если TP1 УЖЕ достигнут - проверяем breakeven и TP2
        if tp1_hit:
            if direction == "LONG":
                # Проверка TP2 (приоритет выше)
                if tp2 and current_price >= tp2:
                    pnl_percent = (tp2 - entry) / entry * 100
                    signal.exit_type = "TP2"  # type: ignore
                    return ("WIN", tp2, pnl_percent, "TP2")
                
                # Проверка breakeven (SL перенесен в entry)
                if current_price <= entry:
                    # ИСПОЛЬЗОВАТЬ СОХРАНЁННЫЙ PnL от TP1 вместо 0%
                    tp1_pnl_saved = float(signal.tp1_pnl_percent) if hasattr(signal, 'tp1_pnl_percent') and signal.tp1_pnl_percent else 0.0  # type: ignore
                    signal.exit_type = "BREAKEVEN"  # type: ignore
                    return ("WIN", entry, tp1_pnl_saved, "BREAKEVEN")
            
            elif direction == "SHORT":
                # Проверка TP2 (приоритет выше)
                if tp2 and current_price <= tp2:
                    pnl_percent = (entry - tp2) / entry * 100
                    signal.exit_type = "TP2"  # type: ignore
                    return ("WIN", tp2, pnl_percent, "TP2")
                
                # Проверка breakeven (SL перенесен в entry)
                if current_price >= entry:
                    # ИСПОЛЬЗОВАТЬ СОХРАНЁННЫЙ PnL от TP1 вместо 0%
                    tp1_pnl_saved = float(signal.tp1_pnl_percent) if hasattr(signal, 'tp1_pnl_percent') and signal.tp1_pnl_percent else 0.0  # type: ignore
                    signal.exit_type = "BREAKEVEN"  # type: ignore
                    return ("WIN", entry, tp1_pnl_saved, "BREAKEVEN")
        
        # Если TP1 ЕЩЁ НЕ достигнут - обычная проверка
        else:
            if direction == "LONG":
                # Проверка SL
                if current_price <= sl:
                    pnl_percent = (sl - entry) / entry * 100
                    signal.exit_type = "SL"  # type: ignore
                    return ("LOSS", sl, pnl_percent, "SL")
                
                # Проверка TP2 (если достигли сразу)
                if tp2 and current_price >= tp2:
                    pnl_percent = (tp2 - entry) / entry * 100
                    signal.exit_type = "TP2"  # type: ignore
                    return ("WIN", tp2, pnl_percent, "TP2")
                
                # Проверка TP1 - ЧАСТИЧНОЕ ЗАКРЫТИЕ
                if tp1 and current_price >= tp1:
                    # Установить флаг TP1 и перенести SL в breakeven
                    signal.tp1_hit = True  # type: ignore
                    signal.tp1_closed_at = datetime.now(pytz.UTC)  # type: ignore
                    signal.stop_loss = entry  # type: ignore - ПЕРЕНОС SL В BREAKEVEN
                    
                    tp1_pnl = (tp1 - entry) / entry * 100
                    signal.tp1_pnl_percent = tp1_pnl  # type: ignore - СОХРАНИТЬ PnL от TP1
                    logger.info(
                        f"📈 TP1 HIT: {signal.symbol} {signal.direction} "
                        f"| Partial close at {tp1:.4f} (+{tp1_pnl:.2f}%) "
                        f"| SL moved to breakeven {entry:.4f}"
                    )
                    return None
            
            elif direction == "SHORT":
                # Проверка SL
                if current_price >= sl:
                    pnl_percent = (entry - sl) / entry * 100
                    signal.exit_type = "SL"  # type: ignore
                    return ("LOSS", sl, pnl_percent, "SL")
                
                # Проверка TP2 (если достигли сразу)
                if tp2 and current_price <= tp2:
                    pnl_percent = (entry - tp2) / entry * 100
                    signal.exit_type = "TP2"  # type: ignore
                    return ("WIN", tp2, pnl_percent, "TP2")
                
                # Проверка TP1 - ЧАСТИЧНОЕ ЗАКРЫТИЕ
                if tp1 and current_price <= tp1:
                    # Установить флаг TP1 и перенести SL в breakeven
                    signal.tp1_hit = True  # type: ignore
                    signal.tp1_closed_at = datetime.now(pytz.UTC)  # type: ignore
                    signal.stop_loss = entry  # type: ignore - ПЕРЕНОС SL В BREAKEVEN
                    
                    tp1_pnl = (entry - tp1) / entry * 100
                    signal.tp1_pnl_percent = tp1_pnl  # type: ignore - СОХРАНИТЬ PnL от TP1
                    logger.info(
                        f"📉 TP1 HIT: {signal.symbol} {signal.direction} "
                        f"| Partial close at {tp1:.4f} (+{tp1_pnl:.2f}%) "
                        f"| SL moved to breakeven {entry:.4f}"
                    )
                    return None
        
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
        sl = float(signal.stop_loss)  # type: ignore
        direction = str(signal.direction)  # type: ignore
        risk = abs(entry - sl)
        
        atr_threshold = 0.5
        
        if direction == "LONG":
            required_move = entry * (atr_threshold / 100)
            if current_price < entry + required_move:
                pnl = current_price - entry
                pnl_r = pnl / risk if risk > 0 else 0
                signal.exit_type = "TIME_STOP"  # type: ignore
                return ("TIME_STOP", current_price, pnl_r, "TIME_STOP")
        
        elif direction == "SHORT":
            required_move = entry * (atr_threshold / 100)
            if current_price > entry - required_move:
                pnl = entry - current_price
                pnl_r = pnl / risk if risk > 0 else 0
                signal.exit_type = "TIME_STOP"  # type: ignore
                return ("TIME_STOP", current_price, pnl_r, "TIME_STOP")
        
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
                    'tp1_count': 0,
                    'tp2_count': 0,
                    'breakeven_count': 0,
                    'time_stop_count': 0,
                    'win_rate': 0.0,
                    'avg_pnl': 0.0,
                    'total_pnl': 0.0,
                    'avg_win': 0.0,
                    'avg_loss': 0.0,
                    'time_stop_total_pnl': 0.0,
                    'time_stop_avg_pnl': 0.0
                }
            
            total = len(signals)
            closed = [s for s in signals if str(s.status) in ['WIN', 'LOSS', 'TIME_STOP']]  # type: ignore
            wins = [s for s in closed if str(s.status) == 'WIN']  # type: ignore
            losses = [s for s in closed if str(s.status) == 'LOSS']  # type: ignore
            time_stops = [s for s in closed if str(s.status) == 'TIME_STOP']  # type: ignore
            
            # Подсчет TP1, TP2 и BREAKEVEN
            tp1_count = len([s for s in closed if hasattr(s, 'exit_type') and s.exit_type == 'TP1'])  # type: ignore
            tp2_count = len([s for s in closed if hasattr(s, 'exit_type') and s.exit_type == 'TP2'])  # type: ignore
            breakeven_count = len([s for s in closed if hasattr(s, 'exit_type') and s.exit_type == 'BREAKEVEN'])  # type: ignore
            
            win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
            
            closed_with_pnl = [s for s in closed if s.pnl_percent is not None]  # type: ignore
            avg_pnl = sum(float(s.pnl_percent) for s in closed_with_pnl) / len(closed_with_pnl) if closed_with_pnl else 0.0  # type: ignore
            total_pnl = sum(float(s.pnl_percent) for s in closed_with_pnl)  # type: ignore
            
            wins_with_pnl = [s for s in wins if s.pnl_percent is not None]  # type: ignore
            losses_with_pnl = [s for s in losses if s.pnl_percent is not None]  # type: ignore
            time_stops_with_pnl = [s for s in time_stops if s.pnl_percent is not None]  # type: ignore
            
            # Статистика TIME_STOP отдельно
            time_stop_count = len(time_stops)
            time_stop_total_pnl = sum(float(s.pnl_percent) for s in time_stops_with_pnl) if time_stops_with_pnl else 0.0  # type: ignore
            time_stop_avg_pnl = time_stop_total_pnl / len(time_stops_with_pnl) if time_stops_with_pnl else 0.0
            
            return {
                'total_signals': total,
                'closed_signals': len(closed),
                'active_signals': total - len(closed),
                'wins': len(wins),
                'losses': len(losses),
                'tp1_count': tp1_count,
                'tp2_count': tp2_count,
                'breakeven_count': breakeven_count,
                'time_stop_count': time_stop_count,
                'win_rate': round(win_rate, 2),
                'avg_pnl': round(avg_pnl, 2),
                'total_pnl': round(total_pnl, 2),
                'avg_win': round(sum(float(s.pnl_percent) for s in wins_with_pnl) / len(wins_with_pnl), 2) if wins_with_pnl else 0.0,  # type: ignore
                'avg_loss': round(sum(float(s.pnl_percent) for s in losses_with_pnl) / len(losses_with_pnl), 2) if losses_with_pnl else 0.0,  # type: ignore
                'time_stop_total_pnl': round(time_stop_total_pnl, 2),
                'time_stop_avg_pnl': round(time_stop_avg_pnl, 2)
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
