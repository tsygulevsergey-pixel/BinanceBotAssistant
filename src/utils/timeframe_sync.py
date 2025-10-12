"""
Smart Timeframe Synchronization - обновляет данные только когда свеча закрылась
"""
from datetime import datetime, timedelta
import pytz
from typing import Dict, Optional


class TimeframeSync:
    """Менеджер умной синхронизации данных по таймфреймам"""
    
    # Кэш timestamp последней обработанной свечи для каждого consumer + timeframe
    _last_processed_candle: Dict[str, datetime] = {}
    
    @staticmethod
    def _get_last_closed_candle_time(timeframe: str, current_time: datetime) -> datetime:
        """
        Получить timestamp последней закрытой свечи для таймфрейма
        
        Args:
            timeframe: Таймфрейм ('15m', '1h', '4h', '1d')
            current_time: Текущее время (UTC)
            
        Returns:
            Timestamp последней закрытой свечи (floor к периоду)
        """
        minute = current_time.minute
        hour = current_time.hour
        
        if timeframe == '15m':
            # Округлить до последней 15m границы: :00, :15, :30, :45
            last_minute = (minute // 15) * 15
            return current_time.replace(minute=last_minute, second=0, microsecond=0)
            
        elif timeframe == '1h':
            # Округлить до последней часовой границы
            return current_time.replace(minute=0, second=0, microsecond=0)
            
        elif timeframe == '4h':
            # Округлить до последней 4h границы: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
            last_hour = (hour // 4) * 4
            return current_time.replace(hour=last_hour, minute=0, second=0, microsecond=0)
            
        elif timeframe == '1d':
            # Округлить до последней дневной границы 00:00
            return current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        else:
            # Неизвестный таймфрейм - округляем до часа
            return current_time.replace(minute=0, second=0, microsecond=0)
    
    @staticmethod
    def should_update_timeframe(timeframe: str, current_time: datetime = None, consumer_id: str = 'default') -> bool:
        """
        Проверить нужно ли обновлять данные для таймфрейма
        
        Новая логика: сравниваем timestamp последней закрытой свечи с последней обработанной.
        Это работает даже если проверка опоздала на несколько минут.
        
        Args:
            timeframe: Таймфрейм ('15m', '1h', '4h', '1d')
            current_time: Текущее время (UTC), если None - берется сейчас
            consumer_id: Идентификатор потребителя (для независимого кэша)
            
        Returns:
            True если свеча закрылась и нужно обновить данные
        """
        if current_time is None:
            current_time = datetime.now(pytz.UTC)
        
        # Получить timestamp последней закрытой свечи
        last_closed = TimeframeSync._get_last_closed_candle_time(timeframe, current_time)
        
        # Ключ для кэша
        cache_key = f"{consumer_id}_{timeframe}"
        
        # Получить timestamp последней обработанной свечи
        last_processed = TimeframeSync._last_processed_candle.get(cache_key)
        
        # Если это первый запуск или свеча обновилась
        if last_processed is None or last_closed > last_processed:
            # Дополнительная проверка: свеча должна быть "свежей" (не старше 5 минут от текущего времени)
            # Это предотвращает обработку старых свечей при первом запуске
            time_since_close = (current_time - last_closed).total_seconds()
            
            # Для первого запуска: обрабатываем только если свеча закрылась недавно
            if last_processed is None and time_since_close > 300:  # 5 минут
                # Первый запуск, но свеча старая - пропускаем, но сохраняем в кэш
                TimeframeSync._last_processed_candle[cache_key] = last_closed
                return False
            
            # Обновляем кэш
            TimeframeSync._last_processed_candle[cache_key] = last_closed
            
            # Очищаем старые записи (оставляем только последние 100)
            if len(TimeframeSync._last_processed_candle) > 100:
                oldest_keys = sorted(TimeframeSync._last_processed_candle.keys())[:50]
                for key in oldest_keys:
                    TimeframeSync._last_processed_candle.pop(key, None)
            
            return True
        
        return False
    
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
        
        # Получить последнюю закрытую свечу
        last_closed = TimeframeSync._get_last_closed_candle_time(timeframe, current_time)
        
        # Добавить период таймфрейма
        if timeframe == '15m':
            next_time = last_closed + timedelta(minutes=15)
        elif timeframe == '1h':
            next_time = last_closed + timedelta(hours=1)
        elif timeframe == '4h':
            next_time = last_closed + timedelta(hours=4)
        elif timeframe == '1d':
            next_time = last_closed + timedelta(days=1)
        else:
            next_time = last_closed + timedelta(hours=1)
        
        return next_time
    
    @staticmethod
    def clear_cache():
        """Очистить кэш обновлений"""
        TimeframeSync._last_processed_candle.clear()
