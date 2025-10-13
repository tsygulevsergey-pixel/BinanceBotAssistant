"""
Professional Market Regime Detection
Классифицирует рынок ПЕРЕД любой стратегией: TRENDING/RANGING/VOLATILE/CHOPPY
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Literal
from dataclasses import dataclass
from src.utils.logger import logger


RegimeType = Literal["TRENDING", "RANGING", "VOLATILE", "CHOPPY", "UNDECIDED"]


@dataclass
class MarketRegime:
    """Результат определения режима рынка"""
    regime: RegimeType
    confidence: float  # 0-1
    adx: float
    bb_width_percentile: float
    atr_percentile: float
    ema_alignment: bool
    details: Dict
    
    def is_suitable_for_strategy(self, strategy_type: str) -> bool:
        """Подходит ли режим для данного типа стратегии"""
        if self.regime == "CHOPPY":
            return False
            
        suitability_map = {
            "TRENDING": ["pullback", "retest", "breakout"],
            "RANGING": ["mean_reversion", "volume_profile", "range_fade"],
            "VOLATILE": ["liquidity_sweep", "order_flow", "momentum"],
            "UNDECIDED": []  # Лучше не торговать
        }
        
        suitable_types = suitability_map.get(self.regime, [])
        return any(st in strategy_type.lower() for st in suitable_types)


class MarketRegimeDetectorPro:
    """
    Профессиональный детектор режима рынка
    
    Методология:
    1. ADX - сила тренда
    2. BB Width - волатильность/сжатие
    3. ATR Percentile - текущая vs историческая волатильность
    4. EMA Alignment - направление тренда
    """
    
    def __init__(self, config: Dict):
        # Пороги из конфига
        self.adx_trending_threshold = config.get('market_detector.trend.adx_threshold', 25)
        self.adx_ranging_threshold = config.get('market_detector.range.adx_threshold', 20)
        self.bb_percentile_threshold = config.get('market_detector.range.bb_percentile', 30)
        self.atr_volatile_percentile = 80  # ATR > 80th percentile = VOLATILE
        
        # Lookback periods
        self.adx_period = 14
        self.bb_period = 20
        self.atr_period = 14
        self.atr_lookback = 100  # Для percentile расчета
        
    def detect_regime(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str = "4h"
    ) -> Optional[MarketRegime]:
        """
        Определить режим рынка
        
        Args:
            df: DataFrame с OHLCV данными
            symbol: Символ
            timeframe: Таймфрейм (по умолчанию 4h для контекста)
            
        Returns:
            MarketRegime или None если недостаточно данных
        """
        try:
            if len(df) < self.atr_lookback:
                logger.warning(f"Not enough data for regime detection: {symbol} ({len(df)} bars)")
                return None
            
            # 1. Расчет ADX (Average Directional Index)
            adx = self._calculate_adx(df)
            current_adx = adx.iloc[-1] if not adx.empty else 0
            
            # 2. Bollinger Bands Width (нормализованная)
            bb_width, bb_width_percentile = self._calculate_bb_width_percentile(df)
            
            # 3. ATR Percentile (текущая волатильность vs историческая)
            atr_percentile = self._calculate_atr_percentile(df)
            
            # 4. EMA Alignment (направление тренда)
            ema_aligned = self._check_ema_alignment(df)
            
            # 5. Классификация режима
            regime, confidence = self._classify_regime(
                adx=current_adx,
                bb_percentile=bb_width_percentile,
                atr_percentile=atr_percentile,
                ema_aligned=ema_aligned
            )
            
            details = {
                'symbol': symbol,
                'timeframe': timeframe,
                'adx': current_adx,
                'bb_width': bb_width,
                'bb_percentile': bb_width_percentile,
                'atr_percentile': atr_percentile,
                'ema_aligned': ema_aligned,
                'price': df['close'].iloc[-1],
                'classification_logic': self._get_classification_logic(
                    current_adx, bb_width_percentile, atr_percentile
                )
            }
            
            logger.debug(
                f"Regime detected for {symbol} ({timeframe}): {regime} "
                f"(ADX={current_adx:.1f}, BB%={bb_width_percentile:.0f}, "
                f"ATR%={atr_percentile:.0f}, Confidence={confidence:.2f})"
            )
            
            return MarketRegime(
                regime=regime,
                confidence=confidence,
                adx=current_adx,
                bb_width_percentile=bb_width_percentile,
                atr_percentile=atr_percentile,
                ema_alignment=ema_aligned,
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in regime detection for {symbol}: {e}", exc_info=True)
            return None
    
    def _calculate_adx(self, df: pd.DataFrame) -> pd.Series:
        """Расчет ADX (Average Directional Index)"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        # Smoothed TR and DM
        atr = tr.rolling(self.adx_period).mean()
        plus_di = 100 * (pd.Series(plus_dm).rolling(self.adx_period).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm).rolling(self.adx_period).mean() / atr)
        
        # ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(self.adx_period).mean()
        
        return adx.fillna(0)
    
    def _calculate_bb_width_percentile(self, df: pd.DataFrame) -> tuple[float, float]:
        """Расчет BB Width и его перцентиля"""
        close = df['close']
        
        # Bollinger Bands
        sma = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        
        # Нормализованная ширина (% от цены)
        bb_width = (2 * std / sma) * 100
        bb_width = bb_width.fillna(0)
        
        # Перцентиль текущей ширины за последние 100 баров
        current_width = bb_width.iloc[-1]
        historical_widths = bb_width.iloc[-self.atr_lookback:]
        percentile = (historical_widths < current_width).sum() / len(historical_widths) * 100
        
        return current_width, percentile
    
    def _calculate_atr_percentile(self, df: pd.DataFrame) -> float:
        """Расчет ATR Percentile"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # ATR
        atr = tr.rolling(self.atr_period).mean()
        
        # Перцентиль текущего ATR
        current_atr = atr.iloc[-1]
        historical_atr = atr.iloc[-self.atr_lookback:]
        percentile = (historical_atr < current_atr).sum() / len(historical_atr) * 100
        
        return percentile
    
    def _check_ema_alignment(self, df: pd.DataFrame) -> bool:
        """Проверка alignment EMA (тренд)"""
        close = df['close']
        
        ema_20 = close.ewm(span=20, adjust=False).mean()
        ema_50 = close.ewm(span=50, adjust=False).mean()
        
        # Aligned = EMA20 > EMA50 (uptrend) ИЛИ EMA20 < EMA50 (downtrend)
        aligned = abs(ema_20.iloc[-1] - ema_50.iloc[-1]) / ema_50.iloc[-1] > 0.005  # > 0.5% difference
        
        return aligned
    
    def _classify_regime(
        self,
        adx: float,
        bb_percentile: float,
        atr_percentile: float,
        ema_aligned: bool
    ) -> tuple[RegimeType, float]:
        """
        Классификация режима рынка с confidence
        
        Логика (в порядке приоритета):
        1. CHOPPY: ADX < 15 AND BB < 20th percentile → НЕ ТОРГОВАТЬ!
        2. VOLATILE: ATR > 80th percentile → специальные стратегии
        3. TRENDING: ADX > 25 AND EMA aligned → breakout/pullback
        4. RANGING: ADX < 20 AND BB < 30th percentile → mean reversion
        5. UNDECIDED: остальное → осторожно
        """
        confidence = 0.5  # базовая
        
        # CHOPPY (самый опасный - избегать!)
        if adx < 15 and bb_percentile < 20:
            return ("CHOPPY", 0.9)
        
        # VOLATILE (высокая волатильность)
        if atr_percentile > self.atr_volatile_percentile:
            confidence = 0.7 + (atr_percentile - 80) / 100  # 0.7-0.9
            return ("VOLATILE", min(confidence, 0.95))
        
        # TRENDING (сильный тренд)
        if adx > self.adx_trending_threshold:
            confidence = 0.6 + (adx - 25) / 100  # Выше ADX = выше confidence
            if ema_aligned:
                confidence += 0.15
            return ("TRENDING", min(confidence, 0.95))
        
        # RANGING (флет с низкой волатильностью)
        if adx < self.adx_ranging_threshold and bb_percentile < self.bb_percentile_threshold:
            confidence = 0.6 + (30 - bb_percentile) / 100
            return ("RANGING", min(confidence, 0.9))
        
        # UNDECIDED (неопределенность - лучше пропустить)
        return ("UNDECIDED", 0.3)
    
    def _get_classification_logic(self, adx: float, bb_percentile: float, atr_percentile: float) -> str:
        """Объяснение логики классификации"""
        if adx < 15 and bb_percentile < 20:
            return "CHOPPY: Low ADX + Narrow BB → High noise, skip trading"
        elif atr_percentile > 80:
            return f"VOLATILE: ATR {atr_percentile:.0f}th percentile → Use sweep/order flow"
        elif adx > 25:
            return f"TRENDING: ADX {adx:.1f} → Use breakout/pullback strategies"
        elif adx < 20 and bb_percentile < 30:
            return "RANGING: Low ADX + Low BB → Use mean reversion"
        else:
            return "UNDECIDED: Mixed signals → Trade cautiously or skip"
    
    def get_suitable_strategies(self, regime: MarketRegime) -> list[str]:
        """Получить подходящие стратегии для режима"""
        strategy_map = {
            "TRENDING": [
                "pullback",  # MA/VWAP Pullback
                "retest",    # Break & Retest
            ],
            "RANGING": [
                "volume_profile",  # Volume Profile
            ],
            "VOLATILE": [
                "liquidity_sweep",  # Liquidity Sweep
                "order_flow",       # Order Flow
            ],
            "CHOPPY": [],  # НЕ ТОРГОВАТЬ!
            "UNDECIDED": []  # Осторожно или skip
        }
        
        return strategy_map.get(regime.regime, [])
