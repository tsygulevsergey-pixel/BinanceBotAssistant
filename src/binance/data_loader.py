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
    
    async def load_warm_up_data(self, symbol: str):
        warm_up_days = config.get('database.warm_up_days', 90)
        end_date = datetime.now(pytz.UTC)
        start_date = end_date - timedelta(days=warm_up_days)
        
        timeframes = ['1m', '5m', '15m', '1h', '4h', '1d']
        total_tf = len(timeframes)
        
        for idx, interval in enumerate(timeframes, 1):
            existing_count = self._count_existing_candles(symbol, interval, start_date, end_date)
            expected_count = self._expected_candle_count(interval, warm_up_days)
            
            if existing_count < expected_count * 0.95:
                logger.info(f"  [{idx}/{total_tf}] Loading {symbol} {interval} (have {existing_count}/{expected_count})")
                await self.download_historical_klines(symbol, interval, start_date, end_date)
            else:
                logger.info(f"  [{idx}/{total_tf}] ✓ {symbol} {interval} already complete ({existing_count} candles)")
    
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
            
            if latest_candle:
                start_date = latest_candle.open_time + timedelta(minutes=1)
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
