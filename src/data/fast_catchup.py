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
    
    def _calculate_symbol_gaps(self, symbol: str, current_time: datetime) -> Dict[str, Dict]:
        """
        Рассчитать gaps для одного символа
        
        Returns:
            Dict[timeframe, {'start': datetime, 'end': datetime, 'candles_needed': int}]
        """
        gaps = {}
        
        for tf in self.timeframes:
            last_candle_time = self._get_last_candle_time(symbol, tf)
            
            if last_candle_time:
                # Есть данные - проверяем gap
                expected_next = self._get_next_candle_time(last_candle_time, tf)
                
                if expected_next < current_time:
                    # Есть gap
                    candles_needed = self._estimate_candles_needed(expected_next, current_time, tf)
                    
                    gaps[tf] = {
                        'start': expected_next,
                        'end': current_time,
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
        
        # Параллельная загрузка всех gaps
        start_time = datetime.now()
        tasks = [load_symbol_gaps(symbol, gaps) for symbol, gaps in existing_gaps.items()]
        await asyncio.gather(*tasks)
        
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
