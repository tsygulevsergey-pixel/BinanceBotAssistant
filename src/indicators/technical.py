import pandas as pd
import numpy as np
from typing import Tuple, Optional
import pandas_ta as ta


class TechnicalIndicators:
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        return ta.atr(df['high'], df['low'], df['close'], length=period)
    
    @staticmethod
    def calculate_atr_percent(df: pd.DataFrame, period: int = 14) -> pd.Series:
        atr = TechnicalIndicators.calculate_atr(df, period)
        return (atr / df['close']) * 100
    
    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        adx_data = ta.adx(df['high'], df['low'], df['close'], length=period)
        return adx_data
    
    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
        return ta.ema(df['close'], length=period)
    
    @staticmethod
    def calculate_bb(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
        bb = ta.bbands(df['close'], length=period, std=std)
        return bb
    
    @staticmethod
    def calculate_bb_width(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.Series:
        bb = TechnicalIndicators.calculate_bb(df, period, std)
        if bb is None or bb.empty:
            return pd.Series(index=df.index, dtype=float)
        
        upper_col = f'BBU_{period}_{std}'
        lower_col = f'BBL_{period}_{std}'
        middle_col = f'BBM_{period}_{std}'
        
        if upper_col in bb.columns and lower_col in bb.columns and middle_col in bb.columns:
            return (bb[upper_col] - bb[lower_col]) / bb[middle_col]
        return pd.Series(index=df.index, dtype=float)
    
    @staticmethod
    def calculate_donchian(df: pd.DataFrame, period: int = 20) -> Tuple[pd.Series, pd.Series]:
        high_channel = df['high'].rolling(window=period).max()
        low_channel = df['low'].rolling(window=period).min()
        return high_channel, low_channel
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        return ta.rsi(df['close'], length=period)
    
    @staticmethod
    def calculate_stochastic(df: pd.DataFrame, k_period: int = 14, 
                            d_period: int = 3) -> pd.DataFrame:
        stoch = ta.stoch(df['high'], df['low'], df['close'], 
                        k=k_period, d=d_period)
        return stoch
    
    @staticmethod
    def calculate_ema_slope(df: pd.DataFrame, period: int = 20, lookback: int = 5) -> pd.Series:
        ema = TechnicalIndicators.calculate_ema(df, period)
        slope = ema.diff(lookback) / lookback
        return slope
    
    @staticmethod
    def detect_swing_points(df: pd.DataFrame, lookback: int = 5) -> Tuple[pd.Series, pd.Series]:
        highs = pd.Series(False, index=df.index)
        lows = pd.Series(False, index=df.index)
        
        for i in range(lookback, len(df) - lookback):
            if df['high'].iloc[i] == df['high'].iloc[i-lookback:i+lookback+1].max():
                highs.iloc[i] = True
            
            if df['low'].iloc[i] == df['low'].iloc[i-lookback:i+lookback+1].min():
                lows.iloc[i] = True
        
        return highs, lows
    
    @staticmethod
    def calculate_percentile(series: pd.Series, value: float, period: int = 90) -> float:
        if len(series) < period:
            period = len(series)
        
        recent_values = series.tail(period)
        percentile = (recent_values < value).sum() / len(recent_values) * 100
        return percentile


# Standalone функции для совместимости с импортами
def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate ATR"""
    return ta.atr(high, low, close, length=period)

def calculate_ema(close: pd.Series, period: int) -> pd.Series:
    """Calculate EMA"""
    return ta.ema(close, length=period)

def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate ADX"""
    adx_data = ta.adx(high, low, close, length=period)
    if adx_data is None or adx_data.empty:
        return pd.Series(index=high.index, dtype=float)
    adx_col = f'ADX_{period}'
    return adx_data[adx_col] if adx_col in adx_data.columns else pd.Series(index=high.index, dtype=float)

def calculate_donchian(high: pd.Series, low: pd.Series, period: int = 20) -> Tuple[pd.Series, pd.Series]:
    """Calculate Donchian Channels"""
    high_channel = high.rolling(window=period).max()
    low_channel = low.rolling(window=period).min()
    return high_channel, low_channel

def calculate_bollinger_bands(close: pd.Series, period: int = 20, std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Bollinger Bands (upper, middle, lower)"""
    bb = ta.bbands(close, length=period, std=std)
    if bb is None or bb.empty:
        return pd.Series(index=close.index, dtype=float), close.rolling(period).mean(), pd.Series(index=close.index, dtype=float)
    
    upper_col = f'BBU_{period}_{std}'
    lower_col = f'BBL_{period}_{std}'
    middle_col = f'BBM_{period}_{std}'
    
    upper = bb[upper_col] if upper_col in bb.columns else pd.Series(index=close.index, dtype=float)
    middle = bb[middle_col] if middle_col in bb.columns else close.rolling(period).mean()
    lower = bb[lower_col] if lower_col in bb.columns else pd.Series(index=close.index, dtype=float)
    
    return upper, middle, lower

def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI"""
    return ta.rsi(close, length=period)

def calculate_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, 
                        period: int = 14, smooth_k: int = 3) -> Tuple[pd.Series, pd.Series]:
    """Calculate Stochastic (K, D)"""
    stoch = ta.stoch(high, low, close, k=period, d=smooth_k)
    if stoch is None or stoch.empty:
        return pd.Series(index=high.index, dtype=float), pd.Series(index=high.index, dtype=float)
    
    k_col = f'STOCHk_{period}_{smooth_k}_3'
    d_col = f'STOCHd_{period}_{smooth_k}_3'
    
    k = stoch[k_col] if k_col in stoch.columns else pd.Series(index=high.index, dtype=float)
    d = stoch[d_col] if d_col in stoch.columns else pd.Series(index=high.index, dtype=float)
    
    return k, d

def calculate_keltner_channels(close: pd.Series, atr: pd.Series, period: int = 20, atr_mult: float = 1.5) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Keltner Channels"""
    middle = close.rolling(window=period).mean()
    upper = middle + (atr * atr_mult)
    lower = middle - (atr * atr_mult)
    return upper, middle, lower
