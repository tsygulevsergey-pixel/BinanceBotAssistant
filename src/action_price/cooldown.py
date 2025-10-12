"""
Cooldown система для предотвращения дубликатов сигналов Action Price
"""
from datetime import datetime, timedelta
from typing import Dict, Optional
import hashlib


class ActionPriceCooldown:
    """Анти-дубликаты для Action Price сигналов"""
    
    def __init__(self, config: dict):
        """
        Args:
            config: Конфигурация из config.yaml['action_price']['cooldown']
        """
        self.config = config
        self.cooldown_1h = config.get('timeframe_1h', 6)  # часов
        self.cooldown_15m = config.get('timeframe_15m', 2)  # часов
        self.unique_key_fields = config.get('unique_key', 
            ['symbol', 'direction', 'zone_id', 'pattern', 'timeframe'])
        
        # Кэш недавних сигналов
        self.recent_signals = {}  # {hash: timestamp}
    
    def generate_signal_hash(self, symbol: str, direction: str, 
                            zone_id: str, pattern_type: str, 
                            timeframe: str) -> str:
        """
        Генерировать уникальный хеш для сигнала
        
        Args:
            symbol: Символ
            direction: LONG/SHORT
            zone_id: ID зоны
            pattern_type: Тип паттерна
            timeframe: Таймфрейм
            
        Returns:
            MD5 хеш
        """
        key_string = f"{symbol}_{direction}_{zone_id}_{pattern_type}_{timeframe}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def is_duplicate(self, symbol: str, direction: str, zone_id: str,
                     pattern_type: str, timeframe: str, 
                     current_time: datetime) -> bool:
        """
        Проверить является ли сигнал дубликатом
        
        Args:
            symbol: Символ
            direction: LONG/SHORT
            zone_id: ID зоны
            pattern_type: Тип паттерна
            timeframe: Таймфрейм ('15m' или '1h')
            current_time: Текущее время
            
        Returns:
            True если дубликат
        """
        signal_hash = self.generate_signal_hash(symbol, direction, zone_id, 
                                                pattern_type, timeframe)
        
        # Определяем TTL
        cooldown_hours = self.cooldown_1h if timeframe == '1h' else self.cooldown_15m
        ttl = timedelta(hours=cooldown_hours)
        
        # Проверяем кэш
        if signal_hash in self.recent_signals:
            last_time = self.recent_signals[signal_hash]
            if current_time - last_time < ttl:
                return True  # Дубликат - слишком рано
        
        # Сохраняем новый сигнал
        self.recent_signals[signal_hash] = current_time
        
        # Очистка старых записей
        self.cleanup_old_signals(current_time)
        
        return False
    
    def cleanup_old_signals(self, current_time: datetime):
        """
        Очистить устаревшие записи из кэша
        
        Args:
            current_time: Текущее время
        """
        max_ttl = timedelta(hours=max(self.cooldown_1h, self.cooldown_15m))
        
        to_remove = []
        for signal_hash, timestamp in self.recent_signals.items():
            if current_time - timestamp > max_ttl:
                to_remove.append(signal_hash)
        
        for signal_hash in to_remove:
            del self.recent_signals[signal_hash]
    
    def register_signal(self, symbol: str, direction: str, zone_id: str,
                       pattern_type: str, timeframe: str, 
                       current_time: datetime):
        """
        Зарегистрировать новый сигнал в cooldown
        
        Args:
            symbol: Символ
            direction: LONG/SHORT
            zone_id: ID зоны
            pattern_type: Тип паттерна
            timeframe: Таймфрейм
            current_time: Текущее время
        """
        signal_hash = self.generate_signal_hash(symbol, direction, zone_id,
                                                pattern_type, timeframe)
        self.recent_signals[signal_hash] = current_time
