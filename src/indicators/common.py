"""
Расчет общих индикаторов для всех стратегий
Рассчитывается ОДИН РАЗ и используется всеми стратегиями
"""
import pandas as pd
import numpy as np
from typing import Dict
from src.indicators.technical import TechnicalIndicators
from src.indicators.cvd import CVDCalculator
from src.indicators.vwap import VWAPCalculator


def calculate_common_indicators(df: pd.DataFrame, timeframe: str = '1h') -> Dict:
    """
    Рассчитать все общие индикаторы один раз
    
    Args:
        df: DataFrame с OHLCV данными
        timeframe: Таймфрейм (для специфичных расчетов)
        
    Returns:
        Dict со всеми рассчитанными индикаторами
    """
    indicators = {}
    
    # === ATR ===
    indicators['atr_14'] = TechnicalIndicators.calculate_atr(df, period=14)
    indicators['atr_pct_14'] = TechnicalIndicators.calculate_atr_percent(df, period=14)
    
    # === EMA ===
    indicators['ema_20'] = TechnicalIndicators.calculate_ema(df, period=20)
    indicators['ema_50'] = TechnicalIndicators.calculate_ema(df, period=50)
    indicators['ema_200'] = TechnicalIndicators.calculate_ema(df, period=200)
    indicators['ema_9'] = TechnicalIndicators.calculate_ema(df, period=9)
    
    # === Bollinger Bands ===
    bb_20 = TechnicalIndicators.calculate_bb(df, period=20, std=2.0)
    indicators['bb_20'] = bb_20
    indicators['bb_width_20'] = TechnicalIndicators.calculate_bb_width(df, period=20, std=2.0)
    
    # Перцентили BB width на 60 барах (для проверки сжатия)
    if 'bb_width_20' in indicators and indicators['bb_width_20'] is not None:
        bb_width = indicators['bb_width_20']
        indicators['bb_width_p30'] = bb_width.rolling(60).quantile(0.30)
        indicators['bb_width_p40'] = bb_width.rolling(60).quantile(0.40)
        indicators['bb_width_p50'] = bb_width.rolling(60).quantile(0.50)
    
    # === Donchian Channels ===
    indicators['donchian_20'] = TechnicalIndicators.calculate_donchian(df, period=20)
    indicators['donchian_55'] = TechnicalIndicators.calculate_donchian(df, period=55)
    
    # === ADX ===
    adx_data = TechnicalIndicators.calculate_adx(df, period=14)
    indicators['adx_14'] = adx_data
    if adx_data is not None and not adx_data.empty:
        # Извлекаем столбцы ADX
        adx_col = [col for col in adx_data.columns if 'ADX' in col and 'DI' not in col]
        if adx_col:
            indicators['adx_value'] = adx_data[adx_col[0]]
    
    # === RSI ===
    indicators['rsi_14'] = TechnicalIndicators.calculate_rsi(df, period=14)
    
    # === Stochastic ===
    indicators['stoch_14_3'] = TechnicalIndicators.calculate_stochastic(df, k_period=14, d_period=3)
    
    # === CVD (Cumulative Volume Delta) ===
    indicators['cvd'] = CVDCalculator.calculate_bar_cvd(df)
    
    # === VWAP ===
    indicators['daily_vwap'] = VWAPCalculator.calculate_daily_vwap(df)
    
    # === EMA Slope ===
    indicators['ema_slope_20'] = TechnicalIndicators.calculate_ema_slope(df, period=20, lookback=5)
    
    # === Дополнительные расчеты для стратегий ===
    
    # Для Squeeze Breakout - проверка сжатия
    if 'bb_20' in indicators and indicators['bb_20'] is not None:
        bb = indicators['bb_20']
        upper_col = [col for col in bb.columns if 'BBU' in col]
        lower_col = [col for col in bb.columns if 'BBL' in col]
        
        if upper_col and lower_col:
            bb_range = bb[upper_col[0]] - bb[lower_col[0]]
            indicators['bb_range_20'] = bb_range
            indicators['bb_range_p20'] = bb_range.rolling(50).quantile(0.20)
    
    # Для Range Fade - range detection
    indicators['high_20'] = df['high'].rolling(20).max()
    indicators['low_20'] = df['low'].rolling(20).min()
    indicators['range_20'] = indicators['high_20'] - indicators['low_20']
    
    # Для Volume Profile - volume statistics
    indicators['volume_mean_20'] = df['volume'].rolling(20).mean()
    indicators['volume_std_20'] = df['volume'].rolling(20).std()
    
    return indicators
