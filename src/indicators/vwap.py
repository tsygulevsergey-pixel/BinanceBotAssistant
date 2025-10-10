import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from typing import Optional


class VWAPCalculator:
    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
        return vwap
    
    @staticmethod
    def calculate_daily_vwap(df: pd.DataFrame, tz: str = 'Europe/Kiev') -> pd.Series:
        df = df.copy()
        
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['tp_volume'] = typical_price * df['volume']
        
        df['date'] = df.index.tz_localize('UTC').tz_convert(tz).date if df.index.tz is None else df.index.tz_convert(tz).date
        
        daily_vwap = df.groupby('date').apply(
            lambda x: (x['tp_volume'].cumsum() / x['volume'].cumsum()).values
        )
        
        vwap_series = pd.Series(index=df.index, dtype=float)
        for date, values in daily_vwap.items():
            mask = df['date'] == date
            vwap_series[mask] = values
        
        return vwap_series
    
    @staticmethod
    def calculate_anchored_vwap(df: pd.DataFrame, anchor_index: int) -> pd.Series:
        if anchor_index >= len(df):
            return pd.Series(index=df.index, dtype=float)
        
        df_subset = df.iloc[anchor_index:].copy()
        typical_price = (df_subset['high'] + df_subset['low'] + df_subset['close']) / 3
        
        avwap = (typical_price * df_subset['volume']).cumsum() / df_subset['volume'].cumsum()
        
        result = pd.Series(index=df.index, dtype=float)
        result.iloc[anchor_index:] = avwap.values
        
        return result
    
    @staticmethod
    def calculate_vwap_bands(df: pd.DataFrame, vwap: pd.Series, std_mult: float = 1.0) -> tuple:
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        
        variance = ((typical_price - vwap) ** 2 * df['volume']).cumsum() / df['volume'].cumsum()
        std = np.sqrt(variance)
        
        upper_band = vwap + (std * std_mult)
        lower_band = vwap - (std * std_mult)
        
        return upper_band, lower_band


# Standalone функции для совместимости
def calculate_daily_vwap(df: pd.DataFrame, tz: str = 'Europe/Kiev') -> tuple:
    """Calculate daily VWAP with bands"""
    vwap = VWAPCalculator.calculate_daily_vwap(df, tz)
    upper, lower = VWAPCalculator.calculate_vwap_bands(df, vwap, std_mult=1.0)
    return vwap, upper, lower

def calculate_anchored_vwap(df: pd.DataFrame, anchor_index: int) -> pd.Series:
    """Calculate anchored VWAP"""
    return VWAPCalculator.calculate_anchored_vwap(df, anchor_index)
