"""
Flip Mechanism - R⇄S zone role switching
Когда resistance пробивается вверх → становится support (и наоборот)

Требования для flip:
1. Пробой телом (close за границей зоны > b1*ATR)
2. Закрепление (два варианта):
   - Базовый: N баров подряд закрыто за зоной
   - Альтернативный: 1 закрытие + ретест в ≤N баров с реакцией ≥r2*ATR
     - Ретест должен быть в пределах delta*ATR от края зоны
     - После ретеста реакция в сторону флипа ≥r2*ATR
"""

import pandas as pd
from typing import Dict, Optional, Literal


FlipState = Literal['normal', 'weakening', 'flipped']
ZoneKind = Literal['R', 'S']


class FlipDetector:
    """Детектирует пробои зон и смену R⇄S"""
    
    def __init__(self,
                 body_break_atr: float = 0.3,
                 confirmation_bars: int = 2,
                 retest_reaction_atr: float = 0.4,
                 weight_multiplier: float = 0.6,
                 retest_lookforward_bars: int = 12,
                 retest_accept_delta_atr: float = 0.25):
        """
        Args:
            body_break_atr: b1 - минимальный пробой телом (в ATR)
            confirmation_bars: N - баров для закрепления (базовый метод)
            retest_reaction_atr: r2 - минимальная реакция при ретесте
            weight_multiplier: Множитель для старого score после flip
            retest_lookforward_bars: Баров для поиска ретеста (альтернативный метод)
            retest_accept_delta_atr: Допуск для ретеста от края зоны
        """
        self.body_break_atr = body_break_atr
        self.confirmation_bars = confirmation_bars
        self.retest_reaction_atr = retest_reaction_atr
        self.weight_multiplier = weight_multiplier
        self.retest_lookforward_bars = retest_lookforward_bars
        self.retest_accept_delta_atr = retest_accept_delta_atr
    
    def check_flip(self,
                  zone: Dict,
                  df: pd.DataFrame,
                  atr_series: pd.Series,
                  lookback_bars: int = 20) -> Dict:
        """
        Проверить произошел ли flip зоны
        
        Args:
            zone: Зона {'kind': 'R'|'S', 'low': float, 'high': float, ...}
            df: DataFrame с OHLC (последние N баров)
            atr_series: Серия ATR
            lookback_bars: Сколько баров назад проверять
        
        Returns:
            {
                'flipped': bool,
                'new_kind': 'R'|'S' или None,
                'flip_bar_index': int или None,
                'confirmation_type': 'bars'|'retest'|None,
            }
        """
        if len(df) < lookback_bars:
            return {'flipped': False, 'new_kind': None, 
                   'flip_bar_index': None, 'confirmation_type': None}
        
        recent_df = df.tail(lookback_bars).copy()
        recent_atr = atr_series.tail(lookback_bars)
        
        kind = zone.get('kind', zone.get('type', 'R'))  # R или S
        
        if kind == 'R':
            # Resistance: ищем пробой вверх
            result = self._check_resistance_flip(
                zone, recent_df, recent_atr
            )
        else:  # S
            # Support: ищем пробой вниз
            result = self._check_support_flip(
                zone, recent_df, recent_atr
            )
        
        return result
    
    def _check_resistance_flip(self,
                               zone: Dict,
                               df: pd.DataFrame,
                               atr_series: pd.Series) -> Dict:
        """
        Проверить пробой Resistance → Support
        
        Логика:
        1. Close выше zone['high'] + b1*ATR
        2. N баров подряд закрываются выше ИЛИ ретест с реакцией
        """
        zone_high = zone['high']
        
        for i in range(len(df)):
            candle = df.iloc[i]
            current_atr = atr_series.iloc[i]
            
            # Пробой телом
            breakout_level = zone_high + self.body_break_atr * current_atr
            if candle['close'] <= breakout_level:
                continue
            
            # Проверить закрепление
            confirmed = self._check_confirmation_above(
                df, i, zone_high, atr_series
            )
            
            if confirmed['confirmed']:
                return {
                    'flipped': True,
                    'new_kind': 'S',  # Resistance → Support
                    'flip_bar_index': i,
                    'confirmation_type': confirmed['type'],
                }
        
        return {'flipped': False, 'new_kind': None, 
               'flip_bar_index': None, 'confirmation_type': None}
    
    def _check_support_flip(self,
                           zone: Dict,
                           df: pd.DataFrame,
                           atr_series: pd.Series) -> Dict:
        """
        Проверить пробой Support → Resistance
        
        Логика:
        1. Close ниже zone['low'] - b1*ATR
        2. N баров подряд закрываются ниже ИЛИ ретест с реакцией
        """
        zone_low = zone['low']
        
        for i in range(len(df)):
            candle = df.iloc[i]
            current_atr = atr_series.iloc[i]
            
            # Пробой телом
            breakout_level = zone_low - self.body_break_atr * current_atr
            if candle['close'] >= breakout_level:
                continue
            
            # Проверить закрепление
            confirmed = self._check_confirmation_below(
                df, i, zone_low, atr_series
            )
            
            if confirmed['confirmed']:
                return {
                    'flipped': True,
                    'new_kind': 'R',  # Support → Resistance
                    'flip_bar_index': i,
                    'confirmation_type': confirmed['type'],
                }
        
        return {'flipped': False, 'new_kind': None, 
               'flip_bar_index': None, 'confirmation_type': None}
    
    def _check_confirmation_above(self,
                                 df: pd.DataFrame,
                                 break_idx: int,
                                 zone_high: float,
                                 atr_series: pd.Series) -> Dict:
        """
        Проверить закрепление выше уровня (пробой R→S)
        
        Вариант 1 (базовый): N баров подряд закрываются выше zone_high
        Вариант 2 (альтернативный): 1 закрытие + ретест в ≤N баров
            - Ретест = low заходит в [zone_high, zone_high + delta_atr × ATR]
            - Реакция вверх ≥ r2_atr × ATR после ретеста
        """
        # Вариант 1: N баров подряд закрыты выше
        if break_idx + self.confirmation_bars < len(df):
            next_bars = df.iloc[break_idx+1:break_idx+1+self.confirmation_bars]
            all_above = (next_bars['close'] > zone_high).all()
            
            if all_above:
                return {'confirmed': True, 'type': 'bars'}
        
        # Вариант 2: Альтернативное подтверждение через ретест
        # У нас уже есть 1 закрытие выше (это break_idx бар)
        # Ищем ретест в следующих retest_lookforward_bars барах
        lookforward = min(self.retest_lookforward_bars, len(df) - break_idx - 1)
        
        if lookforward > 0:
            future_bars = df.iloc[break_idx+1:break_idx+1+lookforward]
            
            for j in range(len(future_bars)):
                candle = future_bars.iloc[j]
                atr_at_retest = atr_series.iloc[break_idx + 1 + j]
                
                # Ретест: low заходит в acceptance зону
                # [zone_high, zone_high + delta_atr × ATR]
                retest_upper = zone_high + self.retest_accept_delta_atr * atr_at_retest
                
                if zone_high <= candle['low'] <= retest_upper:
                    # Ретест обнаружен, проверяем реакцию вверх ПОСЛЕ ретеста
                    # Реакция = max(high) в следующих барах - zone_high
                    remaining_bars = len(future_bars) - j - 1  # Баров после j
                    
                    if remaining_bars > 0:
                        reaction_window = min(4, remaining_bars)
                        # CRITICAL: Начинаем с j+1 (следующий бар ПОСЛЕ ретеста)
                        reaction_bars = future_bars.iloc[j+1:j+1+reaction_window]
                        max_price = reaction_bars['high'].max()
                        reaction_dist = max_price - zone_high
                        
                        if reaction_dist >= self.retest_reaction_atr * atr_at_retest:
                            return {'confirmed': True, 'type': 'retest'}
        
        return {'confirmed': False, 'type': None}
    
    def _check_confirmation_below(self,
                                 df: pd.DataFrame,
                                 break_idx: int,
                                 zone_low: float,
                                 atr_series: pd.Series) -> Dict:
        """
        Проверить закрепление ниже уровня (пробой S→R)
        
        Вариант 1 (базовый): N баров подряд закрываются ниже zone_low
        Вариант 2 (альтернативный): 1 закрытие + ретест в ≤N баров
            - Ретест = high заходит в [zone_low - delta_atr × ATR, zone_low]
            - Реакция вниз ≥ r2_atr × ATR после ретеста
        """
        # Вариант 1: N баров подряд закрыты ниже
        if break_idx + self.confirmation_bars < len(df):
            next_bars = df.iloc[break_idx+1:break_idx+1+self.confirmation_bars]
            all_below = (next_bars['close'] < zone_low).all()
            
            if all_below:
                return {'confirmed': True, 'type': 'bars'}
        
        # Вариант 2: Альтернативное подтверждение через ретест
        # У нас уже есть 1 закрытие ниже (это break_idx бар)
        # Ищем ретест в следующих retest_lookforward_bars барах
        lookforward = min(self.retest_lookforward_bars, len(df) - break_idx - 1)
        
        if lookforward > 0:
            future_bars = df.iloc[break_idx+1:break_idx+1+lookforward]
            
            for j in range(len(future_bars)):
                candle = future_bars.iloc[j]
                atr_at_retest = atr_series.iloc[break_idx + 1 + j]
                
                # Ретест: high заходит в acceptance зону
                # [zone_low - delta_atr × ATR, zone_low]
                retest_lower = zone_low - self.retest_accept_delta_atr * atr_at_retest
                
                if retest_lower <= candle['high'] <= zone_low:
                    # Ретест обнаружен, проверяем реакцию вниз ПОСЛЕ ретеста
                    # Реакция = zone_low - min(low) в следующих барах
                    remaining_bars = len(future_bars) - j - 1  # Баров после j
                    
                    if remaining_bars > 0:
                        reaction_window = min(4, remaining_bars)
                        # CRITICAL: Начинаем с j+1 (следующий бар ПОСЛЕ ретеста)
                        reaction_bars = future_bars.iloc[j+1:j+1+reaction_window]
                        min_price = reaction_bars['low'].min()
                        reaction_dist = zone_low - min_price
                        
                        if reaction_dist >= self.retest_reaction_atr * atr_at_retest:
                            return {'confirmed': True, 'type': 'retest'}
        
        return {'confirmed': False, 'type': None}
    
    def apply_flip(self, zone: Dict, flip_result: Dict) -> Dict:
        """
        Применить flip к зоне (изменить kind и score)
        
        Args:
            zone: Оригинальная зона
            flip_result: Результат check_flip
        
        Returns:
            Обновленная зона
        """
        if not flip_result['flipped']:
            return zone
        
        updated_zone = zone.copy()
        
        # Сменить тип
        updated_zone['kind'] = flip_result['new_kind']
        updated_zone['state'] = 'flipped'
        updated_zone['flip_side'] = zone.get('kind', 'R')
        
        # ✅ FIX: Set meta['flipped'] flag for signal engine detection
        if 'meta' not in updated_zone:
            updated_zone['meta'] = {}
        updated_zone['meta']['flipped'] = True
        
        # Снизить score
        if 'strength' in updated_zone:
            updated_zone['strength'] *= self.weight_multiplier
        
        # Добавить в историю
        if 'history' not in updated_zone:
            updated_zone['history'] = []
        
        updated_zone['history'].append({
            'event': f"flip_to_{'support' if flip_result['new_kind'] == 'S' else 'resistance'}",
            'bar_index': flip_result['flip_bar_index'],
            'confirmation': flip_result['confirmation_type'],
        })
        
        return updated_zone
