import asyncio
import aiohttp
from typing import List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import pytz
import pandas as pd
import math
from src.utils.logger import logger
from src.utils.config import config
from src.binance.client import BinanceClient
from src.database.db import db
from src.database.models import Candle, Trade
import zipfile
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.telegram.bot import TelegramBot


class DataLoader:
    BINANCE_VISION_URL = "https://data.binance.vision"
    
    def __init__(self, client: BinanceClient, telegram_bot: Optional['TelegramBot'] = None):
        self.client = client
        self.telegram_bot = telegram_bot
        self.cache_dir = Path(config.get('data_sources.cache_directory', 'data/cache'))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    async def download_historical_klines(self, symbol: str, interval: str, 
                                        start_date: datetime, end_date: datetime, max_retries: int = 3):
        total_days = max(1, math.ceil((end_date - start_date).total_seconds() / 86400))
        logger.info(f"Downloading historical klines for {symbol} {interval} from {start_date} to {end_date} ({total_days} days)")
        
        current_date = start_date
        all_klines = []
        day_counter = 0
        
        while current_date < end_date:
            start_ms = int(current_date.timestamp() * 1000)
            end_ms = int((current_date + timedelta(days=1)).timestamp() * 1000)
            
            # Retry logic with exponential backoff
            retry_count = 0
            success = False
            
            while retry_count < max_retries and not success:
                try:
                    klines = await self.client.get_klines(
                        symbol=symbol,
                        interval=interval,
                        start_time=start_ms,
                        end_time=end_ms,
                        limit=1500
                    )
                    
                    all_klines.extend(klines)
                    success = True
                    
                except Exception as e:
                    retry_count += 1
                    error_msg = str(e) if str(e) else type(e).__name__
                    if retry_count < max_retries:
                        wait_time = 2 ** retry_count  # Exponential backoff: 2, 4, 8 seconds
                        logger.warning(f"Error downloading {symbol} {interval} on {current_date.date()}: {error_msg}. Retry {retry_count}/{max_retries} in {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"Failed to download {symbol} {interval} on {current_date.date()} after {max_retries} retries: {error_msg}")
                        # Raise exception to stop loading if data is critical
                        raise Exception(f"Data download failed for {symbol} {interval} after {max_retries} retries: {error_msg}")
            
            if success:
                day_counter += 1
                if day_counter % 10 == 0 or current_date >= end_date - timedelta(days=1):
                    progress = (day_counter / total_days) * 100
                    logger.info(f"  Progress: {progress:.1f}% ({day_counter}/{total_days} days) - {symbol} {interval}")
            
            current_date += timedelta(days=1)
        
        # ВАЖНО: Удалить последнюю незакрытую свечу (Binance API всегда возвращает её)
        # Проверяем что это действительно незакрытая свеча (close_time > now)
        if all_klines:
            last_kline = all_klines[-1]
            last_close_time = datetime.fromtimestamp(last_kline[6] / 1000, tz=pytz.UTC)
            now = datetime.now(pytz.UTC)
            
            if last_close_time > now:
                # Это незакрытая свеча - удаляем
                all_klines = all_klines[:-1]
                logger.debug(f"Removed last unclosed candle from {symbol} {interval} (close_time: {last_close_time})")
        
        saved_count = self._save_klines_to_db(symbol, interval, all_klines)
        logger.info(f"Saved {saved_count} klines for {symbol} {interval}")
        
        return all_klines
    
    def _save_klines_to_db(self, symbol: str, interval: str, klines: List) -> int:
        """Save klines to database using BULK UPSERT (100-500x faster)
        
        Uses SQLite's INSERT OR REPLACE for efficient batch operations.
        Requires unique index on (symbol, timeframe, open_time).
        
        Returns:
            int: Number of candles processed
        """
        if not klines:
            return 0
        
        session = db.get_session()
        
        try:
            # Подготовить данные для bulk insert
            candles_data = []
            for kline in klines:
                candles_data.append({
                    'symbol': symbol,
                    'timeframe': interval,
                    'open_time': datetime.fromtimestamp(kline[0] / 1000, tz=pytz.UTC),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5]),
                    'close_time': datetime.fromtimestamp(kline[6] / 1000, tz=pytz.UTC),
                    'quote_volume': float(kline[7]),
                    'trades': int(kline[8]),
                    'taker_buy_base': float(kline[9]),
                    'taker_buy_quote': float(kline[10])
                })
            
            # BULK UPSERT используя SQLite INSERT OR REPLACE
            # Это в 100-500 раз быстрее чем циклы SELECT + INSERT/UPDATE
            from sqlalchemy import text
            
            # SQLite: INSERT OR REPLACE автоматически обновит существующие записи
            insert_sql = text("""
                INSERT OR REPLACE INTO candles (
                    symbol, timeframe, open_time, open, high, low, close,
                    volume, close_time, quote_volume, trades, 
                    taker_buy_base, taker_buy_quote
                ) VALUES (
                    :symbol, :timeframe, :open_time, :open, :high, :low, :close,
                    :volume, :close_time, :quote_volume, :trades,
                    :taker_buy_base, :taker_buy_quote
                )
            """)
            
            # Выполнить bulk insert (все записи одним запросом)
            session.execute(insert_sql, candles_data)
            session.commit()
            
            return len(klines)
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error bulk saving klines to DB: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0
        finally:
            session.close()
    
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
        # Например для 15m и времени 18:43:
        # minutes_since_midnight = 18*60 + 43 = 1123
        # candles_since_midnight = 1123 // 15 = 74
        # current_candle_start_minutes = 74 * 15 = 1110 минут = 18:30
        
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
        is_fresh = last_candle_time >= current_candle_start
        
        return is_fresh
    
    async def load_warm_up_data(self, symbol: str, silent: bool = False):
        """Smart load - загружает ТОЛЬКО недостающие данные с валидацией целостности
        
        ОПТИМИЗАЦИЯ: Проверяет свежесть данных в БД ПЕРЕД запросом к Binance.
        - Если данные свежие → пропускает запрос (экономия времени)
        - Если устарели → загружает только недостающие свечи
        
        Args:
            symbol: Symbol to load data for
            silent: If True, suppress progress logging (for batch loading)
        
        Returns:
            bool: True if all timeframes loaded successfully, False otherwise
        """
        warm_up_days = config.get('database.warm_up_days', 90)
        full_end_date = datetime.now(pytz.UTC)
        full_start_date = full_end_date - timedelta(days=warm_up_days)
        
        timeframes = ['15m', '1h', '4h', '1d']
        total_tf = len(timeframes)
        
        try:
            for idx, interval in enumerate(timeframes, 1):
                session = db.get_session()
                try:
                    # Находим последнюю свечу в БД
                    latest_candle = session.query(Candle).filter(
                        Candle.symbol == symbol,
                        Candle.timeframe == interval
                    ).order_by(Candle.open_time.desc()).first()
                    
                    if latest_candle and latest_candle.open_time:
                        # Есть данные - проверяем свежесть
                        # SQLAlchemy возвращает datetime, но LSP не видит тип - явно приводим
                        last_time: datetime = latest_candle.open_time  # type: ignore
                        
                        # Убеждаемся что last_time имеет timezone UTC
                        if last_time.tzinfo is None:
                            last_time = pytz.UTC.localize(last_time)
                        
                        # ✅ ОПТИМИЗАЦИЯ: Проверка свежести перед запросом к API
                        if self._is_data_fresh(last_time, interval, full_end_date):
                            if not silent:
                                logger.info(f"  [{idx}/{total_tf}] ✓ {symbol} {interval} up-to-date (fresh)")
                            continue  # SKIP запрос к Binance!
                        
                        # Данные устарели - загружаем gap
                        gap_start = last_time + timedelta(minutes=1)
                        gap_end = full_end_date
                        
                        if not silent:
                            logger.info(f"  [{idx}/{total_tf}] 🔄 {symbol} {interval} - updating from {gap_start.strftime('%Y-%m-%d %H:%M')}")
                        await self.download_historical_klines(symbol, interval, gap_start, gap_end)
                    else:
                        # Нет данных - загружаем все 90 дней
                        if not silent:
                            logger.info(f"  [{idx}/{total_tf}] 📥 {symbol} {interval} - loading {warm_up_days} days")
                        await self.download_historical_klines(symbol, interval, full_start_date, full_end_date)
                finally:
                    session.close()
                
                # Validate continuity and fix internal gaps
                gaps = self.validate_candles_continuity(symbol, interval)
                if gaps:
                    logger.warning(f"  [{idx}/{total_tf}] ⚠️ {symbol} {interval}: {len(gaps)} internal gaps detected")
                    fixed = await self.auto_fix_gaps(gaps)
                    if fixed == len(gaps):
                        logger.info(f"  [{idx}/{total_tf}] ✅ {symbol} {interval}: all {fixed} gaps fixed")
                    else:
                        error_msg = f"  [{idx}/{total_tf}] ❌ {symbol} {interval}: only {fixed}/{len(gaps)} gaps fixed"
                        logger.error(error_msg)
                        
                        # Send telegram alert for unfixed gaps (только для старых монет)
                        symbol_age = self._get_symbol_age_days(symbol)
                        if symbol_age >= 90 and self.telegram_bot:
                            asyncio.create_task(
                                self.telegram_bot.send_data_integrity_alert(
                                    symbol, "gaps", 
                                    f"{interval}: {len(gaps)-fixed} gaps remain unfixed"
                                )
                            )
                        elif symbol_age < 90:
                            logger.info(f"🆕 {symbol} is new ({symbol_age} days old), skipping gaps alert")
            
            # Final completeness check with 99% threshold
            if not self.is_symbol_data_complete(symbol):
                error_msg = f"❌ {symbol}: data incomplete after loading (99% threshold not met)"
                logger.error(error_msg)
                
                # Try auto-refill if enabled
                auto_refill_enabled = config.get('data_integrity.auto_refill_on_incomplete', True)
                
                if auto_refill_enabled:
                    logger.info(f"🔧 Attempting auto-refill for {symbol}...")
                    refill_success = await self.auto_refill_incomplete_data(symbol)
                    
                    if refill_success:
                        logger.info(f"✅ {symbol}: auto-refill successful, data complete")
                        return True
                    else:
                        logger.warning(f"⚠️ {symbol}: auto-refill failed")
                        # Send alert only if auto-refill failed (только для старых монет)
                        symbol_age = self._get_symbol_age_days(symbol)
                        if symbol_age >= 90 and self.telegram_bot:
                            asyncio.create_task(
                                self.telegram_bot.send_data_integrity_alert(
                                    symbol, "incomplete", 
                                    "Data completeness below 99% (auto-refill failed)"
                                )
                            )
                            logger.warning(f"📤 {symbol}: sending alert (age: {symbol_age} days)")
                        elif symbol_age < 90:
                            logger.info(f"🆕 {symbol} is new ({symbol_age} days old), skipping incomplete alert")
                        return False
                else:
                    # Auto-refill disabled - проверяем возраст перед алертом
                    symbol_age = self._get_symbol_age_days(symbol)
                    if symbol_age >= 90 and self.telegram_bot:
                        asyncio.create_task(
                            self.telegram_bot.send_data_integrity_alert(symbol, "incomplete", 
                                                                        "Data completeness below 99%")
                        )
                        logger.warning(f"📤 {symbol}: sending alert (age: {symbol_age} days)")
                    elif symbol_age < 90:
                        logger.info(f"🆕 {symbol} is new ({symbol_age} days old), skipping incomplete alert")
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Failed to load warm-up data for {symbol}: {e}")
            return False
    
    def _get_symbol_age_days(self, symbol: str) -> int:
        """Определить возраст монеты по первой доступной свече
        
        Returns:
            int: Количество дней с момента листинга монеты, 0 если нет данных
        """
        session = db.get_session()
        try:
            # Проверяем самый длинный таймфрейм для точности
            first_candle = session.query(Candle).filter(
                Candle.symbol == symbol,
                Candle.timeframe == '1d'
            ).order_by(Candle.open_time.asc()).first()
            
            if not first_candle:
                # Если 1d нет, пробуем 4h
                first_candle = session.query(Candle).filter(
                    Candle.symbol == symbol,
                    Candle.timeframe == '4h'
                ).order_by(Candle.open_time.asc()).first()
            
            if first_candle:
                # Ensure timezone-aware comparison
                now = datetime.now(pytz.UTC)
                candle_time = first_candle.open_time if first_candle.open_time.tzinfo else pytz.UTC.localize(first_candle.open_time)
                age_delta = now - candle_time
                return age_delta.days
            
            return 0
        finally:
            session.close()
    
    def _is_missing_only_current_day(self, symbol: str, existing_count: int, expected_count: int) -> bool:
        """Check if missing candle is only the current unclosed daily candle
        
        For 1d timeframe, if we expect 90 candles but only have 89, check if the missing
        one is today's candle (which hasn't closed yet at 00:00 UTC).
        
        Args:
            symbol: Trading symbol
            existing_count: Actual candles in DB
            expected_count: Expected candles for 90 days
            
        Returns:
            bool: True if only missing today's unclosed candle (normal situation)
        """
        if expected_count - existing_count != 1:
            return False
        
        session = db.get_session()
        try:
            last_candle = session.query(Candle).filter(
                Candle.symbol == symbol,
                Candle.timeframe == '1d'
            ).order_by(Candle.open_time.desc()).first()
            
            if not last_candle:
                return False
            
            now = datetime.now(pytz.UTC)
            last_candle_time = last_candle.open_time if last_candle.open_time.tzinfo else pytz.UTC.localize(last_candle.open_time)
            
            today_candle_start = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=pytz.UTC)
            yesterday_candle_start = today_candle_start - timedelta(days=1)
            
            if last_candle_time.date() == yesterday_candle_start.date():
                logger.debug(f"{symbol} 1d: missing only today's candle (normal, day not closed yet)")
                return True
            
            return False
        finally:
            session.close()
    
    def is_symbol_data_complete(self, symbol: str) -> bool:
        """Check if symbol has complete data for all required timeframes
        
        Returns:
            bool: True if all timeframes are loaded with >=99% expected data (raised from 95%)
        """
        warm_up_days = config.get('database.warm_up_days', 90)
        end_date = datetime.now(pytz.UTC)
        start_date = end_date - timedelta(days=warm_up_days)
        
        timeframes = ['15m', '1h', '4h', '1d']
        
        for interval in timeframes:
            existing_count = self._count_existing_candles(symbol, interval, start_date, end_date)
            expected_count = self._expected_candle_count(interval, warm_up_days)
            
            # Raised threshold from 95% to 99% for better data quality
            if existing_count < expected_count * 0.99:
                coverage = (existing_count / expected_count * 100) if expected_count > 0 else 0
                
                if interval == '1d' and self._is_missing_only_current_day(symbol, existing_count, expected_count):
                    logger.debug(f"{symbol} {interval}: {coverage:.1f}% coverage ({existing_count}/{expected_count} candles) - OK (current day not closed)")
                    continue
                
                logger.warning(f"{symbol} {interval}: incomplete data ({coverage:.1f}% coverage, {existing_count}/{expected_count} candles)")
                return False
        
        return True
    
    async def auto_refill_incomplete_data(self, symbol: str) -> bool:
        """Автоматически докачать недостающие данные для символа
        
        Находит все gaps за 90 дней и докачивает их параллельно
        
        Returns:
            bool: True если данные успешно докачаны до 99%, False иначе
        """
        warm_up_days = config.get('database.warm_up_days', 90)
        end_date = datetime.now(pytz.UTC)
        start_date = end_date - timedelta(days=warm_up_days)
        
        timeframes = ['15m', '1h', '4h', '1d']
        incomplete_timeframes = []
        
        # Найти неполные таймфреймы
        for interval in timeframes:
            existing_count = self._count_existing_candles(symbol, interval, start_date, end_date)
            expected_count = self._expected_candle_count(interval, warm_up_days)
            
            if existing_count < expected_count * 0.99:
                coverage = (existing_count / expected_count * 100) if expected_count > 0 else 0
                incomplete_timeframes.append({
                    'interval': interval,
                    'coverage': coverage,
                    'existing': existing_count,
                    'expected': expected_count
                })
        
        if not incomplete_timeframes:
            return True
        
        logger.info(
            f"🔧 AUTO-REFILL starting for {symbol}:\n"
            f"  📊 Incomplete timeframes: {len(incomplete_timeframes)}"
        )
        
        # Докачать gaps для каждого неполного таймфрейма
        total_fixed = 0
        for tf_info in incomplete_timeframes:
            interval = tf_info['interval']
            logger.info(
                f"  📈 {interval}: {tf_info['coverage']:.1f}% coverage "
                f"({tf_info['existing']}/{tf_info['expected']} candles)"
            )
            
            # Найти gaps
            gaps = self.validate_candles_continuity(symbol, interval)
            
            if gaps:
                logger.info(f"  🔍 Found {len(gaps)} gaps in {interval}")
                # Докачать gaps
                fixed = await self.auto_fix_gaps(gaps)
                total_fixed += fixed
                
                if fixed == len(gaps):
                    logger.info(f"  ✅ {interval}: all {fixed} gaps fixed")
                else:
                    logger.warning(f"  ⚠️ {interval}: only {fixed}/{len(gaps)} gaps fixed")
            else:
                logger.info(f"  ✅ {interval}: no internal gaps detected")
        
        # Проверить результат
        is_complete = self.is_symbol_data_complete(symbol)
        
        if is_complete:
            logger.info(f"✅ AUTO-REFILL complete for {symbol}: data now at 99%+")
        else:
            logger.warning(f"⚠️ AUTO-REFILL finished for {symbol}: still below 99% threshold")
        
        return is_complete
    
    def validate_candles_continuity(self, symbol: str, interval: str) -> list:
        """Validate candle continuity and detect internal gaps
        
        Args:
            symbol: Symbol to validate
            interval: Timeframe (15m, 1h, 4h, 1d)
            
        Returns:
            List of gap dictionaries with details about missing candles
        """
        session = db.get_session()
        gaps = []
        
        try:
            # Get all candles ordered by time
            candles = session.query(Candle).filter(
                Candle.symbol == symbol,
                Candle.timeframe == interval
            ).order_by(Candle.open_time).all()
            
            if len(candles) < 2:
                return gaps
            
            # Define expected interval in minutes
            interval_minutes = {
                '1m': 1,
                '5m': 5,
                '15m': 15,
                '1h': 60,
                '4h': 240,
                '1d': 1440
            }.get(interval, 15)
            
            # Check continuity between consecutive candles
            for i in range(len(candles) - 1):
                current_time = candles[i].open_time
                next_time = candles[i + 1].open_time
                
                # Ensure timezone aware
                if current_time.tzinfo is None:
                    current_time = pytz.UTC.localize(current_time)
                if next_time.tzinfo is None:
                    next_time = pytz.UTC.localize(next_time)
                
                expected_next = current_time + timedelta(minutes=interval_minutes)
                
                # Detect gap
                if next_time != expected_next:
                    gap_minutes = (next_time - expected_next).total_seconds() / 60
                    missing_candles = int(gap_minutes / interval_minutes)
                    
                    gaps.append({
                        'symbol': symbol,
                        'interval': interval,
                        'gap_start': expected_next,
                        'gap_end': next_time,
                        'gap_minutes': gap_minutes,
                        'missing_candles': missing_candles,
                        'after_candle': current_time
                    })
            
            return gaps
            
        finally:
            session.close()
    
    async def auto_fix_gaps(self, gaps: list) -> int:
        """Automatically fix detected gaps by downloading missing candles
        
        Args:
            gaps: List of gap dictionaries from validate_candles_continuity
            
        Returns:
            int: Number of gaps successfully fixed
        """
        if not gaps:
            return 0
        
        fixed_count = 0
        
        for gap in gaps:
            try:
                logger.info(f"Fixing gap: {gap['symbol']} {gap['interval']} at {gap['gap_start']} ({gap['missing_candles']} candles)")
                
                await self.download_historical_klines(
                    symbol=gap['symbol'],
                    interval=gap['interval'],
                    start_date=gap['gap_start'],
                    end_date=gap['gap_end'],
                    max_retries=3
                )
                
                fixed_count += 1
                
            except Exception as e:
                logger.error(f"Failed to fix gap for {gap['symbol']} {gap['interval']}: {e}")
        
        return fixed_count
    
    def _count_existing_candles(self, symbol: str, interval: str, 
                                start_date: datetime, end_date: datetime) -> int:
        session = db.get_session()
        try:
            count = session.query(Candle).filter(
                Candle.symbol == symbol,
                Candle.timeframe == interval,
                Candle.open_time >= start_date,
                Candle.open_time <= end_date
            ).count()
            return count
        finally:
            session.close()
    
    def _expected_candle_count(self, interval: str, days: int) -> int:
        interval_map = {
            '1m': 1440,
            '5m': 288,
            '15m': 96,
            '1h': 24,
            '4h': 6,
            '1d': 1
        }
        return interval_map.get(interval, 1) * days
    
    def _get_interval_minutes(self, interval: str) -> int:
        """Get interval duration in minutes
        
        Args:
            interval: Timeframe string (e.g., '15m', '1h', '4h', '1d')
        
        Returns:
            int: Number of minutes in the interval
        """
        interval_map = {
            '1m': 1,
            '5m': 5,
            '15m': 15,
            '1h': 60,
            '4h': 240,
            '1d': 1440
        }
        return interval_map.get(interval, 15)
    
    async def update_missing_candles(self, symbol: str, interval: str):
        """Update missing candles from last DB candle to current time
        
        FIXED (Problem #15): Changed from fixed 300s threshold to interval-aware check.
        Now updates whenever gap >= 1 full candle duration (e.g., 15m, 1h, 4h).
        
        Args:
            symbol: Trading pair symbol
            interval: Timeframe (15m, 1h, 4h, 1d)
        """
        session = db.get_session()
        try:
            latest_candle = session.query(Candle).filter(
                Candle.symbol == symbol,
                Candle.timeframe == interval
            ).order_by(Candle.open_time.desc()).first()
            
            if latest_candle and latest_candle.open_time:
                # SQLAlchemy возвращает datetime, но LSP не видит тип - явно приводим
                last_time: datetime = latest_candle.open_time  # type: ignore
                
                # Убеждаемся что last_time имеет timezone UTC
                if last_time.tzinfo is None:
                    last_time = pytz.UTC.localize(last_time)
                
                end_date = datetime.now(pytz.UTC)
                
                # FIXED: Interval-aware threshold instead of fixed 300s
                # Calculate gap from last_time to detect missing candles correctly
                interval_seconds = self._get_interval_minutes(interval) * 60
                gap_seconds = (end_date - last_time).total_seconds()
                
                # Update if gap >= 1 full candle duration
                if gap_seconds >= interval_seconds:
                    # Use last_time + 1 minute as start to avoid duplicate candles
                    start_date = last_time + timedelta(minutes=1)
                    logger.info(f"Updating missing candles for {symbol} {interval} from {start_date}")
                    await self.download_historical_klines(symbol, interval, start_date, end_date)
        finally:
            session.close()
    
    async def refresh_recent_candles(self, symbol: str, days: int = 10):
        """
        Обновить/переобновить все свечи за последние N дней
        Используется для исправления незакрытых свечей в БД
        
        Args:
            symbol: Символ для обновления
            days: Количество дней для обновления (по умолчанию 10)
        """
        timeframes = ['15m', '1h', '4h', '1d']
        end_date = datetime.now(pytz.UTC)
        start_date = end_date - timedelta(days=days)
        
        logger.info(f"🔄 Refreshing {symbol} data for last {days} days ({start_date.date()} to {end_date.date()})")
        
        for interval in timeframes:
            try:
                # Скачать данные заново
                await self.download_historical_klines(symbol, interval, start_date, end_date)
                logger.info(f"✅ {symbol} {interval} refreshed successfully")
            except Exception as e:
                logger.error(f"❌ Failed to refresh {symbol} {interval}: {e}")
    
    def get_candles(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        session = db.get_session()
        try:
            candles = session.query(Candle).filter(
                Candle.symbol == symbol,
                Candle.timeframe == interval
            ).order_by(Candle.open_time.desc()).limit(limit).all()
            
            if not candles:
                return pd.DataFrame()
            
            data = [{
                'open_time': c.open_time,
                'open': c.open,
                'high': c.high,
                'low': c.low,
                'close': c.close,
                'volume': c.volume,
                'taker_buy_base': c.taker_buy_base,
                'taker_buy_quote': c.taker_buy_quote
            } for c in reversed(candles)]
            
            df = pd.DataFrame(data)
            df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
            # ВАЖНО: НЕ делать set_index - Action Price требует open_time как колонку для timestamp-based selection
            # df.set_index('open_time', inplace=True)
            
            return df
        finally:
            session.close()
