"""
Fast Catchup Loader - Быстрая догрузка gaps при рестарте бота
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import pytz
from src.database.models import Candle

logger = logging.getLogger('trading_bot')


class FastCatchupLoader:
    """Умная система быстрой догрузки gaps при рестарте"""
    
    def __init__(self, data_loader, db):
        """
        Args:
            data_loader: DataLoader instance
            db: Database session
        """
        self.data_loader = data_loader
        self.db = db
        self.timeframes = ['15m', '1h', '4h', '1d']
        
    def analyze_restart_state(self, symbols: List[str], current_time: datetime) -> Tuple[Dict, List[str]]:
        """
        Анализировать состояние БД и определить стратегию загрузки
        
        Args:
            symbols: Список всех символов для проверки
            current_time: Текущее время UTC
            
        Returns:
            (existing_gaps, new_symbols) - символы с gaps и новые символы
        """
        existing_gaps = {}
        new_symbols = []
        
        logger.info("📊 Analyzing restart state...")
        
        for symbol in symbols:
            gaps = self._calculate_symbol_gaps(symbol, current_time)
            
            if gaps:
                # Есть данные в БД, но есть gaps
                existing_gaps[symbol] = gaps
            elif not self._has_any_data(symbol):
                # Совсем новый символ
                new_symbols.append(symbol)
        
        total_gap_requests = sum(len(gaps) for gaps in existing_gaps.values())
        
        logger.info(
            f"📊 Restart analysis:\n"
            f"  ✅ Existing symbols with gaps: {len(existing_gaps)} ({total_gap_requests} total requests)\n"
            f"  🆕 New symbols: {len(new_symbols)}\n"
            f"  📈 Total symbols: {len(symbols)}"
        )
        
        return existing_gaps, new_symbols
    
    def _is_data_fresh(self, last_candle_time: datetime, interval: str, current_time: datetime) -> bool:
        """Проверить свежесть данных - актуальна ли последняя свеча для текущего времени
        
        Args:
            last_candle_time: Время открытия последней свечи в БД
            interval: Таймфрейм (15m, 1h, 4h, 1d)
            current_time: Текущее время (UTC)
        
        Returns:
            bool: True если данные свежие (последняя свеча покрывает текущее время)
        
        Example:
            Сейчас 18:40, interval=15m:
            - Текущая свеча: 18:30-18:45 (еще не закрылась)
            - Если last_candle_time >= 18:30 → данные СВЕЖИЕ ✅
            - Если last_candle_time = 18:15 → данные УСТАРЕЛИ ⚠️ (пропущена свеча 18:30)
        """
        # Интервалы в минутах
        interval_minutes = {
            '15m': 15,
            '1h': 60,
            '4h': 240,
            '1d': 1440
        }.get(interval, 15)
        
        # Для дневного таймфрейма специальная логика
        if interval == '1d':
            # Текущий день начался в 00:00 UTC
            current_day_start = datetime(
                current_time.year, current_time.month, current_time.day,
                0, 0, 0, tzinfo=pytz.UTC
            )
            # Если последняя свеча = вчерашний день, данные свежие
            # (сегодняшняя свеча еще не закрылась)
            yesterday_start = current_day_start - timedelta(days=1)
            return last_candle_time >= yesterday_start
        
        # Для внутридневных таймфреймов: найти начало текущей свечи
        minutes_since_midnight = current_time.hour * 60 + current_time.minute
        candles_since_midnight = minutes_since_midnight // interval_minutes
        current_candle_start_minutes = candles_since_midnight * interval_minutes
        
        current_candle_start = current_time.replace(
            hour=current_candle_start_minutes // 60,
            minute=current_candle_start_minutes % 60,
            second=0,
            microsecond=0
        )
        
        # Если последняя свеча >= начала текущей свечи, данные свежие
        return last_candle_time >= current_candle_start
    
    def _get_current_candle_start(self, current_time: datetime, interval: str) -> datetime:
        """
        Получить начало текущей (незакрытой) свечи
        
        Это время последней ЗАКРЫТОЙ свечи, которую можно запросить у Binance.
        
        Args:
            current_time: Текущее время (UTC)
            interval: Таймфрейм (15m, 1h, 4h, 1d)
        
        Returns:
            Время начала текущей свечи
        
        Example:
            Сейчас 23:51, interval=1h:
            - Текущая свеча: 23:00-00:00 (еще не закрылась)
            - Вернет: 23:00 (последняя доступная для загрузки)
        """
        interval_minutes = {
            '15m': 15,
            '1h': 60,
            '4h': 240,
            '1d': 1440
        }.get(interval, 15)
        
        # Для дневного таймфрейма
        if interval == '1d':
            current_day_start = datetime(
                current_time.year, current_time.month, current_time.day,
                0, 0, 0, tzinfo=pytz.UTC
            )
            # Сегодняшняя свеча еще не закрылась, вернуть вчерашний день
            return current_day_start - timedelta(days=1)
        
        # Для внутридневных таймфреймов
        minutes_since_midnight = current_time.hour * 60 + current_time.minute
        candles_since_midnight = minutes_since_midnight // interval_minutes
        current_candle_start_minutes = candles_since_midnight * interval_minutes
        
        return current_time.replace(
            hour=current_candle_start_minutes // 60,
            minute=current_candle_start_minutes % 60,
            second=0,
            microsecond=0
        )
    
    def _calculate_symbol_gaps(self, symbol: str, current_time: datetime) -> Dict[str, Dict]:
        """
        Рассчитать gaps для одного символа
        
        ОПТИМИЗАЦИЯ: Проверяет свежесть данных ПЕРЕД определением gap.
        - Если данные свежие → gap не создается (пропуск запроса к Binance)
        - Если устарели → создается gap только для недостающих свечей
        - Gap end = начало текущей свечи (последняя закрытая), НЕ current_time
        
        Returns:
            Dict[timeframe, {'start': datetime, 'end': datetime, 'candles_needed': int}]
        """
        gaps = {}
        
        for tf in self.timeframes:
            last_candle_time = self._get_last_candle_time(symbol, tf)
            
            if last_candle_time:
                # ✅ ОПТИМИЗАЦИЯ: Проверка свежести перед созданием gap
                if self._is_data_fresh(last_candle_time, tf, current_time):
                    # Данные свежие - пропускаем, gap НЕ нужен
                    continue
                
                # Данные устарели - создаем gap
                expected_next = self._get_next_candle_time(last_candle_time, tf)
                
                # ✅ FIX: Использовать начало текущей свечи, а не current_time
                # Текущая свеча еще не закрылась, Binance её не вернет
                current_candle_start = self._get_current_candle_start(current_time, tf)
                
                if expected_next < current_candle_start:
                    # Есть gap между последней свечой и началом текущей
                    candles_needed = self._estimate_candles_needed(expected_next, current_candle_start, tf)
                    
                    gaps[tf] = {
                        'start': expected_next,
                        'end': current_candle_start,  # ✅ Начало текущей свечи, НЕ current_time
                        'candles_needed': candles_needed,
                        'last_candle': last_candle_time
                    }
        
        return gaps
    
    def _get_last_candle_time(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Получить время последней свечи из БД"""
        session = self.db.get_session()
        try:
            latest_candle = session.query(Candle).filter(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe
            ).order_by(Candle.open_time.desc()).first()
            
            if latest_candle and latest_candle.open_time:
                # Ensure timezone-aware datetime
                last_time = latest_candle.open_time
                if last_time.tzinfo is None:
                    last_time = pytz.UTC.localize(last_time)
                return last_time
            return None
        finally:
            session.close()
    
    def _has_any_data(self, symbol: str) -> bool:
        """Проверить есть ли хоть какие-то данные для символа"""
        for tf in self.timeframes:
            if self._get_last_candle_time(symbol, tf):
                return True
        return False
    
    def _get_next_candle_time(self, last_time: datetime, timeframe: str) -> datetime:
        """Получить время следующей свечи"""
        intervals = {
            '15m': timedelta(minutes=15),
            '1h': timedelta(hours=1),
            '4h': timedelta(hours=4),
            '1d': timedelta(days=1)
        }
        return last_time + intervals[timeframe]
    
    def _estimate_candles_needed(self, start: datetime, end: datetime, timeframe: str) -> int:
        """Оценить количество свечей в gap"""
        delta = end - start
        
        intervals = {
            '15m': 15,
            '1h': 60,
            '4h': 240,
            '1d': 1440
        }
        
        minutes = delta.total_seconds() / 60
        candles = int(minutes / intervals[timeframe]) + 1
        return candles
    
    async def burst_catchup(self, existing_gaps: Dict[str, Dict], 
                           max_parallel: Optional[int] = None) -> Tuple[int, int]:
        """
        Быстрая параллельная догрузка gaps
        
        Args:
            existing_gaps: Dict[symbol, Dict[tf, gap_info]]
            max_parallel: Максимальное количество параллельных загрузок (auto если None)
            
        Returns:
            (success_count, failed_count)
        """
        if not existing_gaps:
            return 0, 0
        
        total_requests = sum(len(gaps) for gaps in existing_gaps.values())
        
        # Умный расчёт parallelism на основе объёма
        if max_parallel is None:
            max_parallel = self._calculate_optimal_parallelism(total_requests)
        
        logger.info(
            f"⚡ Starting BURST CATCHUP mode:\n"
            f"  📦 Symbols to update: {len(existing_gaps)}\n"
            f"  📊 Total requests: {total_requests}\n"
            f"  🔄 Parallel workers: {max_parallel}\n"
            f"  ⏱️  Estimated time: {self._estimate_burst_time(total_requests, max_parallel)} seconds"
        )
        
        semaphore = asyncio.Semaphore(max_parallel)
        success_count = 0
        failed_count = 0
        
        async def load_symbol_gaps(symbol: str, gaps: Dict):
            nonlocal success_count, failed_count
            
            async with semaphore:
                try:
                    for tf, gap_info in gaps.items():
                        # Проверить rate limit перед запросом (90% порог)
                        if hasattr(self.data_loader, 'client') and hasattr(self.data_loader.client, 'rate_limiter'):
                            usage = self.data_loader.client.rate_limiter.get_current_usage()
                            if usage.get('is_near_limit', False):
                                logger.info(
                                    f"⏸️ Pausing burst catchup: rate limit at "
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
                            # _save_candles уже async, не нужен to_thread
                            logger.debug(f"Loaded {len(df)} candles for {symbol} {tf}")
                            
                            logger.debug(
                                f"  ✅ {symbol} {tf}: +{len(df)} candles "
                                f"({gap_info['start'].strftime('%H:%M')} → {gap_info['end'].strftime('%H:%M')})"
                            )
                        
                        # Микро-пауза для rate limit
                        await asyncio.sleep(0.05)
                    
                    success_count += 1
                    
                except Exception as e:
                    logger.error(f"  ❌ {symbol} catchup failed: {e}")
                    failed_count += 1
        
        # Параллельная загрузка всех gaps С БАТЧИРОВАНИЕМ для безопасности rate limiter
        start_time = datetime.now()
        
        # Разбить символы на батчи по 20 символов (безопаснее для rate limiter)
        BATCH_SIZE = 20
        BATCH_PAUSE = 0.5  # Пауза 0.5 сек между батчами для избежания rate limit spikes
        
        symbol_items = list(existing_gaps.items())
        total_batches = (len(symbol_items) + BATCH_SIZE - 1) // BATCH_SIZE
        
        logger.info(
            f"📦 Splitting {len(symbol_items)} symbols into {total_batches} batches "
            f"(batch size: {BATCH_SIZE}, pause: {BATCH_PAUSE}s)"
        )
        
        for batch_num in range(total_batches):
            batch_start = batch_num * BATCH_SIZE
            batch_end = min(batch_start + BATCH_SIZE, len(symbol_items))
            batch = symbol_items[batch_start:batch_end]
            
            logger.info(
                f"📊 Processing batch {batch_num+1}/{total_batches} "
                f"({len(batch)} symbols: {batch[0][0]} ... {batch[-1][0]})"
            )
            
            tasks = [load_symbol_gaps(symbol, gaps) for symbol, gaps in batch]
            await asyncio.gather(*tasks)
            
            # КРИТИЧНО: Проверить rate usage после каждого батча
            if hasattr(self.data_loader, 'client') and hasattr(self.data_loader.client, 'rate_limiter'):
                usage = self.data_loader.client.rate_limiter.get_current_usage()
                current_percent = usage.get('percent_of_safe', 0)
                
                # Если rate > 50% от safe threshold - увеличить паузу
                if current_percent > 50:
                    extra_pause = 2.0  # Дополнительная пауза 2 секунды
                    logger.info(
                        f"⏸️ Rate usage {current_percent:.1f}% > 50%, adding {extra_pause}s pause"
                    )
                    await asyncio.sleep(extra_pause)
            
            # Стандартная пауза между батчами (кроме последнего)
            if batch_num < total_batches - 1:
                logger.debug(f"⏸️ Batch pause {BATCH_PAUSE}s before next batch")
                await asyncio.sleep(BATCH_PAUSE)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        logger.info(
            f"⚡ BURST CATCHUP COMPLETE:\n"
            f"  ✅ Success: {success_count} symbols\n"
            f"  ❌ Failed: {failed_count} symbols\n"
            f"  ⏱️  Time: {elapsed:.1f}s (avg {elapsed/len(existing_gaps):.2f}s per symbol)\n"
            f"  🚀 Speed: {total_requests/elapsed:.1f} requests/sec"
        )
        
        return success_count, failed_count
    
    def _calculate_optimal_parallelism(self, total_requests: int) -> int:
        """
        Рассчитать оптимальное количество параллельных загрузок
        
        Args:
            total_requests: Общее количество запросов
            
        Returns:
            Оптимальное количество параллельных workers
        """
        # Rate limit Binance: 1200 weight/min
        # Gap request weight: ~5
        # Безопасный лимит: 800 weight/min (запас)
        
        if total_requests < 30:
            # Мало запросов - агрессивно
            return 12
        elif total_requests < 100:
            # Средне - балансировано
            return 8
        elif total_requests < 300:
            # Много - консервативно
            return 6
        else:
            # Очень много - очень консервативно
            return 4
    
    def _estimate_burst_time(self, total_requests: int, parallel: int) -> int:
        """Оценить время выполнения burst catchup в секундах"""
        # Средний запрос: ~0.3 сек
        avg_request_time = 0.3
        
        # Последовательное время / параллелизм + накладные расходы
        sequential_time = total_requests * avg_request_time
        parallel_time = sequential_time / parallel
        overhead = 2  # Накладные расходы
        
        return int(parallel_time + overhead)
    
    def get_catchup_stats(self, existing_gaps: Dict) -> Dict:
        """
        Получить статистику по gaps для отчёта
        
        Returns:
            Dict со статистикой
        """
        if not existing_gaps:
            return {
                'total_symbols': 0,
                'total_gaps': 0,
                'total_candles': 0,
                'by_timeframe': {}
            }
        
        stats = {
            'total_symbols': len(existing_gaps),
            'total_gaps': 0,
            'total_candles': 0,
            'by_timeframe': {tf: {'gaps': 0, 'candles': 0} for tf in self.timeframes}
        }
        
        for gaps in existing_gaps.values():
            for tf, gap_info in gaps.items():
                stats['total_gaps'] += 1
                stats['total_candles'] += gap_info['candles_needed']
                stats['by_timeframe'][tf]['gaps'] += 1
                stats['by_timeframe'][tf]['candles'] += gap_info['candles_needed']
        
        return stats
