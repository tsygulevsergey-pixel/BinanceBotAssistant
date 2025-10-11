import pandas as pd
import numpy as np
from typing import Tuple, Optional


class SwingLevels:
    """
    Расчёт swing highs и swing lows используя fractal patterns
    
    Fractal pattern:
    - Swing High: локальный максимум с N барами ниже с каждой стороны
    - Swing Low: локальный минимум с N барами выше с каждой стороны
    """
    
    @staticmethod
    def find_swing_high(df: pd.DataFrame, lookback: int = 5, position: int = -1) -> Optional[float]:
        """
        Найти последний swing high используя fractal pattern
        
        Args:
            df: DataFrame с колонкой 'high'
            lookback: Количество баров с каждой стороны для подтверждения (default=5)
            position: Позиция для поиска (-1 = последний бар, -2 = предпоследний и т.д.)
        
        Returns:
            Swing high level или None если не найден
        """
        if len(df) < lookback * 2 + 1:
            return None
        
        # Начинаем с указанной позиции и идём назад
        for i in range(len(df) + position, lookback - 1, -1):
            if i - lookback < 0 or i + lookback >= len(df):
                continue
            
            current_high = df['high'].iloc[i]
            
            # Проверяем что все бары слева ниже
            left_bars = df['high'].iloc[i - lookback:i]
            left_valid = all(current_high > h for h in left_bars)
            
            # Проверяем что все бары справа ниже
            right_bars = df['high'].iloc[i + 1:i + lookback + 1]
            right_valid = all(current_high > h for h in right_bars)
            
            if left_valid and right_valid:
                return float(current_high)
        
        return None
    
    @staticmethod
    def find_swing_low(df: pd.DataFrame, lookback: int = 5, position: int = -1) -> Optional[float]:
        """
        Найти последний swing low используя fractal pattern
        
        Args:
            df: DataFrame с колонкой 'low'
            lookback: Количество баров с каждой стороны для подтверждения (default=5)
            position: Позиция для поиска (-1 = последний бар, -2 = предпоследний и т.д.)
        
        Returns:
            Swing low level или None если не найден
        """
        if len(df) < lookback * 2 + 1:
            return None
        
        # Начинаем с указанной позиции и идём назад
        for i in range(len(df) + position, lookback - 1, -1):
            if i - lookback < 0 or i + lookback >= len(df):
                continue
            
            current_low = df['low'].iloc[i]
            
            # Проверяем что все бары слева выше
            left_bars = df['low'].iloc[i - lookback:i]
            left_valid = all(current_low < l for l in left_bars)
            
            # Проверяем что все бары справа выше
            right_bars = df['low'].iloc[i + 1:i + lookback + 1]
            right_valid = all(current_low < l for l in right_bars)
            
            if left_valid and right_valid:
                return float(current_low)
        
        return None
    
    @staticmethod
    def get_swing_levels(df: pd.DataFrame, lookback: int = 5) -> Tuple[Optional[float], Optional[float]]:
        """
        Получить последние swing high и swing low
        
        Args:
            df: DataFrame с колонками 'high' и 'low'
            lookback: Количество баров с каждой стороны для fractal pattern
        
        Returns:
            Tuple (swing_high, swing_low)
        """
        swing_high = SwingLevels.find_swing_high(df, lookback=lookback)
        swing_low = SwingLevels.find_swing_low(df, lookback=lookback)
        
        return swing_high, swing_low
    
    @staticmethod
    def find_all_swing_highs(df: pd.DataFrame, lookback: int = 5, max_swings: int = 10) -> list:
        """
        Найти все swing highs в порядке убывания важности
        
        Args:
            df: DataFrame с колонкой 'high'
            lookback: Количество баров с каждой стороны
            max_swings: Максимальное количество swing levels
        
        Returns:
            List swing high levels
        """
        swings = []
        
        for i in range(len(df) - lookback - 1, lookback - 1, -1):
            if i - lookback < 0 or i + lookback >= len(df):
                continue
            
            current_high = df['high'].iloc[i]
            
            left_bars = df['high'].iloc[i - lookback:i]
            left_valid = all(current_high > h for h in left_bars)
            
            right_bars = df['high'].iloc[i + 1:i + lookback + 1]
            right_valid = all(current_high > h for h in right_bars)
            
            if left_valid and right_valid:
                swings.append(float(current_high))
                
                if len(swings) >= max_swings:
                    break
        
        return swings
    
    @staticmethod
    def find_all_swing_lows(df: pd.DataFrame, lookback: int = 5, max_swings: int = 10) -> list:
        """
        Найти все swing lows в порядке убывания важности
        
        Args:
            df: DataFrame с колонкой 'low'
            lookback: Количество баров с каждой стороны
            max_swings: Максимальное количество swing levels
        
        Returns:
            List swing low levels
        """
        swings = []
        
        for i in range(len(df) - lookback - 1, lookback - 1, -1):
            if i - lookback < 0 or i + lookback >= len(df):
                continue
            
            current_low = df['low'].iloc[i]
            
            left_bars = df['low'].iloc[i - lookback:i]
            left_valid = all(current_low < l for l in left_bars)
            
            right_bars = df['low'].iloc[i + 1:i + lookback + 1]
            right_valid = all(current_low < l for l in right_bars)
            
            if left_valid and right_valid:
                swings.append(float(current_low))
                
                if len(swings) >= max_swings:
                    break
        
        return swings


def calculate_swing_levels(df: pd.DataFrame, lookback: int = 5) -> Tuple[Optional[float], Optional[float]]:
    """
    Standalone функция для совместимости
    Рассчитывает swing high и swing low используя fractal patterns
    """
    return SwingLevels.get_swing_levels(df, lookback=lookback)
