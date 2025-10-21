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
                       ema200: Optional[pd.Series] = None,
                       htf_zones: Optional[Dict] = None,
                       vwap: Optional[pd.Series] = None,
                       swing_highs: Optional[List] = None,
                       swing_lows: Optional[List] = None,
                       zone_timeframe: str = '15m') -> float:
        """
        Рассчитать общий score зоны (0-100)
        
        Args:
            zone: Зона {'low': float, 'high': float, 'mid': float}
            touches: Список касаний от ReactionValidator
            current_time: Текущее время
            tau_days: Константа затухания для freshness
            df: DataFrame для анализа noise (optional)
            ema200: Серия EMA200 для confluence (optional)
            htf_zones: Dict с зонами старших TF для HTF alignment (optional)
            vwap: Серия VWAP для proximity check (optional)
            swing_highs: Список swing highs для confluence (optional)
            swing_lows: Список swing lows для confluence (optional)
            zone_timeframe: Timeframe зоны для HTF multiplier (default: '15m')
        
        Returns:
            Score 0-100 (с применением HTF multiplier)
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
        
        # 4. Confluence component (расширен с 2 до 7 факторов)
        confluence_score = self._score_confluence(
            zone, ema200, df, htf_zones, vwap, swing_highs, swing_lows
        )
        
        # 5. Noise penalty
        noise_penalty = self._score_noise(zone, df, touches)
        
        # Комбинировать
        base_score = (
            self.norm_w1 * touches_score +
            self.norm_w2 * reactions_score +
            self.norm_w3 * freshness_score +
            self.norm_w4 * confluence_score -
            self.norm_w5 * noise_penalty
        ) * 100
        
        # Применяем HTF multiplier
        final_score = self._apply_htf_multiplier(base_score, zone_timeframe)
        
        # Clamp 0-100
        return max(0.0, min(100.0, final_score))
    
    def _score_touches(self, valid_touches: List[Dict]) -> float:
        """
        Оценить количество валидных касаний (смягчено для лучшего баланса)
        
        Логика (обновлено на основе industry best practices): 
        - 0 touches = 0.0
        - 1 touch = 0.4 (было 0.3) - одно качественное касание достаточно
        - 2 touches = 0.65 (было 0.5) - оптимальное количество
        - 3 touches = 0.85 (было 0.7) - сильная зона
        - 4 touches = 0.95 (было 0.85)
        - 5-6 touches = 1.0 - максимум силы
        - 7+ touches = 0.9 - diminishing returns (зона истощается)
        """
        count = len(valid_touches)
        
        if count == 0:
            return 0.0
        elif count == 1:
            return 0.4
        elif count == 2:
            return 0.65
        elif count == 3:
            return 0.85
        elif count == 4:
            return 0.95
        elif count <= 6:
            return 1.0
        else:
            # 7+ касаний - зона истощается (diminishing returns)
            return 0.9
    
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
        try:
            last_touch = max(touches, key=lambda t: t['timestamp'])
            last_ts = last_touch['timestamp']
            
            # Конвертировать в datetime если нужно
            if isinstance(last_ts, pd.Timestamp):
                last_ts = last_ts.to_pydatetime()
            elif isinstance(last_ts, (int, float)):
                # Если это индекс или timestamp в секундах, вернуть default freshness
                return 0.5
            elif not isinstance(last_ts, datetime):
                # Неизвестный тип - вернуть default freshness
                return 0.5
            
            # Дельта времени в днях
            delta_days = (current_time - last_ts).total_seconds() / 86400
        except (TypeError, AttributeError, KeyError) as e:
            # Ошибка при обработке timestamp - вернуть default freshness
            return 0.5
        
        # Экспоненциальное затухание
        freshness = np.exp(-delta_days / tau_days)
        
        return float(freshness)
    
    def _score_confluence(self,
                         zone: Dict,
                         ema200: Optional[pd.Series],
                         df: Optional[pd.DataFrame],
                         htf_zones: Optional[Dict] = None,
                         vwap: Optional[pd.Series] = None,
                         swing_highs: Optional[List] = None,
                         swing_lows: Optional[List] = None) -> float:
        """
        Оценить confluence факторы (расширен с 2 до 7):
        1. EMA200 proximity (+0.2)
        2. Round numbers (+0.2)
        3. HTF zone alignment (+0.5) - САМЫЙ ВАЖНЫЙ!
        4. VWAP proximity (+0.3)
        5. Swing high/low (+0.4)
        6. Fibonacci levels (+0.3) - future
        7. POC proximity (+0.4) - future
        
        Returns:
            0.0-1.0 (сумма confluence бонусов, cap на 1.0)
        """
        score = 0.0
        
        # 1. EMA200 proximity (+0.2)
        if ema200 is not None and len(ema200) > 0:
            try:
                ema_val = ema200.iloc[-1]
                zone_range = zone['high'] - zone['low']
                ema_in_zone = zone['low'] <= ema_val <= zone['high']
                ema_close = abs(ema_val - zone['mid']) < zone_range * 0.5
                
                if ema_in_zone or ema_close:
                    score += 0.2
            except (IndexError, KeyError):
                pass
        
        # 2. Round numbers (+0.2)
        round_nums = self._find_round_numbers(zone)
        if round_nums:
            score += 0.2
        
        # 3. HTF Zone Alignment (+0.5) - КРИТИЧНО ВАЖНО!
        if htf_zones:
            htf_aligned = self._check_htf_alignment(zone, htf_zones)
            if htf_aligned:
                score += 0.5
        
        # 4. VWAP proximity (+0.3)
        if vwap is not None and len(vwap) > 0:
            try:
                vwap_val = vwap.iloc[-1]
                # VWAP в пределах зоны или очень близко
                vwap_in_zone = zone['low'] <= vwap_val <= zone['high']
                zone_range = zone['high'] - zone['low']
                vwap_close = abs(vwap_val - zone['mid']) < zone_range * 0.5
                
                if vwap_in_zone or vwap_close:
                    score += 0.3
            except (IndexError, KeyError):
                pass
        
        # 5. Swing High/Low confluence (+0.4)
        if swing_highs or swing_lows:
            swing_aligned = self._check_swing_alignment(
                zone, swing_highs, swing_lows
            )
            if swing_aligned:
                score += 0.4
        
        # Cap на 1.0
        return min(1.0, score)
    
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
    
    def _check_htf_alignment(self, zone: Dict, htf_zones: Dict) -> bool:
        """
        Проверить пересекается ли зона с зонами на старших TF
        
        Args:
            zone: Текущая зона
            htf_zones: Dict с зонами старших TF {'4h': [...], '1d': [...]}
        
        Returns:
            True если есть пересечение с HTF зоной
        """
        if not htf_zones:
            return False
        
        zone_low = zone['low']
        zone_high = zone['high']
        
        # Проверяем все HTF (4h, 1d)
        for tf, zones_list in htf_zones.items():
            if not zones_list:
                continue
            
            for htf_zone in zones_list:
                # Проверка пересечения зон
                htf_low = htf_zone.get('low', htf_zone.get('bottom', 0))
                htf_high = htf_zone.get('high', htf_zone.get('top', 0))
                
                # Зоны пересекаются если хоть немного overlap
                overlap = not (zone_high < htf_low or zone_low > htf_high)
                if overlap:
                    return True
        
        return False
    
    def _check_swing_alignment(self, 
                               zone: Dict, 
                               swing_highs: Optional[List],
                               swing_lows: Optional[List]) -> bool:
        """
        Проверить совпадает ли зона со swing high/low
        
        Args:
            zone: Текущая зона
            swing_highs: Список swing highs (price levels)
            swing_lows: Список swing lows (price levels)
        
        Returns:
            True если есть swing в зоне
        """
        zone_low = zone['low']
        zone_high = zone['high']
        
        # Проверяем swing highs
        if swing_highs:
            for swing in swing_highs:
                # swing может быть float или dict
                swing_price = swing if isinstance(swing, (int, float)) else swing.get('price', 0)
                if zone_low <= swing_price <= zone_high:
                    return True
        
        # Проверяем swing lows
        if swing_lows:
            for swing in swing_lows:
                swing_price = swing if isinstance(swing, (int, float)) else swing.get('price', 0)
                if zone_low <= swing_price <= zone_high:
                    return True
        
        return False
    
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
    
    def _apply_htf_multiplier(self, score: float, zone_timeframe: str) -> float:
        """
        Применить HTF multiplier к score зоны
        
        Higher timeframe = более надежные зоны = выше multiplier
        
        Args:
            score: Базовый score зоны (0-100)
            zone_timeframe: Timeframe зоны ('15m', '1h', '4h', '1d')
        
        Returns:
            Score с примененным multiplier
        """
        # HTF multipliers на основе industry best practices
        multipliers = {
            '1d': 1.2,   # Дневные зоны - самые надежные
            '4h': 1.1,   # 4-часовые зоны - очень надежные
            '1h': 1.0,   # Часовые зоны - baseline
            '15m': 0.95  # 15-минутные зоны - менее надежные
        }
        
        # Получить multiplier для данного TF (default 1.0)
        multiplier = multipliers.get(zone_timeframe, 1.0)
        
        return score * multiplier
