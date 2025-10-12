"""
Утилита для расчета простых зон поддержки/сопротивления.
Используется в основных стратегиях для размещения стоп-лоссов.
Работает с любым таймфреймом.
"""
import pandas as pd
from typing import Optional, Dict, List


def find_swing_highs_lows(df: pd.DataFrame, lookback: int = 20, k: int = 2) -> Dict[str, List[float]]:
    """
    Найти swing highs/lows используя простую fractal логику
    
    Args:
        df: DataFrame с OHLC данными
        lookback: Сколько баров назад смотреть (по умолчанию 20)
        k: Количество баров вокруг для fractal проверки (по умолчанию 2)
    
    Returns:
        {'highs': [...], 'lows': [...]} - списки swing уровней
    """
    if len(df) < lookback + k * 2:
        return {'highs': [], 'lows': []}
    
    # Берем только последние N баров для скорости
    recent_df = df.tail(lookback + k * 2).reset_index(drop=True)
    
    highs = []
    lows = []
    
    for i in range(k, len(recent_df) - k):
        # Swing High: high[i] выше всех соседних high
        is_swing_high = True
        for j in range(i - k, i + k + 1):
            if j == i:
                continue
            if recent_df['high'].iloc[i] <= recent_df['high'].iloc[j]:
                is_swing_high = False
                break
        
        if is_swing_high:
            highs.append(recent_df['high'].iloc[i])
        
        # Swing Low: low[i] ниже всех соседних low
        is_swing_low = True
        for j in range(i - k, i + k + 1):
            if j == i:
                continue
            if recent_df['low'].iloc[i] >= recent_df['low'].iloc[j]:
                is_swing_low = False
                break
        
        if is_swing_low:
            lows.append(recent_df['low'].iloc[i])
    
    return {'highs': highs, 'lows': lows}


def create_sr_zones(df: pd.DataFrame, atr: float, buffer_mult: float = 0.25) -> Dict[str, List[Dict]]:
    """
    Создать зоны поддержки/сопротивления с буфером
    
    Args:
        df: DataFrame с OHLC данными
        atr: Текущий ATR
        buffer_mult: Множитель ATR для буфера зоны (по умолчанию 0.25)
    
    Returns:
        {'resistance': [...], 'support': [...]} - списки зон с границами
    """
    swings = find_swing_highs_lows(df, lookback=20, k=2)
    
    resistance_zones = []
    support_zones = []
    
    buffer = buffer_mult * atr
    
    # Создать зоны сопротивления из swing highs
    for high in swings['highs']:
        resistance_zones.append({
            'level': high,
            'upper': high + buffer,
            'lower': high - buffer,
            'type': 'resistance'
        })
    
    # Создать зоны поддержки из swing lows
    for low in swings['lows']:
        support_zones.append({
            'level': low,
            'upper': low + buffer,
            'lower': low - buffer,
            'type': 'support'
        })
    
    return {
        'resistance': resistance_zones,
        'support': support_zones
    }


def find_nearest_zone(current_price: float, zones: Dict[str, List[Dict]], 
                      direction: str) -> Optional[Dict]:
    """
    Найти ближайшую зону поддержки/сопротивления для размещения стопа
    
    Args:
        current_price: Текущая цена
        zones: Словарь зон {'resistance': [...], 'support': [...]}
        direction: 'LONG' или 'SHORT' - направление сделки
    
    Returns:
        Ближайшая зона или None если не найдена
    """
    if direction == 'LONG':
        # Для LONG: ищем ближайшую зону ПОДДЕРЖКИ НИЖЕ цены
        support_zones = zones.get('support', [])
        
        # Фильтруем зоны ниже текущей цены
        zones_below = [z for z in support_zones if z['upper'] < current_price]
        
        if not zones_below:
            return None
        
        # Берем ближайшую (максимальный уровень среди зон ниже)
        nearest = max(zones_below, key=lambda z: z['level'])
        return nearest
    
    elif direction == 'SHORT':
        # Для SHORT: ищем ближайшую зону СОПРОТИВЛЕНИЯ ВЫШЕ цены
        resistance_zones = zones.get('resistance', [])
        
        # Фильтруем зоны выше текущей цены
        zones_above = [z for z in resistance_zones if z['lower'] > current_price]
        
        if not zones_above:
            return None
        
        # Берем ближайшую (минимальный уровень среди зон выше)
        nearest = min(zones_above, key=lambda z: z['level'])
        return nearest
    
    return None


def calculate_stop_loss_from_zone(entry_price: float, nearest_zone: Optional[Dict], 
                                   current_atr: float, direction: str,
                                   fallback_mult: float = 2.0,
                                   max_distance_atr: float = 5.0) -> float:
    """
    Рассчитать стоп-лосс за ближайшей зоной S/R с проверкой максимальной дистанции
    
    Args:
        entry_price: Цена входа
        nearest_zone: Ближайшая зона или None
        current_atr: Текущий ATR
        direction: 'LONG' или 'SHORT'
        fallback_mult: Множитель ATR для fallback стопа если зона не найдена
        max_distance_atr: Максимальная дистанция до зоны в ATR (по умолчанию 5.0)
    
    Returns:
        Уровень стоп-лосса
    """
    # Проверка: если зона найдена, но слишком далеко (>5 ATR) - игнорируем её
    if nearest_zone:
        zone_distance = abs(entry_price - nearest_zone['level'])
        max_distance = max_distance_atr * current_atr
        
        if zone_distance > max_distance:
            # Зона слишком далеко (резкий импульс) → используем Fallback
            nearest_zone = None
    
    if nearest_zone:
        if direction == 'LONG':
            # Стоп за нижней границей зоны поддержки
            stop_loss = nearest_zone['lower'] - 0.1 * current_atr
        else:  # SHORT
            # Стоп за верхней границей зоны сопротивления
            stop_loss = nearest_zone['upper'] + 0.1 * current_atr
    else:
        # Fallback: если зона не найдена или слишком далеко, используем простую логику
        if direction == 'LONG':
            stop_loss = entry_price - fallback_mult * current_atr
        else:  # SHORT
            stop_loss = entry_price + fallback_mult * current_atr
    
    return stop_loss
