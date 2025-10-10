"""
Reclaim механизм для проверки что цена удержалась в зоне N баров
Используется в mean reversion стратегиях для снижения ложных сигналов
"""

import pandas as pd
from typing import Optional, Union, Tuple


def check_reclaim_hold(
    df: pd.DataFrame,
    zone_level: Union[float, Tuple[float, float]],
    direction: str,
    hold_bars: int = 2,
    tolerance_pct: float = 0.1
) -> bool:
    """
    Проверить что цена удержалась внутри/за пределами зоны N баров
    
    Args:
        df: DataFrame с OHLC данными
        zone_level: Уровень зоны для проверки
        direction: 'above' (цена выше зоны) или 'below' (цена ниже зоны) или 'inside_range' (внутри диапазона)
        hold_bars: Сколько баров должна удержаться (по умолчанию 2)
        tolerance_pct: Допустимое отклонение в % (по умолчанию 0.1%)
    
    Returns:
        bool: True если цена удержалась нужное количество баров
    
    Examples:
        # Проверить что цена выше VAL последние 2 бара
        check_reclaim_hold(df, val_level, 'above', hold_bars=2)
        
        # Проверить что цена ниже VAH последние 2 бара  
        check_reclaim_hold(df, vah_level, 'below', hold_bars=2)
    """
    if df is None or len(df) < hold_bars:
        return False
    
    if isinstance(zone_level, tuple):
        tolerance = zone_level[0] * (tolerance_pct / 100)
    else:
        tolerance = zone_level * (tolerance_pct / 100)
    
    last_bars = df.tail(hold_bars)
    
    if direction == 'above':
        if isinstance(zone_level, tuple):
            return False
        return all(last_bars['close'] >= zone_level - tolerance)
    
    elif direction == 'below':
        if isinstance(zone_level, tuple):
            return False
        return all(last_bars['close'] <= zone_level + tolerance)
    
    elif direction == 'inside_range':
        if not isinstance(zone_level, tuple):
            return False
        return all(
            (last_bars['close'] >= zone_level[0] - tolerance) &
            (last_bars['close'] <= zone_level[1] + tolerance)
        )
    
    return False


def check_value_area_reclaim(
    df: pd.DataFrame,
    val: float,
    vah: float,
    direction: str,
    hold_bars: int = 2
) -> bool:
    """
    Проверить reclaim в Value Area с удержанием N баров
    
    Args:
        df: DataFrame с OHLC данными
        val: Value Area Low
        vah: Value Area High
        direction: 'long' (reclaim выше VAL) или 'short' (reclaim ниже VAH)
        hold_bars: Сколько баров должна удержаться внутри VA
    
    Returns:
        bool: True если цена вернулась в VA и удержалась там
    """
    if df is None or len(df) < hold_bars + 1:
        return False
    
    if direction == 'long':
        was_below = df.iloc[-hold_bars - 1]['close'] < val
        now_inside = check_reclaim_hold(df, val, 'above', hold_bars=hold_bars)
        return was_below and now_inside
    
    elif direction == 'short':
        was_above = df.iloc[-hold_bars - 1]['close'] > vah
        now_inside = check_reclaim_hold(df, vah, 'below', hold_bars=hold_bars)
        return was_above and now_inside
    
    return False


def check_range_reclaim(
    df: pd.DataFrame,
    range_low: float,
    range_high: float,
    direction: str,
    hold_bars: int = 2
) -> bool:
    """
    Проверить reclaim в диапазон с удержанием N баров
    
    Args:
        df: DataFrame с OHLC данными
        range_low: Нижняя граница диапазона
        range_high: Верхняя граница диапазона
        direction: 'long' (reclaim с низа) или 'short' (reclaim с верха)
        hold_bars: Сколько баров должна удержаться внутри диапазона
    
    Returns:
        bool: True если цена вернулась в диапазон и удержалась
    """
    if df is None or len(df) < hold_bars + 1:
        return False
    
    prev_close = df.iloc[-hold_bars - 1]['close']
    
    if direction == 'long':
        was_below = prev_close < range_low
        now_inside = check_reclaim_hold(
            df, 
            (range_low, range_high), 
            'inside_range', 
            hold_bars=hold_bars
        )
        return was_below and now_inside
    
    elif direction == 'short':
        was_above = prev_close > range_high
        now_inside = check_reclaim_hold(
            df,
            (range_low, range_high),
            'inside_range',
            hold_bars=hold_bars
        )
        return was_above and now_inside
    
    return False


def check_level_reclaim(
    df: pd.DataFrame,
    level: float,
    direction: str,
    hold_bars: int = 2,
    tolerance_pct: float = 0.15
) -> bool:
    """
    Проверить reclaim уровня (VWAP, EMA, etc) с удержанием
    
    Args:
        df: DataFrame с OHLC данными
        level: Уровень для проверки
        direction: 'long' (reclaim выше уровня) или 'short' (reclaim ниже уровня)
        hold_bars: Сколько баров должна удержаться
        tolerance_pct: Допустимое отклонение в %
    
    Returns:
        bool: True если цена вернулась к уровню и удержалась
    """
    if df is None or len(df) < hold_bars + 1:
        return False
    
    prev_close = df.iloc[-hold_bars - 1]['close']
    tolerance = level * (tolerance_pct / 100)
    
    if direction == 'long':
        was_below = prev_close < level - tolerance
        now_above = check_reclaim_hold(df, level, 'above', hold_bars=hold_bars, tolerance_pct=tolerance_pct)
        return was_below and now_above
    
    elif direction == 'short':
        was_above = prev_close > level + tolerance
        now_below = check_reclaim_hold(df, level, 'below', hold_bars=hold_bars, tolerance_pct=tolerance_pct)
        return was_above and now_below
    
    return False
