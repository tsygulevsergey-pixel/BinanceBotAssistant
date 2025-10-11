import pandas as pd
from enum import Enum
from typing import Dict, Optional
from src.indicators.technical import TechnicalIndicators
from src.utils.config import config
from src.utils.logger import logger


class MarketRegime(Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    CHOP = "CHOP"  # Choppy/боковое движение
    SQUEEZE = "SQUEEZE"
    UNDECIDED = "UNDECIDED"


class MarketRegimeDetector:
    def __init__(self):
        self.adx_threshold = config.get('market_detector.trend.adx_threshold', 20)
        self.bb_percentile_threshold = config.get('market_detector.range.bb_percentile', 30)
        self.squeeze_bb_percentile = config.get('market_detector.squeeze.bb_percentile', 25)
        self.squeeze_min_bars = config.get('market_detector.squeeze.min_bars', 12)
        self.late_trend_atr_mult = config.get('market_detector.trend.late_trend_atr_multiplier', 1.8)
        self.ema_periods = config.get('market_detector.trend.ema_periods', [20, 50, 200])
    
    def detect_regime(self, df: pd.DataFrame, timeframe: str = '1h') -> Dict:
        if len(df) < 200:
            logger.warning(f"Insufficient data for regime detection ({len(df)} bars)")
            return {
                'regime': MarketRegime.UNDECIDED,
                'confidence': 0.0,
                'late_trend': False,
                'details': {}
            }
        
        adx_data = TechnicalIndicators.calculate_adx(df)
        adx = adx_data[f'ADX_{14}'].iloc[-1] if f'ADX_{14}' in adx_data.columns else 0
        
        atr = TechnicalIndicators.calculate_atr(df).iloc[-1]
        atr_percent = TechnicalIndicators.calculate_atr_percent(df).iloc[-1]
        
        bb_width = TechnicalIndicators.calculate_bb_width(df)
        bb_width_current = bb_width.iloc[-1] if not bb_width.empty else 0
        bb_width_percentile = TechnicalIndicators.calculate_percentile(bb_width, bb_width_current, period=90)
        
        ema_20 = TechnicalIndicators.calculate_ema(df, 20).iloc[-1]
        ema_50 = TechnicalIndicators.calculate_ema(df, 50).iloc[-1]
        ema_200 = TechnicalIndicators.calculate_ema(df, 200).iloc[-1]
        
        close = df['close'].iloc[-1]
        
        ema_aligned_bull = ema_20 > ema_50 > ema_200
        ema_aligned_bear = ema_20 < ema_50 < ema_200
        ema_aligned = ema_aligned_bull or ema_aligned_bear
        
        distance_to_ema20 = abs(close - ema_20) / atr if atr > 0 else 0
        late_trend = distance_to_ema20 > self.late_trend_atr_mult
        
        squeeze_bars = self._count_squeeze_bars(bb_width, self.squeeze_bb_percentile)
        is_squeeze = (bb_width_percentile < self.squeeze_bb_percentile and 
                     squeeze_bars >= self.squeeze_min_bars)
        
        regime = MarketRegime.UNDECIDED
        confidence = 0.0
        
        # ПРИОРИТЕТ 1: TREND - сильный тренд с высоким ADX и выровненными EMA
        if adx > self.adx_threshold and ema_aligned:
            regime = MarketRegime.TREND
            confidence = min(adx / 40, 1.0)
            logger.debug(f"Regime: TREND | ADX={adx:.1f} > {self.adx_threshold}, EMA aligned={ema_aligned}")
        
        # ПРИОРИТЕТ 2: SQUEEZE - очень узкая консолидация (BB width < 25 + длительность)
        elif is_squeeze:
            regime = MarketRegime.SQUEEZE
            confidence = min(squeeze_bars / self.squeeze_min_bars, 1.0)
            logger.debug(f"Regime: SQUEEZE | BB%ile={bb_width_percentile:.1f} < {self.squeeze_bb_percentile}, bars={squeeze_bars} >= {self.squeeze_min_bars}")
        
        # ПРИОРИТЕТ 3: RANGE/CHOP - низкий ADX и низкая волатильность (но не squeeze)
        elif adx < self.adx_threshold and bb_width_percentile < self.bb_percentile_threshold:
            ema_20_slope_raw = abs(TechnicalIndicators.calculate_ema_slope(df, 20).iloc[-1])
            ema_50_slope_raw = abs(TechnicalIndicators.calculate_ema_slope(df, 50).iloc[-1])
            
            # Нормализация slope в процентах от цены (чтобы работало для любых активов)
            ema_20_slope_pct = (ema_20_slope_raw / ema_20 * 100) if ema_20 > 0 else 0
            ema_50_slope_pct = (ema_50_slope_raw / ema_50 * 100) if ema_50 > 0 else 0
            
            # Threshold: 0.05% для различия CHOP vs RANGE (0.05% slope за бар)
            slope_threshold_pct = 0.05
            
            # CHOP - беспорядочное движение (EMA не плоские, но ADX низкий)
            if ema_20_slope_pct >= slope_threshold_pct or ema_50_slope_pct >= slope_threshold_pct:
                regime = MarketRegime.CHOP
                confidence = 1.0 - (adx / self.adx_threshold)
                logger.debug(f"Regime: CHOP | ADX={adx:.1f} < {self.adx_threshold}, BB%ile={bb_width_percentile:.1f} < {self.bb_percentile_threshold}, EMA20 slope={ema_20_slope_pct:.3f}%, EMA50 slope={ema_50_slope_pct:.3f}%")
            # RANGE - чистый боковик (EMA плоские, ADX низкий)
            else:
                regime = MarketRegime.RANGE
                confidence = 1.0 - (adx / self.adx_threshold)
                logger.debug(f"Regime: RANGE | ADX={adx:.1f} < {self.adx_threshold}, BB%ile={bb_width_percentile:.1f} < {self.bb_percentile_threshold}, EMA20 slope={ema_20_slope_pct:.3f}%, EMA50 slope={ema_50_slope_pct:.3f}%")
        
        details = {
            'adx': adx,
            'atr': atr,
            'atr_percent': atr_percent,
            'bb_width_percentile': bb_width_percentile,
            'ema_20': ema_20,
            'ema_50': ema_50,
            'ema_200': ema_200,
            'ema_aligned': ema_aligned,
            'distance_to_ema20_atr': distance_to_ema20,
            'squeeze_bars': squeeze_bars
        }
        
        return {
            'regime': regime,
            'confidence': confidence,
            'late_trend': late_trend,
            'details': details
        }
    
    def _count_squeeze_bars(self, bb_width: pd.Series, percentile_threshold: float) -> int:
        if bb_width.empty or len(bb_width) < 20:
            return 0
        
        count = 0
        for i in range(len(bb_width) - 1, -1, -1):
            percentile = TechnicalIndicators.calculate_percentile(
                bb_width[:i+1], bb_width.iloc[i], period=90
            )
            if percentile < percentile_threshold:
                count += 1
            else:
                break
        
        return count
    
    def get_h4_bias(self, df_h4: pd.DataFrame) -> str:
        if len(df_h4) < 50:
            return 'neutral'
        
        ema_50 = TechnicalIndicators.calculate_ema(df_h4, 50).iloc[-1]
        ema_200 = TechnicalIndicators.calculate_ema(df_h4, 200).iloc[-1]
        close = df_h4['close'].iloc[-1]
        
        if close > ema_50 > ema_200:
            return 'bullish'
        elif close < ema_50 < ema_200:
            return 'bearish'
        else:
            return 'neutral'
