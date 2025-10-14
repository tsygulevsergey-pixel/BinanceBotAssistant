import asyncio
import time
from collections import deque
from typing import Dict, Optional, Any
from src.utils.logger import logger
from src.utils.config import config


class RateLimiter:
    def __init__(self, weight_limit: Optional[int] = None, window_seconds: int = 60, safety_threshold: float = 0.75):
        self.weight_limit = weight_limit or config.get('binance.rest_weight_limit', 1100)
        self.window_seconds = window_seconds
        self.safety_threshold = safety_threshold  # 75% порог безопасности (было 90% - слишком опасно для burst catchup!)
        self.safe_limit = int(self.weight_limit * safety_threshold)  # 1800 для 2400 (или 825 для 1100)
        self.requests = deque()
        self.current_weight = 0  # Реальный вес от Binance
        self.pending_weight = 0  # Вес запросов в полёте (до получения ответа от Binance)
        self.lock = asyncio.Lock()
        self.backoff_base = config.get('binance.rate_limit_backoff_base', 2)
        self.max_retries = config.get('binance.rate_limit_max_retries', 5)
        
        # IP ban tracking
        self.ip_ban_until: Optional[float] = None  # Timestamp когда IP бан снимется
        
        # Warning debounce (показывать warning максимум раз в 60 секунд)
        self.last_threshold_warning_time: float = 0
    
    async def acquire(self, weight: int = 1) -> bool:
        while True:
            async with self.lock:
                now = time.time()
                
                # Проверить IP ban
                if self.ip_ban_until and now < self.ip_ban_until:
                    wait_time = self.ip_ban_until - now
                    logger.warning(
                        f"🚫 IP BAN active, waiting {wait_time:.0f}s before next request "
                        f"(unbanned at {time.strftime('%H:%M:%S', time.localtime(self.ip_ban_until))})"
                    )
                    await asyncio.sleep(wait_time)
                    self.ip_ban_until = None  # Сбросить после ожидания
                    continue
                
                # Очистить устаревшие запросы
                while self.requests and self.requests[0][0] < now - self.window_seconds:
                    self.requests.popleft()
                
                # Проверка: current (от Binance) + pending (в полёте) + новый weight
                total_weight = self.current_weight + self.pending_weight + weight
                
                if total_weight > self.safe_limit:
                    # Найти время до сброса (используем окно 60 сек)
                    wait_time = 60 - (now % 60) + 1  # Ждём до следующей минуты
                    percent = (total_weight / self.weight_limit) * 100
                    
                    # Debounce: показывать warning максимум раз в 60 секунд
                    if now - self.last_threshold_warning_time >= 60:
                        logger.warning(
                            f"⚠️ Rate limit threshold reached ({percent:.1f}% of limit), "
                            f"pausing for {wait_time:.1f}s (current: {self.current_weight}+{self.pending_weight}/{self.safe_limit})"
                        )
                        self.last_threshold_warning_time = now
                    
                    # КРИТИЧНО: Ждем сброса лимита ВНУТРИ цикла
                    # Освобождаем lock перед сном
                else:
                    # Резервируем вес (будет освобождён при получении ответа от Binance)
                    self.pending_weight += weight
                    self.requests.append((now, weight))
                    return True
            
            # Ждем сброса лимита (wait_time установлен в if блоке выше)
            await asyncio.sleep(wait_time)
            
            # КРИТИЧЕСКИ ВАЖНО: После ожидания принудительно сбросить счетчики
            # т.к. Binance уже сбросил свои, но мы не получим обновление пока не сделаем запрос
            async with self.lock:
                self.current_weight = 0
                self.pending_weight = 0
                self.requests.clear()
                logger.info(f"✅ Rate limit window reset, counters cleared")
    
    async def execute_with_backoff(self, func, *args, weight: int = 1, **kwargs):
        acquired = False
        try:
            for attempt in range(self.max_retries):
                try:
                    if not acquired:
                        await self.acquire(weight)
                        acquired = True
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_str = str(e)
                    
                    # КРИТИЧНО: Если IP BAN обнаружен - НЕ РЕТРАИТЬ!
                    # acquire() уже установил ip_ban_until и будет автоматически ждать
                    if '418' in error_str:
                        logger.warning(
                            f"🚫 IP BAN detected in request, stopping retries. "
                            f"Next acquire() will wait until ban expires."
                        )
                        # Освободить acquired флаг чтобы следующий запрос вызвал acquire()
                        if acquired:
                            async with self.lock:
                                self.pending_weight = max(0, self.pending_weight - weight)
                            acquired = False
                        raise  # Прокинуть exception наверх, не ретраить
                    
                    # 429 (обычный rate limit) - делаем backoff retry
                    if '429' in error_str:
                        wait_time = (self.backoff_base ** attempt) + (time.time() % 1)
                        logger.warning(
                            f"Rate limit 429 (attempt {attempt + 1}/{self.max_retries}), "
                            f"backing off for {wait_time:.2f}s"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        raise
            
            raise Exception(f"Max retries ({self.max_retries}) exceeded for rate limited request")
        except:
            # Если запрос не удался и update_from_binance() не был вызван,
            # освобождаем pending weight чтобы избежать постоянной блокировки
            if acquired:
                async with self.lock:
                    self.pending_weight = max(0, self.pending_weight - weight)
            raise
    
    async def update_from_binance_headers(self, actual_weight: int, retry_after: Optional[str] = None):
        """
        Обновить rate limiter реальными данными из заголовков Binance
        
        Args:
            actual_weight: Реальный вес из заголовка X-MBX-USED-WEIGHT-1M
            retry_after: Время ожидания из заголовка Retry-After (при бане)
        """
        async with self.lock:  # ← THREAD-SAFE обновление
            # Логировать только значительные изменения
            if actual_weight != self.current_weight:
                diff = actual_weight - self.current_weight
                if abs(diff) > 50:  # Логировать только при большом расхождении
                    logger.info(
                        f"📊 Rate limiter sync: local={self.current_weight}+{self.pending_weight}, "
                        f"binance={actual_weight} (diff: {diff:+d})"
                    )
            
            # Вычислить сколько веса реально добавилось (от Binance)
            # При сбросе счётчика Binance (новая минута) diff может быть отрицательным
            weight_added = max(0, actual_weight - self.current_weight)
            
            # ВСЕГДА синхронизировать с Binance (единственный источник правды)
            self.current_weight = actual_weight
            
            # Освободить pending weight на величину добавленного веса
            # Это учитывает что ответ пришёл от ОДНОГО запроса, остальные ещё в полёте
            self.pending_weight = max(0, self.pending_weight - weight_added)
            
            # Если Binance сбросил счётчик (новая минута) - сбросить pending
            if actual_weight < self.pending_weight:
                self.pending_weight = 0
            
            # Очистить локальную историю
            self.requests.clear()
        
        # Если есть Retry-After - значит IP бан или временная блокировка
        if retry_after:
            wait_seconds = int(retry_after)
            self.ip_ban_until = time.time() + wait_seconds
            unban_time = time.strftime('%H:%M:%S', time.localtime(self.ip_ban_until))
            logger.error(
                f"🚨 BINANCE IP BAN detected! All requests blocked until {unban_time} ({wait_seconds}s)"
            )
    
    def get_current_usage(self) -> Dict[str, Any]:
        # current_weight обновляется от Binance, не вычитаем здесь
        return {
            'current_weight': self.current_weight,
            'safe_limit': self.safe_limit,
            'hard_limit': self.weight_limit,
            'percent_used': (self.current_weight / self.weight_limit) * 100,
            'percent_of_safe': (self.current_weight / self.safe_limit) * 100 if self.safe_limit > 0 else 0,
            'is_near_limit': self.current_weight >= self.safe_limit
        }
    
    async def wait_if_near_limit(self, weight: int = 1) -> None:
        """Подождать если близко к лимиту (для batch операций)"""
        should_wait = False
        wait_time = 0
        
        async with self.lock:
            now = time.time()
            
            # Очистить устаревшие запросы (только для очистки deque)
            while self.requests and self.requests[0][0] < now - self.window_seconds:
                self.requests.popleft()
            
            # Проверка: current + pending + новый weight
            total_weight = self.current_weight + self.pending_weight + weight
            
            if total_weight > self.safe_limit:
                should_wait = True
                wait_time = 60 - (now % 60) + 1  # Ждём до следующей минуты
                percent = (total_weight / self.weight_limit) * 100
                logger.info(
                    f"🛑 Batch operation paused at {percent:.1f}% limit "
                    f"({self.current_weight}+{self.pending_weight}/{self.safe_limit}), waiting {wait_time:.1f}s for reset"
                )
        
        # Ждем ВНЕ lock
        if should_wait:
            await asyncio.sleep(wait_time)
            
            # КРИТИЧЕСКИ ВАЖНО: После ожидания принудительно сбросить счетчики
            async with self.lock:
                self.current_weight = 0
                self.pending_weight = 0
                self.requests.clear()
                logger.info(f"✅ Batch rate limit window reset, counters cleared")
