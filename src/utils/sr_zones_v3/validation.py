"""
Reaction Validation - Measure zone strength by price reactions
A valid reaction = price reaches zone → reverses ≥0.7 ATR within m bars
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional


class ReactionValidator:
    """Validates and measures zone reactions (touches)"""
    
    def __init__(self, atr_mult: float = 0.7, bars_window: int = 8):
        """
        Args:
            atr_mult: Minimum reaction strength (0.7 = откат ≥0.7 ATR)
            bars_window: Lookback window to measure reaction (m bars)
        """
        self.atr_mult = atr_mult
        self.bars_window = bars_window
    
    def find_zone_touches(self, 
                         df: pd.DataFrame,
                         zone: Dict,
                         atr_series: pd.Series) -> List[Dict]:
        """
        Найти все касания зоны и измерить силу реакций
        
        Args:
            df: DataFrame с OHLC
            zone: Зона {'low': float, 'high': float, 'mid': float}
            atr_series: Серия ATR значений
        
        Returns:
            Список касаний: [{'index': int, 'timestamp': Timestamp, 
                             'reaction_atr': float, 'valid': bool}, ...]
        """
        touches = []
        
        for i in range(len(df)):
            candle = df.iloc[i]
            
            # Проверка касания: цена зашла в зону
            touches_zone = (
                candle['low'] <= zone['high'] and 
                candle['high'] >= zone['low']
            )
            
            if not touches_zone:
                continue
            
            # Измерить реакцию в следующих m барах
            reaction = self._measure_reaction(
                df, i, zone, atr_series.iloc[i]
            )
            
            touch = {
                'index': i,
                'timestamp': df.index[i],
                'price': float(candle['close']),
                'reaction_atr': reaction['strength_atr'],
                'reaction_bars': reaction['bars_to_peak'],
                'valid': reaction['valid'],
            }
            
            touches.append(touch)
        
        return touches
    
    def _measure_reaction(self, 
                         df: pd.DataFrame,
                         touch_idx: int,
                         zone: Dict,
                         current_atr: float) -> Dict:
        """
        Измерить силу реакции после касания
        
        Реакция = максимальное движение от зоны в сторону отбоя
        в пределах bars_window баров
        
        Returns:
            {'strength_atr': float, 'bars_to_peak': int, 'valid': bool}
        """
        if current_atr <= 0:
            return {'strength_atr': 0.0, 'bars_to_peak': 0, 'valid': False}
        
        # Определить направление зоны (support или resistance)
        touch_price = df.iloc[touch_idx]['close']
        zone_mid = zone['mid']
        
        # Если цена пришла снизу → support (ожидаем отскок вверх)
        # Если сверху → resistance (ожидаем отскок вниз)
        is_support = touch_price < zone_mid
        
        # Ищем пик движения в следующих m барах
        end_idx = min(touch_idx + self.bars_window, len(df) - 1)
        window = df.iloc[touch_idx:end_idx+1]
        
        if is_support:
            # Support: ищем максимум (upward reaction)
            peak_price = window['high'].max()
            reaction_distance = peak_price - zone['high']
            peak_idx = window['high'].idxmax()
        else:
            # Resistance: ищем минимум (downward reaction)
            peak_price = window['low'].min()
            reaction_distance = zone['low'] - peak_price
            peak_idx = window['low'].idxmin()
        
        # Сила реакции в ATR
        strength_atr = abs(reaction_distance) / current_atr
        
        # Количество баров до пика
        bars_to_peak = window.index.get_loc(peak_idx)
        
        # Валидность: реакция ≥ atr_mult
        valid = strength_atr >= self.atr_mult
        
        return {
            'strength_atr': strength_atr,
            'bars_to_peak': bars_to_peak,
            'valid': valid,
        }
    
    def calculate_avg_reaction(self, touches: List[Dict]) -> float:
        """
        Рассчитать среднюю силу валидных реакций
        
        Args:
            touches: Результат find_zone_touches
        
        Returns:
            Median reaction strength in ATR (0 if no valid touches)
        """
        valid_reactions = [
            t['reaction_atr'] for t in touches if t['valid']
        ]
        
        if not valid_reactions:
            return 0.0
        
        return float(np.median(valid_reactions))
