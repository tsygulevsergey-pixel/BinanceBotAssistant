import pandas as pd
import numpy as np
from typing import Optional
from src.utils.logger import logger


class CVDCalculator:
    @staticmethod
    def calculate_bar_cvd(df: pd.DataFrame) -> pd.Series:
        """
        Рассчитать CVD из bar/kline данных
        Требуется колонка с taker buy volume для точного расчёта
        
        Проверяет разные варианты названий колонок:
        - taker_buy_base (стандартное название)
        - takerBuyBaseAssetVolume (Binance API naming)
        
        Если данных нет, возвращает Series из нулей с предупреждением
        """
        # Проверяем разные варианты названий колонок
        taker_buy_col = None
        
        if 'taker_buy_base' in df.columns:
            taker_buy_col = 'taker_buy_base'
        elif 'takerBuyBaseAssetVolume' in df.columns:
            taker_buy_col = 'takerBuyBaseAssetVolume'
        elif 'taker_buy_base_asset_volume' in df.columns:
            taker_buy_col = 'taker_buy_base_asset_volume'
        
        if taker_buy_col is None:
            logger.warning(
                "⚠️  CVD: Нет данных taker buy volume! CVD будет нулевым. "
                f"Доступные колонки: {list(df.columns)}"
            )
            return pd.Series(0, index=df.index)
        
        # Рассчитываем CVD
        buy_volume = df[taker_buy_col]
        sell_volume = df['volume'] - df[taker_buy_col]
        
        delta = buy_volume - sell_volume
        cvd = delta.cumsum()
        
        # Проверяем что CVD не все нули (качество данных)
        if cvd.sum() == 0:
            logger.warning(
                f"⚠️  CVD: Все значения равны нулю - возможно некачественные данные в колонке '{taker_buy_col}'"
            )
        
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
