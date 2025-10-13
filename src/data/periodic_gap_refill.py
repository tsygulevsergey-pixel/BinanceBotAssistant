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
    
    async def refill_gaps(self, gaps: Dict[str, Dict[str, dict]]) -> Dict[str, int]:
        """
        Параллельная докачка gaps
        
        Returns:
            {'success': count, 'failed': count}
        """
        if not gaps:
            return {'success': 0, 'failed': 0}
        
        total_gaps = sum(len(tfs) for tfs in gaps.values())
        
        # Вычислить оптимальный параллелизм
        optimal_parallel = min(self.max_parallel, max(4, total_gaps // 5))
        
        logger.info(
            f"⚡ PERIODIC GAP REFILL starting:\n"
            f"  📊 Symbols: {len(gaps)}\n"
            f"  📈 Total gaps: {total_gaps}\n"
            f"  🔄 Parallel workers: {optimal_parallel}"
        )
        
        semaphore = asyncio.Semaphore(optimal_parallel)
        tasks = []
        
        for symbol, timeframe_gaps in gaps.items():
            task = self._refill_symbol_gaps(symbol, timeframe_gaps, semaphore)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success = sum(1 for r in results if r is True)
        failed = len(results) - success
        
        logger.info(
            f"⚡ PERIODIC GAP REFILL complete:\n"
            f"  ✅ Success: {success} symbols\n"
            f"  ❌ Failed: {failed} symbols"
        )
        
        return {'success': success, 'failed': failed}
    
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
        
        # Определить какие таймфреймы проверять
        timeframes = await self.determine_timeframes_to_check()
        
        now = datetime.now(pytz.UTC)
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
