"""
Zone Scoring System
score = w1*Touches + w2*Reactions + w3*Freshness + w4*Confluence - w5*Noise

Classifies zones as: key (80+), strong (60-79), normal (40-59), weak (<40)
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime, timedelta


class ZoneScorer:
    """Calculates zone strength score (0-100)"""
    
    def __init__(self, 
                 w1_touches: int = 24,
                 w2_reactions: int = 28,
                 w3_freshness: int = 18,
                 w4_confluence: int = 22,
                 w5_noise: int = 12):
        """
        Args:
            w1-w5: Scoring weights (должны быть сбалансированы)
        """
        self.w1 = w1_touches
        self.w2 = w2_reactions
        self.w3 = w3_freshness
        self.w4 = w4_confluence
        self.w5 = w5_noise
        
        # Нормализация весов к 100 (все 5 весов включая noise)
        total = w1_touches + w2_reactions + w3_freshness + w4_confluence + w5_noise
        self.norm_w1 = w1_touches / total
        self.norm_w2 = w2_reactions / total
        self.norm_w3 = w3_freshness / total
        self.norm_w4 = w4_confluence / total
        self.norm_w5 = w5_noise / total
    
    def calculate_score(self,
                       zone: Dict,
                       touches: List[Dict],
                       current_time: datetime,
                       tau_days: float,
                       df: pd.DataFrame = None,
                       ema200: Optional[pd.Series] = None) -> float:
        """
        Рассчитать общий score зоны (0-100)
        
        Args:
            zone: Зона {'low': float, 'high': float, 'mid': float}
            touches: Список касаний от ReactionValidator
            current_time: Текущее время
            tau_days: Константа затухания для freshness
            df: DataFrame для анализа noise (optional)
            ema200: Серия EMA200 для confluence (optional)
        
        Returns:
            Score 0-100
        """
        # 1. Touches component
        valid_touches = [t for t in touches if t['valid']]
        touches_score = self._score_touches(valid_touches)
        
        # 2. Reactions component
        reactions_score = self._score_reactions(valid_touches)
        
        # 3. Freshness component  
        freshness_score = self._score_freshness(
            touches, current_time, tau_days
        )
        
        # 4. Confluence component
        confluence_score = self._score_confluence(
            zone, ema200, df
        )
        
        # 5. Noise penalty
        noise_penalty = self._score_noise(zone, df, touches)
        
        # Комбинировать
        score = (
            self.norm_w1 * touches_score +
            self.norm_w2 * reactions_score +
            self.norm_w3 * freshness_score +
            self.norm_w4 * confluence_score -
            self.norm_w5 * noise_penalty
        ) * 100
        
        # Clamp 0-100
        return max(0.0, min(100.0, score))
    
    def _score_touches(self, valid_touches: List[Dict]) -> float:
        """
        Оценить количество валидных касаний
        
        Логика: 
        - 0 touches = 0.0
        - 1-2 touches = 0.3-0.5
        - 3-4 touches = 0.6-0.8
        - 5+ touches = 0.9-1.0
        """
        count = len(valid_touches)
        
        if count == 0:
            return 0.0
        elif count == 1:
            return 0.3
        elif count == 2:
            return 0.5
        elif count == 3:
            return 0.7
        elif count == 4:
            return 0.85
        else:
            # Diminishing returns после 5+
            return min(1.0, 0.9 + (count - 5) * 0.02)
    
    def _score_reactions(self, valid_touches: List[Dict]) -> float:
        """
        Оценить силу реакций (median/max откат в ATR)
        
        Логика:
        - Median reaction ≥2.0 ATR = 1.0
        - 1.5 ATR = 0.8
        - 1.0 ATR = 0.6
        - 0.7 ATR = 0.4 (минимум для valid)
        """
        if not valid_touches:
            return 0.0
        
        reactions = [t['reaction_atr'] for t in valid_touches]
        median_reaction = np.median(reactions)
        
        # Линейная интерполяция
        if median_reaction >= 2.0:
            return 1.0
        elif median_reaction >= 1.5:
            return 0.6 + (median_reaction - 1.5) * 0.8  # 0.6-1.0
        elif median_reaction >= 1.0:
            return 0.4 + (median_reaction - 1.0) * 0.4  # 0.4-0.6
        else:
            return 0.2 + (median_reaction - 0.7) * 0.667  # 0.2-0.4
    
    def _score_freshness(self,
                        touches: List[Dict],
                        current_time: datetime,
                        tau_days: float) -> float:
        """
        Оценить свежесть зоны (exponential decay)
        
        freshness = exp(-Δt / τ)
        где Δt = дни с последнего касания, τ = константа затухания
        """
        if not touches:
            return 0.0
        
        # Найти последнее касание
        last_touch = max(touches, key=lambda t: t['timestamp'])
        last_ts = last_touch['timestamp']
        
        # Конвертировать в datetime если нужно
        if isinstance(last_ts, pd.Timestamp):
            last_ts = last_ts.to_pydatetime()
        
        # Дельта времени в днях
        delta_days = (current_time - last_ts).total_seconds() / 86400
        
        # Экспоненциальное затухание
        freshness = np.exp(-delta_days / tau_days)
        
        return float(freshness)
    
    def _score_confluence(self,
                         zone: Dict,
                         ema200: Optional[pd.Series],
                         df: Optional[pd.DataFrame]) -> float:
        """
        Оценить confluence факторы:
        - EMA200 близко к зоне
        - Round number в зоне
        - Пересечение с старшей зоной (будет в builder)
        - VWAP/POC (future)
        
        Returns:
            0.0-1.0 (доля confluence факторов)
        """
        factors = []
        
        # EMA200 proximity
        if ema200 is not None and len(ema200) > 0:
            ema_val = ema200.iloc[-1]
            # Проверка: EMA200 в пределах зоны или близко (±10%)
            zone_range = zone['high'] - zone['low']
            ema_in_zone = zone['low'] <= ema_val <= zone['high']
            ema_close = abs(ema_val - zone['mid']) < zone_range * 0.5
            
            if ema_in_zone or ema_close:
                factors.append('ema200')
        
        # Round number check
        round_nums = self._find_round_numbers(zone)
        if round_nums:
            factors.append('round')
        
        # Confluence score
        if not factors:
            return 0.0
        
        # Каждый фактор добавляет 0.5
        return min(1.0, len(factors) * 0.5)
    
    def _find_round_numbers(self, zone: Dict) -> List[float]:
        """
        Найти круглые числа в зоне
        
        Круглые: 100, 250, 500, 1000-кратные
        """
        round_nums = []
        zone_mid = zone['mid']
        
        # Определить порядок (100s, 1000s, 10000s)
        if zone_mid < 100:
            step = 10
        elif zone_mid < 1000:
            step = 100
        elif zone_mid < 10000:
            step = 250
        else:
            step = 1000
        
        # Проверить ближайшие круглые числа
        round_below = (zone_mid // step) * step
        round_above = round_below + step
        
        if zone['low'] <= round_below <= zone['high']:
            round_nums.append(round_below)
        if zone['low'] <= round_above <= zone['high']:
            round_nums.append(round_above)
        
        return round_nums
    
    def _score_noise(self,
                    zone: Dict,
                    df: Optional[pd.DataFrame],
                    touches: List[Dict]) -> float:
        """
        Штраф за noise (clarity penalty):
        - Частые закрытия внутри зоны без реакции
        - Множественные "пилы" (входы/выходы)
        
        Returns:
            0.0-1.0 (чем выше, тем больше шума)
        """
        if df is None or len(df) < 10:
            return 0.0
        
        # Считаем бары закрытые внутри зоны
        closes_in_zone = (
            (df['close'] >= zone['low']) & 
            (df['close'] <= zone['high'])
        ).sum()
        
        total_bars = len(df)
        pct_in_zone = closes_in_zone / total_bars
        
        # Если >20% баров внутри зоны - это шум
        if pct_in_zone > 0.20:
            noise = pct_in_zone  # 0.2-1.0
        else:
            noise = 0.0
        
        # Дополнительно: если много касаний но мало валидных реакций
        if len(touches) > 5:
            valid_ratio = len([t for t in touches if t['valid']]) / len(touches)
            if valid_ratio < 0.5:  # <50% валидных
                noise += 0.3
        
        return min(1.0, noise)
    
    def classify_strength(self, score: float) -> str:
        """
        Классифицировать силу зоны по score
        
        Returns:
            'key' | 'strong' | 'normal' | 'weak'
        """
        if score >= 80:
            return 'key'
        elif score >= 60:
            return 'strong'
        elif score >= 40:
            return 'normal'
        else:
            return 'weak'
