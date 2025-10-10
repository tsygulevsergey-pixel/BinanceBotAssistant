import asyncio
import time
from collections import deque
from typing import Dict, Optional, Any
from src.utils.logger import logger
from src.utils.config import config


class RateLimiter:
    def __init__(self, weight_limit: Optional[int] = None, window_seconds: int = 60):
        self.weight_limit = weight_limit or config.get('binance.rest_weight_limit', 1100)
        self.window_seconds = window_seconds
        self.requests = deque()
        self.current_weight = 0
        self.lock = asyncio.Lock()
        self.backoff_base = config.get('binance.rate_limit_backoff_base', 2)
        self.max_retries = config.get('binance.rate_limit_max_retries', 5)
    
    async def acquire(self, weight: int = 1) -> bool:
        while True:
            async with self.lock:
                now = time.time()
                
                while self.requests and self.requests[0][0] < now - self.window_seconds:
                    _, w = self.requests.popleft()
                    self.current_weight -= w
                
                if self.current_weight + weight > self.weight_limit:
                    wait_time = self.requests[0][0] + self.window_seconds - now if self.requests else 1
                    logger.warning(f"Rate limit approaching, waiting {wait_time:.2f}s (current: {self.current_weight}/{self.weight_limit})")
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
    
    def get_current_usage(self) -> Dict[str, int]:
        now = time.time()
        while self.requests and self.requests[0][0] < now - self.window_seconds:
            _, w = self.requests.popleft()
            self.current_weight -= w
        
        return {
            'current_weight': self.current_weight,
            'limit': self.weight_limit,
            'percent_used': (self.current_weight / self.weight_limit) * 100
        }
