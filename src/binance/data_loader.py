import asyncio
import aiohttp
from typing import List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import pytz
import pandas as pd
from src.utils.logger import logger
from src.utils.config import config
from src.binance.client import BinanceClient
from src.database.db import db
from src.database.models import Candle, Trade
import zipfile
import io


class DataLoader:
    BINANCE_VISION_URL = "https://data.binance.vision"
    
    def __init__(self, client: BinanceClient):
        self.client = client
        self.cache_dir = Path(config.get('data_sources.cache_directory', 'data/cache'))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    async def download_historical_klines(self, symbol: str, interval: str, 
                                        start_date: datetime, end_date: datetime):
        total_days = max(1, int((end_date - start_date).total_seconds() / 86400))
        logger.info(f"Downloading historical klines for {symbol} {interval} from {start_date} to {end_date} ({total_days} days)")
        
        current_date = start_date
        all_klines = []
        day_counter = 0
        
        while current_date < end_date:
            start_ms = int(current_date.timestamp() * 1000)
            end_ms = int((current_date + timedelta(days=1)).timestamp() * 1000)
            
            try:
                klines = await self.client.get_klines(
                    symbol=symbol,
                    interval=interval,
                    start_time=start_ms,
                    end_time=end_ms,
                    limit=1500
                )
                
                all_klines.extend(klines)
                day_counter += 1
                
                if day_counter % 10 == 0 or current_date >= end_date - timedelta(days=1):
                    progress = (day_counter / total_days) * 100
                    logger.info(f"  Progress: {progress:.1f}% ({day_counter}/{total_days} days) - {symbol} {interval}")
            
            except Exception as e:
                logger.error(f"Error downloading klines for {symbol} {interval} on {current_date.date()}: {e}")
            
            current_date += timedelta(days=1)
        
        self._save_klines_to_db(symbol, interval, all_klines)
        logger.info(f"Saved {len(all_klines)} klines for {symbol} {interval}")
        
        return all_klines
    
    def _save_klines_to_db(self, symbol: str, interval: str, klines: List):
        session = db.get_session()
        try:
            for kline in klines:
                open_time = datetime.fromtimestamp(kline[0] / 1000, tz=pytz.UTC)
                close_time = datetime.fromtimestamp(kline[6] / 1000, tz=pytz.UTC)
                
                existing = session.query(Candle).filter(
                    Candle.symbol == symbol,
                    Candle.timeframe == interval,
                    Candle.open_time == open_time
                ).first()
                
                if not existing:
                    candle = Candle(
                        symbol=symbol,
                        timeframe=interval,
                        open_time=open_time,
                        open=float(kline[1]),
                        high=float(kline[2]),
                        low=float(kline[3]),
                        close=float(kline[4]),
                        volume=float(kline[5]),
                        close_time=close_time,
                        quote_volume=float(kline[7]),
                        trades=int(kline[8]),
                        taker_buy_base=float(kline[9]),
                        taker_buy_quote=float(kline[10])
                    )
                    session.add(candle)
            
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving klines to DB: {e}")
        finally:
            session.close()
    
    async def load_warm_up_data(self, symbol: str, silent: bool = False):
        """Smart load - загружает ТОЛЬКО недостающие данные
        
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
                        # Есть данные - проверяем gap
                        # SQLAlchemy возвращает datetime, но LSP не видит тип - явно приводим
                        last_time: datetime = latest_candle.open_time  # type: ignore
                        
                        # Убеждаемся что last_time имеет timezone UTC
                        if last_time.tzinfo is None:
                            last_time = pytz.UTC.localize(last_time)
                        
                        gap_start = last_time + timedelta(minutes=1)
                        gap_end = full_end_date
                        gap_minutes = (gap_end - gap_start).total_seconds() / 60
                        
                        if gap_minutes > 5:  # Gap больше 5 минут
                            if not silent:
                                logger.info(f"  [{idx}/{total_tf}] 🔄 {symbol} {interval} - gap detected, updating from {gap_start.strftime('%Y-%m-%d %H:%M')}")
                            await self.download_historical_klines(symbol, interval, gap_start, gap_end)
                        else:
                            if not silent:
                                logger.info(f"  [{idx}/{total_tf}] ✓ {symbol} {interval} up-to-date")
                    else:
                        # Нет данных - загружаем все 90 дней
                        if not silent:
                            logger.info(f"  [{idx}/{total_tf}] 📥 {symbol} {interval} - loading {warm_up_days} days")
                        await self.download_historical_klines(symbol, interval, full_start_date, full_end_date)
                finally:
                    session.close()
            
            return True
        except Exception as e:
            logger.error(f"Failed to load warm-up data for {symbol}: {e}")
            return False
    
    def is_symbol_data_complete(self, symbol: str) -> bool:
        """Check if symbol has complete data for all required timeframes
        
        Returns:
            bool: True if all timeframes are loaded with >=95% expected data
        """
        warm_up_days = config.get('database.warm_up_days', 90)
        end_date = datetime.now(pytz.UTC)
        start_date = end_date - timedelta(days=warm_up_days)
        
        timeframes = ['15m', '1h', '4h', '1d']
        
        for interval in timeframes:
            existing_count = self._count_existing_candles(symbol, interval, start_date, end_date)
            expected_count = self._expected_candle_count(interval, warm_up_days)
            
            if existing_count < expected_count * 0.95:
                return False
        
        return True
    
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
    
    async def update_missing_candles(self, symbol: str, interval: str):
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
                
                start_date = last_time + timedelta(minutes=1)
                end_date = datetime.now(pytz.UTC)
                
                if (end_date - start_date).total_seconds() > 300:
                    logger.info(f"Updating missing candles for {symbol} {interval} from {start_date}")
                    await self.download_historical_klines(symbol, interval, start_date, end_date)
        finally:
            session.close()
    
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
            df['open_time'] = pd.to_datetime(df['open_time'])
            df.set_index('open_time', inplace=True)
            
            return df
        finally:
            session.close()
