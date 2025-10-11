"""
Система кеширования индикаторов для повышения производительности
"""
from typing import Dict, Optional, Tuple
import pandas as pd
from datetime import datetime


class IndicatorCache:
    """
    Кеш для хранения рассчитанных индикаторов
    Ключ: (symbol, timeframe, last_bar_time)
    Пересчитывается только при появлении нового бара
    """
    
    def __init__(self):
        self._cache: Dict[Tuple[str, str], Dict] = {}
    
    def get(self, symbol: str, timeframe: str, last_bar_time: pd.Timestamp) -> Optional[Dict]:
        """
        Получить закешированные индикаторы
        
        Args:
            symbol: Символ (например, BTCUSDT)
            timeframe: Таймфрейм (например, 1h)
            last_bar_time: Время последнего бара
            
        Returns:
            Dict с индикаторами если кеш актуален, иначе None
        """
        key = (symbol, timeframe)
        cached = self._cache.get(key)
        
        # Если кеша нет - вернуть None
        if not cached:
            return None
        
        # Если время последнего бара изменилось - кеш устарел
        if cached['last_bar_time'] != last_bar_time:
            return None
        
        return cached.get('indicators')
    
    def set(self, symbol: str, timeframe: str, last_bar_time: pd.Timestamp, indicators: Dict):
        """
        Сохранить рассчитанные индикаторы в кеш
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            last_bar_time: Время последнего бара
            indicators: Словарь с рассчитанными индикаторами
        """
        key = (symbol, timeframe)
        self._cache[key] = {
            'last_bar_time': last_bar_time,
            'indicators': indicators
        }
    
    def clear_symbol(self, symbol: str):
        """
        Очистить кеш для конкретного символа (все таймфреймы)
        
        Args:
            symbol: Символ для очистки
        """
        keys_to_delete = [k for k in self._cache.keys() if k[0] == symbol]
        for key in keys_to_delete:
            del self._cache[key]
    
    def clear_all(self):
        """Очистить весь кеш"""
        self._cache.clear()
    
    def get_stats(self) -> Dict:
        """
        Получить статистику по кешу
        
        Returns:
            Dict со статистикой (количество символов, таймфреймов и т.д.)
        """
        symbols = set(k[0] for k in self._cache.keys())
        timeframes = set(k[1] for k in self._cache.keys())
        
        return {
            'total_entries': len(self._cache),
            'symbols_count': len(symbols),
            'timeframes_count': len(timeframes),
            'symbols': list(symbols),
            'timeframes': list(timeframes)
        }
