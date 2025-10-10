import pandas as pd
import numpy as np
from typing import Optional


class CVDCalculator:
    @staticmethod
    def calculate_bar_cvd(df: pd.DataFrame) -> pd.Series:
        if 'taker_buy_base' not in df.columns:
            return pd.Series(0, index=df.index)
        
        buy_volume = df['taker_buy_base']
        sell_volume = df['volume'] - df['taker_buy_base']
        
        delta = buy_volume - sell_volume
        cvd = delta.cumsum()
        
        return cvd
    
    @staticmethod
    def calculate_tick_cvd(trades_df: pd.DataFrame) -> pd.Series:
        if trades_df.empty:
            return pd.Series(dtype=float)
        
        trades_df = trades_df.copy()
        trades_df['delta'] = np.where(
            trades_df['is_buyer_maker'],
            -trades_df['quantity'],
            trades_df['quantity']
        )
        
        cvd = trades_df['delta'].cumsum()
        return cvd
    
    @staticmethod
    def detect_cvd_divergence(price: pd.Series, cvd: pd.Series, 
                             lookback: int = 20) -> str:
        if len(price) < lookback or len(cvd) < lookback:
            return 'none'
        
        recent_price = price.tail(lookback)
        recent_cvd = cvd.tail(lookback)
        
        price_trend = recent_price.iloc[-1] > recent_price.iloc[0]
        cvd_trend = recent_cvd.iloc[-1] > recent_cvd.iloc[0]
        
        if price_trend and not cvd_trend:
            return 'bearish'
        elif not price_trend and cvd_trend:
            return 'bullish'
        
        return 'none'
    
    @staticmethod
    def calculate_cvd_slope(cvd: pd.Series, period: int = 10) -> pd.Series:
        return cvd.diff(period) / period
