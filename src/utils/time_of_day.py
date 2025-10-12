"""
Утилиты для определения времени суток и адаптации параметров
"""
from datetime import time
import pandas as pd


def get_session_type(timestamp: pd.Timestamp) -> str:
    """
    Определить тип торговой сессии на основе времени UTC
    
    Args:
        timestamp: Временная метка (UTC)
    
    Returns:
        'night' - низкая активность (00:00-08:00 UTC)
        'day' - высокая активность (08:00-20:00 UTC)
        'evening' - средняя активность (20:00-00:00 UTC)
    """
    current_time = timestamp.time()
    
    # Ночная сессия (низкая ликвидность): 00:00 - 08:00 UTC
    if time(0, 0) <= current_time < time(8, 0):
        return 'night'
    
    # Вечерняя сессия (средняя ликвидность): 20:00 - 00:00 UTC
    elif time(20, 0) <= current_time or current_time < time(0, 0):
        return 'evening'
    
    # Дневная сессия (высокая ликвидность): 08:00 - 20:00 UTC
    else:
        return 'day'


def get_adaptive_volume_threshold(timestamp: pd.Timestamp, base_threshold: float = 1.5) -> float:
    """
    Получить адаптивный порог объема на основе времени суток
    
    Args:
        timestamp: Временная метка (UTC)
        base_threshold: Базовый порог для дневной сессии
    
    Returns:
        Адаптированный порог объема
    """
    session = get_session_type(timestamp)
    
    if session == 'night':
        # Ночью объемы ниже - снижаем порог на 40%
        return base_threshold * 0.6
    elif session == 'evening':
        # Вечером объемы средние - снижаем порог на 20%
        return base_threshold * 0.8
    else:
        # День - используем базовый порог
        return base_threshold


def is_high_liquidity_period(timestamp: pd.Timestamp) -> bool:
    """
    Проверить, является ли текущий период высокой ликвидности
    
    Args:
        timestamp: Временная метка (UTC)
    
    Returns:
        True если высокая ликвидность (EU/US sessions overlap: 13:00-17:00 UTC)
    """
    current_time = timestamp.time()
    
    # Пиковая ликвидность - пересечение EU и US сессий
    return time(13, 0) <= current_time < time(17, 0)
