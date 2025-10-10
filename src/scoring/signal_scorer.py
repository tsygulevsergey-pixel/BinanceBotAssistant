"""
Система скоринга сигналов согласно мануалу.

Скоринг сделки (вход при score ≥ +2):
- +1 объём > 1.5× медианы 20 баров
- +1 CVD в сторону (или дивергенция для MR)
- +1 ΔOI ≥ +1…+3% за 30–90 мин
- +1 устойчивый depth-imbalance 10–30с в сторону
- −1 LATE_TREND / funding-экстрем
- −2 BTC идёт против (на H1)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from src.strategies.base_strategy import Signal
from src.utils.logger import logger


class SignalScorer:
    """Система скоринга сигналов"""
    
    def __init__(self, config: Dict):
        self.volume_threshold = config.get('scoring.volume_mult', 1.5)
        self.doi_min_pct = config.get('scoring.doi_min_pct', 1.0)
        self.doi_max_pct = config.get('scoring.doi_max_pct', 3.0)
        self.enter_threshold = config.get('scoring.enter_threshold', 2.0)
        
        # Depth imbalance пороги
        self.imbalance_long_max = config.get('scoring.depth_imbalance_ratio.long_max', 0.90)
        self.imbalance_short_min = config.get('scoring.depth_imbalance_ratio.short_min', 1.10)
        
        # BTC filter TF
        self.btc_filter_tf = config.get('scoring.btc_filter_tf', '1h')
        
    def score_signal(
        self,
        signal: Signal,
        market_data: Dict,
        indicators: Dict,
        btc_data: Optional[pd.DataFrame] = None
    ) -> float:
        """
        Рассчитать финальный score сигнала
        
        Args:
            signal: Сигнал стратегии
            market_data: Рыночные данные (df, volume, etc.)
            indicators: Индикаторы (CVD, OI, imbalance, etc.)
            btc_data: BTC данные для фильтра
            
        Returns:
            Финальный score (float)
        """
        score = signal.base_score  # Начинаем с базового score от стратегии
        
        # +1: Объём > 1.5× медианы 20 баров
        if signal.volume_ratio and signal.volume_ratio >= self.volume_threshold:
            score += 1.0
            logger.debug(f"{signal.symbol} +1 volume (ratio={signal.volume_ratio:.2f})")
        
        # +1: CVD в сторону (или дивергенция для MR)
        cvd_score = self._score_cvd(signal, indicators)
        score += cvd_score
        
        # +1: ΔOI ≥ +1…+3% за 30–90 мин
        doi_score = self._score_doi(signal, indicators)
        score += doi_score
        
        # +1: Устойчивый depth-imbalance 10–30с в сторону
        imbalance_score = self._score_imbalance(signal, indicators)
        score += imbalance_score
        
        # −1: LATE_TREND / funding-экстрем
        late_trend_penalty = self._score_late_trend(signal, indicators)
        score += late_trend_penalty
        
        # −2: BTC идёт против (на H1)
        btc_penalty = self._score_btc_filter(signal, btc_data)
        score += btc_penalty
        
        logger.info(
            f"{signal.symbol} {signal.direction} score={score:.1f} "
            f"(base={signal.base_score}, vol={signal.volume_ratio:.2f})"
        )
        
        return score
    
    def _score_cvd(self, signal: Signal, indicators: Dict) -> float:
        """
        Скоринг CVD (Cumulative Volume Delta)
        +1 если CVD в сторону сигнала (или дивергенция для MR)
        """
        cvd = indicators.get('cvd', None)
        if cvd is None:
            return 0.0
        
        # Для MR стратегий проверяем дивергенцию
        if signal.strategy_name in ['VWAP Mean Reversion', 'Range Fade', 'RSI/Stoch MR']:
            # Упрощённо: проверяем flip CVD
            cvd_direction = 'bullish' if cvd > 0 else 'bearish'
            if signal.direction == 'LONG' and cvd_direction == 'bullish':
                logger.debug(f"{signal.symbol} +1 CVD flip bullish (MR)")
                return 1.0
            elif signal.direction == 'SHORT' and cvd_direction == 'bearish':
                logger.debug(f"{signal.symbol} +1 CVD flip bearish (MR)")
                return 1.0
        else:
            # Для трендовых: CVD в сторону
            if signal.direction == 'LONG' and cvd > 0:
                logger.debug(f"{signal.symbol} +1 CVD bullish")
                return 1.0
            elif signal.direction == 'SHORT' and cvd < 0:
                logger.debug(f"{signal.symbol} +1 CVD bearish")
                return 1.0
        
        return 0.0
    
    def _score_doi(self, signal: Signal, indicators: Dict) -> float:
        """
        Скоринг ΔOI (Delta Open Interest)
        +1 если ΔOI ≥ +1…+3% за 30–90 мин
        """
        doi_pct = indicators.get('doi_pct', None)
        if doi_pct is None:
            return 0.0
        
        # Проверка: ΔOI в нужном диапазоне
        if self.doi_min_pct <= abs(doi_pct) <= self.doi_max_pct:
            # Для LONG нужен положительный ΔOI
            if signal.direction == 'LONG' and doi_pct > 0:
                logger.debug(f"{signal.symbol} +1 ΔOI={doi_pct:.2f}%")
                return 1.0
            # Для SHORT тоже положительный (рост интереса)
            elif signal.direction == 'SHORT' and doi_pct > 0:
                logger.debug(f"{signal.symbol} +1 ΔOI={doi_pct:.2f}%")
                return 1.0
        
        return 0.0
    
    def _score_imbalance(self, signal: Signal, indicators: Dict) -> float:
        """
        Скоринг depth-imbalance
        +1 если устойчивый imbalance 10–30с в сторону
        """
        imbalance_ratio = indicators.get('depth_imbalance', None)
        if imbalance_ratio is None:
            return 0.0
        
        # LONG: imbalance должен быть низким (больше bid ликвидности)
        # Ratio = Ask/Bid, если < 0.90 значит bid преобладает
        if signal.direction == 'LONG' and imbalance_ratio <= self.imbalance_long_max:
            logger.debug(f"{signal.symbol} +1 imbalance bullish (ratio={imbalance_ratio:.2f})")
            return 1.0
        
        # SHORT: imbalance высокий (больше ask ликвидности)
        elif signal.direction == 'SHORT' and imbalance_ratio >= self.imbalance_short_min:
            logger.debug(f"{signal.symbol} +1 imbalance bearish (ratio={imbalance_ratio:.2f})")
            return 1.0
        
        return 0.0
    
    def _score_late_trend(self, signal: Signal, indicators: Dict) -> float:
        """
        Пенальти за LATE_TREND или funding экстрем
        −1 если условия выполнены
        """
        penalty = 0.0
        
        # LATE_TREND: цена слишком далеко от EMA20 (>1.5-1.8 ATR)
        late_trend = indicators.get('late_trend', False)
        if late_trend:
            logger.debug(f"{signal.symbol} -1 LATE_TREND")
            penalty -= 1.0
        
        # Funding экстрем (z-score > 2.5)
        funding_extreme = indicators.get('funding_extreme', False)
        if funding_extreme:
            logger.debug(f"{signal.symbol} -1 funding extreme")
            penalty -= 1.0
        
        return penalty
    
    def _score_btc_filter(
        self, 
        signal: Signal, 
        btc_data: Optional[pd.DataFrame]
    ) -> float:
        """
        BTC фильтр: −2 если BTC идёт против (на H1)
        """
        if btc_data is None or len(btc_data) < 2:
            return 0.0
        
        # Определить направление BTC
        btc_close_current = btc_data['close'].iloc[-1]
        btc_close_prev = btc_data['close'].iloc[-2]
        btc_direction = 'up' if btc_close_current > btc_close_prev else 'down'
        
        # Пенальти если BTC против сигнала
        if signal.direction == 'LONG' and btc_direction == 'down':
            logger.debug(f"{signal.symbol} -2 BTC against (BTC down, signal LONG)")
            return -2.0
        elif signal.direction == 'SHORT' and btc_direction == 'up':
            logger.debug(f"{signal.symbol} -2 BTC against (BTC up, signal SHORT)")
            return -2.0
        
        return 0.0
    
    def should_enter(self, score: float) -> bool:
        """Проверить, достаточен ли score для входа"""
        return score >= self.enter_threshold
