"""
Periodic Gap Refill - быстрая периодическая докачка gaps во время работы бота
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Set
import pytz
from sqlalchemy.orm import Session

from src.database.db import db
from src.database.models import Candle
from src.binance.data_loader import DataLoader
from src.utils.logger import logger


class PeriodicGapRefill:
    """
    Периодическая быстрая докачка gaps для разных таймфреймов
    """
    
    def __init__(self, data_loader: DataLoader, config: dict, timezone_str: str = "Europe/Kyiv"):
        self.data_loader = data_loader
        self.config = config.get('periodic_gap_refill', {})
        self.enabled = self.config.get('enabled', True)
        self.max_parallel = self.config.get('max_parallel', 8)
        self.lookback_minutes = self.config.get('lookback_minutes', 120)  # 2 часа назад
        self.timezone = pytz.timezone(timezone_str)
        self.startup_time = datetime.now(pytz.UTC)  # Запомнить время старта
        self.min_startup_delay_minutes = 15  # Не запускаться первые 15 минут
        self.max_rate_usage_percent = 30  # Запускаться только если rate < 30%
        
        # Таймфреймы для каждого расписания
        self.timeframe_map = {
            '15m': ['15m'],
            '1h': ['15m', '1h'],
            '4h': ['15m', '1h', '4h'],
            '1d': ['15m', '1h', '4h', '1d']
        }
    
    async def determine_timeframes_to_check(self) -> List[str]:
        """
        Определяет какие таймфреймы нужно проверить в зависимости от текущего времени
        """
        now = datetime.now(pytz.UTC)
        minute = now.minute
        hour = now.hour
        
        # Каждый день в 00:00 - все таймфреймы
        if hour == 0 and minute < 15:
            return self.timeframe_map['1d']
        
        # Каждые 4 часа (00, 04, 08, 12, 16, 20) - 15m, 1h, 4h
        if hour % 4 == 0 and minute < 15:
            return self.timeframe_map['4h']
        
        # Каждый час в XX:00 - 15m, 1h
        if minute < 15:
            return self.timeframe_map['1h']
        
        # Остальное время - только 15m
        return self.timeframe_map['15m']
    
    async def find_recent_gaps(self, symbols: List[str], timeframes: List[str]) -> Dict[str, Dict[str, dict]]:
        """
        Находит gaps за последние N минут для указанных символов и таймфреймов
        
        Returns:
            {symbol: {timeframe: {'start': datetime, 'end': datetime, 'count': int}}}
        """
        gaps = {}
        now = datetime.now(pytz.UTC)
        lookback_start = now - timedelta(minutes=self.lookback_minutes)
        
        session = db.get_session()
        try:
            for symbol in symbols:
                symbol_gaps = {}
                
                for tf in timeframes:
                    # Получить последнюю свечу
                    last_candle = session.query(Candle).filter(
                        Candle.symbol == symbol,
                        Candle.timeframe == tf
                    ).order_by(Candle.open_time.desc()).first()
                    
                    if not last_candle:
                        continue
                    
                    # Проверить gap между последней свечой и текущим временем
                    last_time = last_candle.open_time.replace(tzinfo=pytz.UTC)
                    
                    # Вычислить интервал для таймфрейма
                    interval_minutes = {
                        '15m': 15,
                        '1h': 60,
                        '4h': 240,
                        '1d': 1440
                    }.get(tf, 15)
                    
                    expected_next = last_time + timedelta(minutes=interval_minutes)
                    
                    # Если gap больше одного интервала - добавить
                    if expected_next < now - timedelta(minutes=interval_minutes):
                        # Докачиваем только recent gaps (последние lookback_minutes)
                        gap_start = max(expected_next, lookback_start)
                        gap_end = now
                        
                        if gap_start < gap_end:
                            gap_count = int((gap_end - gap_start).total_seconds() / 60 / interval_minutes)
                            
                            symbol_gaps[tf] = {
                                'start': gap_start,
                                'end': gap_end,
                                'count': gap_count
                            }
                
                if symbol_gaps:
                    gaps[symbol] = symbol_gaps
        finally:
            session.close()
        
        return gaps
    
    def calculate_request_weight(self, gaps: Dict[str, Dict[str, dict]]) -> int:
        """
        Подсчитывает общее количество запросов для докачки всех gaps
        
        Returns:
            Количество запросов (weight)
        """
        total_requests = 0
        for symbol, timeframe_gaps in gaps.items():
            # Каждый таймфрейм = 1 запрос (download_historical_klines)
            total_requests += len(timeframe_gaps)
        
        return total_requests
    
    def get_available_capacity(self) -> int:
        """
        Вычисляет доступный capacity для отправки запросов
        
        Returns:
            Количество доступных запросов до порога 55%
        """
        if not hasattr(self.data_loader, 'client') or not hasattr(self.data_loader.client, 'rate_limiter'):
            return 0
        
        usage = self.data_loader.client.rate_limiter.get_current_usage()
        current_count = usage.get('used', 0)
        max_count = usage.get('limit', 2400)
        safe_threshold = 0.55  # 55%
        
        safe_count = int(max_count * safe_threshold)
        available = safe_count - current_count
        
        return max(0, available)
    
    async def refill_gaps(self, gaps: Dict[str, Dict[str, dict]]) -> Dict[str, int]:
        """
        Интеллектуальная докачка gaps с калькулятором веса запросов
        
        Returns:
            {'success': count, 'failed': count}
        """
        if not gaps:
            return {'success': 0, 'failed': 0}
        
        # 1. Рассчитать вес запросов
        total_requests = self.calculate_request_weight(gaps)
        total_symbols = len(gaps)
        
        # 2. Получить доступный capacity
        available_capacity = self.get_available_capacity()
        
        # 3. Проверить MIN_BATCH_SIZE
        MIN_BATCH_SIZE = 50
        if available_capacity < MIN_BATCH_SIZE:
            logger.info(
                f"⏸️ Gap refill skipped: capacity too low\n"
                f"  📊 Available: {available_capacity} requests\n"
                f"  ⚠️ Minimum: {MIN_BATCH_SIZE} requests"
            )
            return {'success': 0, 'failed': 0}
        
        logger.info(
            f"⚡ PERIODIC GAP REFILL starting:\n"
            f"  📊 Symbols: {total_symbols}\n"
            f"  📈 Total requests: {total_requests}\n"
            f"  💾 Available capacity: {available_capacity}\n"
            f"  🎯 Strategy: {'Single batch' if total_requests <= available_capacity else 'Multiple batches with wait'}"
        )
        
        # 4. Определить стратегию выполнения
        symbols_list = list(gaps.items())  # FIFO порядок
        
        if total_requests <= available_capacity:
            # ✅ Всё влезает - отправляем за один раз (батчами для safety)
            return await self._execute_batch(symbols_list, batch_num=1, total_batches=1)
        else:
            # ⚠️ Не влезает - разбиваем на части
            return await self._execute_with_wait(symbols_list, available_capacity)
    
    async def _execute_batch(self, symbols_list: List[tuple], batch_num: int, total_batches: int) -> Dict[str, int]:
        """
        Выполняет докачку одного списка символов (батчами по 20 для safety)
        """
        BATCH_SIZE = 20
        BATCH_PAUSE = 1.0
        
        success_count = 0
        failed_count = 0
        
        total_mini_batches = (len(symbols_list) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for mini_batch_num in range(total_mini_batches):
            start_idx = mini_batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, len(symbols_list))
            mini_batch = symbols_list[start_idx:end_idx]
            
            # Обработать мини-батч параллельно (max 4 одновременно)
            semaphore = asyncio.Semaphore(4)
            tasks = []
            
            for symbol, timeframe_gaps in mini_batch:
                task = self._refill_symbol_gaps(symbol, timeframe_gaps, semaphore)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            batch_success = sum(1 for r in results if r is True)
            batch_failed = len(results) - batch_success
            
            success_count += batch_success
            failed_count += batch_failed
            
            if total_batches == -1:
                # Неизвестное количество батчей (циклический режим)
                logger.info(
                    f"  📦 Batch {batch_num} - Mini {mini_batch_num+1}/{total_mini_batches}: "
                    f"✅ {batch_success} / ❌ {batch_failed}"
                )
            elif total_batches > 1:
                # Известное количество батчей
                logger.info(
                    f"  📦 Batch {batch_num}/{total_batches} - Mini {mini_batch_num+1}/{total_mini_batches}: "
                    f"✅ {batch_success} / ❌ {batch_failed}"
                )
            else:
                # Один батч
                logger.info(
                    f"  📦 Mini-batch {mini_batch_num+1}/{total_mini_batches}: "
                    f"✅ {batch_success} / ❌ {batch_failed}"
                )
            
            # Пауза между мини-батчами
            if mini_batch_num < total_mini_batches - 1:
                await asyncio.sleep(BATCH_PAUSE)
        
        return {'success': success_count, 'failed': failed_count}
    
    async def _execute_with_wait(self, symbols_list: List[tuple], available_capacity: int) -> Dict[str, int]:
        """
        Выполняет докачку с ожиданием сброса rate limit
        Использует ТОЧНЫЙ расчет веса и циклические wait при необходимости
        """
        total_success = 0
        total_failed = 0
        remaining_symbols = symbols_list.copy()
        batch_num = 0
        
        while remaining_symbols:
            batch_num += 1
            
            # Пересчитать available capacity перед каждым батчем
            current_capacity = self.get_available_capacity()
            
            if current_capacity < 10:  # Safety минимум
                logger.warning(
                    f"  ⚠️ Capacity too low ({current_capacity}), waiting 60s for rate reset..."
                )
                await asyncio.sleep(60)
                continue
            
            # Аккумулировать символы строго под capacity (ТОЧНЫЙ вес)
            batch_symbols = []
            accumulated_weight = 0
            
            for symbol, timeframe_gaps in remaining_symbols:
                symbol_weight = len(timeframe_gaps)  # Точный вес: 1-4 requests
                
                if accumulated_weight + symbol_weight <= current_capacity:
                    batch_symbols.append((symbol, timeframe_gaps))
                    accumulated_weight += symbol_weight
                else:
                    # Превысим capacity - остановить аккумуляцию
                    break
            
            if not batch_symbols:
                # Ни один символ не влез - ждём reset
                logger.warning(
                    f"  ⚠️ No symbols fit in capacity ({current_capacity}), waiting 60s..."
                )
                await asyncio.sleep(60)
                continue
            
            # Убрать отправленные символы из remaining
            remaining_symbols = remaining_symbols[len(batch_symbols):]
            
            logger.info(
                f"  🔄 Batch {batch_num}:\n"
                f"    Symbols: {len(batch_symbols)}\n"
                f"    Weight: {accumulated_weight} requests\n"
                f"    Capacity: {current_capacity}\n"
                f"    Remaining: {len(remaining_symbols)} symbols"
            )
            
            # Отправить батч (total_batches=-1 означает "неизвестно заранее")
            result = await self._execute_batch(batch_symbols, batch_num=batch_num, total_batches=-1)
            total_success += result['success']
            total_failed += result['failed']
            
            # Если остались символы - ждать reset перед следующим батчем
            if remaining_symbols:
                logger.info(
                    f"  ⏳ Waiting 60s for rate limit reset before next batch..."
                )
                await asyncio.sleep(60)
        
        logger.info(
            f"⚡ PERIODIC GAP REFILL complete:\n"
            f"  ✅ Success: {total_success} symbols\n"
            f"  ❌ Failed: {total_failed} symbols\n"
            f"  📦 Total batches: {batch_num}"
        )
        
        return {'success': total_success, 'failed': total_failed}
    
    async def _refill_symbol_gaps(self, symbol: str, gaps: Dict[str, dict], semaphore) -> bool:
        """
        Докачивает gaps для одного символа (все таймфреймы)
        """
        async with semaphore:
            try:
                for tf, gap_info in gaps.items():
                    # Проверить rate limit перед запросом (90% порог)
                    if hasattr(self.data_loader, 'client') and hasattr(self.data_loader.client, 'rate_limiter'):
                        usage = self.data_loader.client.rate_limiter.get_current_usage()
                        if usage.get('is_near_limit', False):
                            logger.info(
                                f"⏸️ Pausing gap refill: rate limit at "
                                f"{usage['percent_of_safe']:.1f}% of safe threshold"
                            )
                            # Подождать сброса лимита
                            await self.data_loader.client.rate_limiter.wait_if_near_limit(weight=5)
                    
                    # Загрузить gap
                    df = await self.data_loader.download_historical_klines(
                        symbol, tf,
                        start_date=gap_info['start'],
                        end_date=gap_info['end']
                    )
                    
                    if df is not None and len(df) > 0:
                        logger.debug(
                            f"  ✅ {symbol} {tf}: +{len(df)} candles "
                            f"({gap_info['start'].strftime('%H:%M')} → {gap_info['end'].strftime('%H:%M')})"
                        )
                
                return True
                
            except Exception as e:
                logger.error(f"  ❌ {symbol} refill failed: {e}")
                return False
    
    async def run_periodic_check(self, symbols: List[str]):
        """
        Основной метод периодической проверки и докачки gaps
        """
        if not self.enabled:
            return
        
        now = datetime.now(pytz.UTC)
        
        # КРИТИЧНО: Не запускаться первые 15 минут после старта (burst catchup может быть активен)
        time_since_startup = (now - self.startup_time).total_seconds() / 60
        if time_since_startup < self.min_startup_delay_minutes:
            logger.info(
                f"⏸️ Gap refill skipped: bot running only {time_since_startup:.1f}min "
                f"(waiting {self.min_startup_delay_minutes}min after startup)"
            )
            return
        
        # КРИТИЧНО: Проверить rate usage - запускаться только если < 30%
        if hasattr(self.data_loader, 'client') and hasattr(self.data_loader.client, 'rate_limiter'):
            usage = self.data_loader.client.rate_limiter.get_current_usage()
            current_percent = usage.get('percent', 0)
            
            if current_percent > self.max_rate_usage_percent:
                logger.info(
                    f"⏸️ Gap refill skipped: rate usage too high "
                    f"({current_percent:.1f}% > {self.max_rate_usage_percent}%)"
                )
                return
        
        # Определить какие таймфреймы проверять
        timeframes = await self.determine_timeframes_to_check()
        
        logger.info(
            f"🔄 Periodic gap check started:\n"
            f"  🕐 Time: {now.strftime('%H:%M UTC')}\n"
            f"  📊 Timeframes to check: {', '.join(timeframes)}\n"
            f"  📈 Symbols: {len(symbols)}"
        )
        
        # Найти gaps
        gaps = await self.find_recent_gaps(symbols, timeframes)
        
        if gaps:
            logger.info(f"  📊 Found {len(gaps)} symbols with gaps")
            # Докачать gaps параллельно
            await self.refill_gaps(gaps)
        else:
            logger.info("  ✅ No gaps found")
