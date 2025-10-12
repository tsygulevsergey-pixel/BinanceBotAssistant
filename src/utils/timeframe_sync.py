"""
Smart Timeframe Synchronization - обновляет данные только когда свеча закрылась
"""
from datetime import datetime
import pytz
from typing import Dict


class TimeframeSync:
    """Менеджер умной синхронизации данных по таймфреймам"""
    
    # Кэш последнего обновления для каждого таймфрейма
    _last_update: Dict[str, datetime] = {}
    
    @staticmethod
    def should_update_timeframe(timeframe: str, current_time: datetime = None, consumer_id: str = 'default') -> bool:
        """
        Проверить нужно ли обновлять данные для таймфрейма
        
        Args:
            timeframe: Таймфрейм ('15m', '1h', '4h', '1d')
            current_time: Текущее время (UTC), если None - берется сейчас
            consumer_id: Идентификатор потребителя (для независимого кэша)
            
        Returns:
            True если свеча закрылась и нужно обновить данные
        """
        if current_time is None:
            current_time = datetime.now(pytz.UTC)
        
        minute = current_time.minute
        hour = current_time.hour
        second = current_time.second
        
        # Определяем закрылась ли свеча (проверяем первые 90 секунд после закрытия)
        if timeframe == '15m':
            # 15m свечи закрываются в :00, :15, :30, :45 - проверяем в течение 90 сек после
            should_update = minute % 15 == 0 and second < 90
            
        elif timeframe == '1h':
            # 1h свечи закрываются в :00 каждого часа - проверяем в течение 90 сек после
            should_update = minute == 0 and second < 90
            
        elif timeframe == '4h':
            # 4h свечи закрываются в 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
            should_update = minute == 0 and hour % 4 == 0 and second < 90
            
        elif timeframe == '1d':
            # 1d свечи закрываются в 00:00 UTC
            should_update = minute == 0 and hour == 0 and second < 90
            
        else:
            # Неизвестный таймфрейм - всегда обновляем
            should_update = True
        
        if not should_update:
            return False
        
        # Проверяем кэш - если уже обновляли в эту минуту в последние 90 секунд, скипаем
        cache_key = f"{consumer_id}_{timeframe}_{current_time.strftime('%Y%m%d%H%M')}"
        if cache_key in TimeframeSync._last_update:
            last_update = TimeframeSync._last_update[cache_key]
            # Если обновляли менее 90 секунд назад - пропускаем
            if (current_time - last_update).total_seconds() < 90:
                return False
        
        # Сохраняем время обновления в кэш
        TimeframeSync._last_update[cache_key] = current_time
        
        # Очищаем старые записи (оставляем только последние 100)
        if len(TimeframeSync._last_update) > 100:
            oldest_keys = sorted(TimeframeSync._last_update.keys())[:50]
            for key in oldest_keys:
                TimeframeSync._last_update.pop(key, None)
        
        return True
    
    @staticmethod
    def get_next_update_time(timeframe: str, current_time: datetime = None) -> datetime:
        """
        Получить время следующего обновления для таймфрейма
        
        Args:
            timeframe: Таймфрейм ('15m', '1h', '4h', '1d')
            current_time: Текущее время (UTC)
            
        Returns:
            Время следующего закрытия свечи
        """
        if current_time is None:
            current_time = datetime.now(pytz.UTC)
        
        minute = current_time.minute
        hour = current_time.hour
        
        if timeframe == '15m':
            # Следующее: 00, 15, 30, 45
            next_minute = ((minute // 15) + 1) * 15
            if next_minute >= 60:
                next_time = current_time.replace(hour=hour+1 if hour < 23 else 0, minute=0, second=0, microsecond=0)
            else:
                next_time = current_time.replace(minute=next_minute, second=0, microsecond=0)
                
        elif timeframe == '1h':
            # Следующий час
            next_time = current_time.replace(hour=hour+1 if hour < 23 else 0, minute=0, second=0, microsecond=0)
            
        elif timeframe == '4h':
            # Следующее: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
            next_hour = ((hour // 4) + 1) * 4
            if next_hour >= 24:
                next_hour = 0
            next_time = current_time.replace(hour=next_hour, minute=0, second=0, microsecond=0)
            
        elif timeframe == '1d':
            # Следующий день в 00:00
            next_time = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            from datetime import timedelta
            next_time = next_time + timedelta(days=1)
        
        else:
            # По умолчанию - через час
            next_time = current_time.replace(hour=hour+1 if hour < 23 else 0, minute=0, second=0, microsecond=0)
        
        return next_time
    
    @staticmethod
    def clear_cache():
        """Очистить кэш обновлений"""
        TimeframeSync._last_update.clear()
