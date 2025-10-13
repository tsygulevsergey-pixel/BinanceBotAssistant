import asyncio
import time
from collections import deque
from typing import Dict, Optional, Any
from src.utils.logger import logger
from src.utils.config import config


class RateLimiter:
    def __init__(self, weight_limit: Optional[int] = None, window_seconds: int = 60, safety_threshold: float = 0.9):
        self.weight_limit = weight_limit or config.get('binance.rest_weight_limit', 1100)
        self.window_seconds = window_seconds
        self.safety_threshold = safety_threshold  # 90% порог безопасности
        self.safe_limit = int(self.weight_limit * safety_threshold)  # 990 для 1100
        self.requests = deque()
        self.current_weight = 0
        self.lock = asyncio.Lock()
        self.backoff_base = config.get('binance.rate_limit_backoff_base', 2)
        self.max_retries = config.get('binance.rate_limit_max_retries', 5)
    
    async def acquire(self, weight: int = 1) -> bool:
        while True:
            async with self.lock:
                now = time.time()
                
                # Очистить устаревшие запросы
                while self.requests and self.requests[0][0] < now - self.window_seconds:
                    _, w = self.requests.popleft()
                    self.current_weight -= w
                
                # Проверка на 90% порог безопасности
                if self.current_weight + weight > self.safe_limit:
                    # Найти время до сброса самого старого запроса
                    wait_time = self.requests[0][0] + self.window_seconds - now if self.requests else 1
                    percent = ((self.current_weight + weight) / self.weight_limit) * 100
                    logger.warning(
                        f"⚠️ Rate limit threshold reached ({percent:.1f}% of limit), "
                        f"pausing for {wait_time:.1f}s (current: {self.current_weight}/{self.safe_limit})"
                    )
                else:
                    self.requests.append((now, weight))
                    self.current_weight += weight
                    return True
            
            await asyncio.sleep(wait_time)
    
    async def execute_with_backoff(self, func, *args, weight: int = 1, **kwargs):
        for attempt in range(self.max_retries):
            try:
                await self.acquire(weight)
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                if '429' in str(e) or '418' in str(e):
                    wait_time = (self.backoff_base ** attempt) + (time.time() % 1)
                    logger.warning(f"Rate limit hit (attempt {attempt + 1}/{self.max_retries}), backing off for {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                else:
                    raise
        
        raise Exception(f"Max retries ({self.max_retries}) exceeded for rate limited request")
    
    def update_from_binance_headers(self, actual_weight: int, retry_after: Optional[str] = None):
        """
        Обновить rate limiter реальными данными из заголовков Binance
        
        Args:
            actual_weight: Реальный вес из заголовка X-MBX-USED-WEIGHT-1M
            retry_after: Время ожидания из заголовка Retry-After (при бане)
        """
        # Синхронизировать локальный счётчик с реальным от Binance
        if actual_weight != self.current_weight:
            diff = actual_weight - self.current_weight
            if abs(diff) > 10:  # Только если расхождение больше 10
                logger.info(
                    f"📊 Rate limiter sync: local={self.current_weight}, "
                    f"binance={actual_weight} (diff: {diff:+d})"
                )
            self.current_weight = actual_weight
        
        # Если есть Retry-After - значит IP бан или временная блокировка
        if retry_after:
            wait_seconds = int(retry_after)
            logger.error(
                f"🚨 BINANCE IP BAN/BLOCK detected! Must wait {wait_seconds}s before next request"
            )
    
    def get_current_usage(self) -> Dict[str, Any]:
        now = time.time()
        while self.requests and self.requests[0][0] < now - self.window_seconds:
            _, w = self.requests.popleft()
            self.current_weight -= w
        
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
        async with self.lock:
            now = time.time()
            
            # Очистить устаревшие
            while self.requests and self.requests[0][0] < now - self.window_seconds:
                _, w = self.requests.popleft()
                self.current_weight -= w
            
            # Если добавление weight превысит 90%
            if self.current_weight + weight > self.safe_limit:
                wait_time = self.requests[0][0] + self.window_seconds - now if self.requests else 1
                percent = ((self.current_weight + weight) / self.weight_limit) * 100
                logger.info(
                    f"🛑 Batch operation paused at {percent:.1f}% limit "
                    f"({self.current_weight}/{self.safe_limit}), waiting {wait_time:.1f}s for reset"
                )
                await asyncio.sleep(wait_time)
