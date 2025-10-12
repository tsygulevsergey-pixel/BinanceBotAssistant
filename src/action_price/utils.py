"""
Утилиты для Action Price Strategy
"""
import numpy as np
import pandas as pd
from typing import Tuple, Optional


def calculate_mtr(df: pd.DataFrame, period: int = 20) -> float:
    """
    Рассчитать median True Range (mTR) - медиана диапазонов свечей
    
    Args:
        df: DataFrame с OHLC данными
        period: Период для расчёта (по умолчанию 20)
        
    Returns:
        Медиана True Range
    """
    if len(df) < period:
        return 0.0
    
    # True Range = high - low для каждой свечи
    ranges = df['high'].iloc[-period:] - df['low'].iloc[-period:]
    
    return float(np.median(ranges))


def calculate_zone_width(mtr: float, price: float, 
                         width_mult: float = 0.5, 
                         min_pct: float = 0.15) -> float:
    """
    Рассчитать ширину зоны S/R
    
    Args:
        mtr: median True Range
        price: Текущая цена
        width_mult: Множитель для mTR (по умолчанию 0.5)
        min_pct: Минимум процент от цены (по умолчанию 0.15%)
        
    Returns:
        Ширина зоны
    """
    mtr_width = width_mult * mtr
    pct_width = (min_pct / 100.0) * price
    
    return max(mtr_width, pct_width)


def calculate_buffer(mtr: float, price: float,
                     buffer_mult: float = 0.25,
                     min_pct: float = 0.05) -> float:
    """
    Рассчитать buffer для стопов и зон
    
    Args:
        mtr: median True Range
        price: Текущая цена
        buffer_mult: Множитель для mTR (по умолчанию 0.25)
        min_pct: Минимум процент от цены (по умолчанию 0.05%)
        
    Returns:
        Размер буфера
    """
    mtr_buffer = buffer_mult * mtr
    pct_buffer = (min_pct / 100.0) * price
    
    return max(mtr_buffer, pct_buffer)


def get_eps(price: float, eps_mult: float = 0.0001) -> float:
    """
    Получить epsilon для сравнения цен
    
    Args:
        price: Текущая цена
        eps_mult: Множитель (по умолчанию 0.0001)
        
    Returns:
        Epsilon для сравнений
    """
    return eps_mult * price


def is_price_in_zone(price: float, zone_low: float, zone_high: float) -> bool:
    """
    Проверить находится ли цена в зоне
    
    Args:
        price: Цена для проверки
        zone_low: Нижняя граница зоны
        zone_high: Верхняя граница зоны
        
    Returns:
        True если цена в зоне
    """
    return zone_low <= price <= zone_high


def calculate_rr_ratio(entry: float, stop: float, target: float) -> float:
    """
    Рассчитать соотношение риск/прибыль (R:R)
    
    Args:
        entry: Цена входа
        stop: Стоп-лосс
        target: Тейк-профит
        
    Returns:
        R:R соотношение
    """
    risk = abs(entry - stop)
    if risk == 0:
        return 0.0
    
    reward = abs(target - entry)
    return reward / risk


def merge_overlapping_zones(zones: list, merge_distance: float) -> list:
    """
    Объединить пересекающиеся зоны
    
    Args:
        zones: Список зон [{low, high, score, ...}]
        merge_distance: Расстояние для слияния
        
    Returns:
        Список объединённых зон
    """
    if not zones:
        return []
    
    # Сортировка по нижней границе
    sorted_zones = sorted(zones, key=lambda z: z['low'])
    merged = []
    
    current = sorted_zones[0].copy()
    
    for next_zone in sorted_zones[1:]:
        current_center = (current['low'] + current['high']) / 2
        next_center = (next_zone['low'] + next_zone['high']) / 2
        
        # Если центры близко - объединяем
        if abs(next_center - current_center) < merge_distance:
            # Расширяем границы
            current['low'] = min(current['low'], next_zone['low'])
            current['high'] = max(current['high'], next_zone['high'])
            # Берём лучший score
            current['score'] = max(current.get('score', 0), next_zone.get('score', 0))
            # Объединяем touches
            current['touches'] = current.get('touches', 0) + next_zone.get('touches', 0)
        else:
            # Сохраняем текущую и переходим к следующей
            merged.append(current)
            current = next_zone.copy()
    
    # Добавляем последнюю
    merged.append(current)
    
    return merged


def filter_top_zones(zones: list, current_price: float, top_n: int = 6) -> list:
    """
    Оставить топ-N ближайших зон к цене
    
    Args:
        zones: Список зон
        current_price: Текущая цена
        top_n: Количество зон для оставления
        
    Returns:
        Топ-N зон
    """
    if not zones:
        return []
    
    # Рассчитываем расстояние до цены для каждой зоны
    for zone in zones:
        zone_center = (zone['low'] + zone['high']) / 2
        zone['distance'] = abs(current_price - zone_center)
    
    # Сортируем по score (убывание) и distance (возрастание)
    sorted_zones = sorted(zones, 
                         key=lambda z: (-z.get('score', 0), z.get('distance', float('inf'))))
    
    return sorted_zones[:top_n]


def is_zone_broken(df: pd.DataFrame, zone_low: float, zone_high: float, 
                   zone_type: str, broken_closes: int = 3) -> bool:
    """
    Проверить сломана ли зона (N подряд закрытий за границей)
    
    Args:
        df: DataFrame со свечами
        zone_low: Нижняя граница зоны
        zone_high: Верхняя граница зоны
        zone_type: Тип зоны ('demand' или 'supply')
        broken_closes: Количество закрытий для слома (по умолчанию 3)
        
    Returns:
        True если зона сломана
    """
    if len(df) < broken_closes:
        return False
    
    recent_closes = df['close'].iloc[-broken_closes:]
    
    if zone_type == 'demand':
        # Demand зона ломается если N закрытий ниже low
        return all(close < zone_low for close in recent_closes)
    elif zone_type == 'supply':
        # Supply зона ломается если N закрытий выше high
        return all(close > zone_high for close in recent_closes)
    
    return False
