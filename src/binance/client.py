import asyncio
import aiohttp
import hashlib
import hmac
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
import pytz
from src.utils.config import config
from src.utils.logger import logger
from src.utils.rate_limiter import RateLimiter


class BinanceClient:
    BASE_URL = "https://fapi.binance.com"
    TESTNET_URL = "https://testnet.binancefuture.com"
    
    def __init__(self):
        self.use_testnet = config.get('binance.use_testnet', False)
        self.signals_only_mode = config.get('binance.signals_only_mode', False)
        
        # API ключи опциональны в режиме signals_only
        if self.signals_only_mode:
            self.api_key = None
            self.api_secret = None
            logger.warning("⚠️ Signals-Only Mode: API keys disabled, trading functions unavailable")
        else:
            self.api_key = config.get_secret('binance_api_key')
            self.api_secret = config.get_secret('binance_api_secret')
        
        if self.use_testnet:
            logger.warning("⚠️ Using Binance TESTNET - not real market data!")
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter()
        
        # Кэш для информации о символах (precision)
        self.symbols_info: Dict[str, Dict] = {}
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _generate_signature(self, params: Dict[str, Any]) -> str:
        if not self.api_secret:
            raise Exception("Cannot generate signature: API secret not configured (signals_only_mode enabled)")
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, 
                       signed: bool = False, weight: int = 1) -> Any:
        if params is None:
            params = {}
        
        # Запретить подписанные запросы в signals_only режиме
        if signed and self.signals_only_mode:
            raise Exception(f"Cannot execute signed request '{endpoint}' in signals_only_mode")
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        headers = {'X-MBX-APIKEY': self.api_key} if self.api_key else {}
        base_url = self.TESTNET_URL if self.use_testnet else self.BASE_URL
        url = f"{base_url}{endpoint}"
        
        async def _do_request():
            if not self.session:
                raise Exception("Session not initialized")
            async with self.session.request(method, url, params=params, headers=headers) as response:
                # Извлечь информацию о лимитах из заголовков
                used_weight = response.headers.get('X-MBX-USED-WEIGHT-1M')
                retry_after = response.headers.get('Retry-After')
                
                # Обновить rate limiter реальными данными от Binance
                if used_weight:
                    actual_weight = int(used_weight)
                    await self.rate_limiter.update_from_binance_headers(actual_weight, retry_after)
                
                # Проверить статус ответа
                if response.status == 429 or response.status == 418:
                    if retry_after:
                        raise Exception(f"Rate limit/IP ban (status {response.status}), retry after {retry_after}s")
                    else:
                        raise Exception(f"Rate limit error: {response.status}")
                response.raise_for_status()
                return await response.json()
        
        return await self.rate_limiter.execute_with_backoff(_do_request, weight=weight)
    
    async def get_exchange_info(self) -> Dict:
        return await self._request('GET', '/fapi/v1/exchangeInfo', weight=10)
    
    async def load_symbols_info(self):
        """Загрузить информацию о символах (precision) в кэш (с кешированием в файл)"""
        import json
        import os
        from datetime import datetime, timedelta
        import pytz
        
        cache_file = 'data/exchange_info_cache.json'
        cache_ttl_hours = 1  # Кеш на 1 час
        
        try:
            # Проверить наличие кеша
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r') as f:
                        cache_data = json.load(f)
                        cached_time = datetime.fromisoformat(cache_data['timestamp'])
                        now = datetime.now(pytz.UTC)
                        
                        # Если кеш свежий (< 1 часа), использовать его
                        if now - cached_time < timedelta(hours=cache_ttl_hours):
                            self.symbols_info = cache_data['symbols_info']
                            age_minutes = (now - cached_time).total_seconds() / 60
                            logger.info(
                                f"📦 Loaded precision info from cache for {len(self.symbols_info)} symbols "
                                f"(age: {age_minutes:.1f} min)"
                            )
                            return
                        else:
                            logger.info(f"Cache expired ({(now - cached_time).total_seconds() / 3600:.1f}h old), fetching new data")
                except Exception as e:
                    logger.warning(f"Failed to read cache file: {e}, fetching new data")
            
            # Кеш отсутствует или устарел - делаем запрос к API
            logger.info(f"Fetching exchange info from API (cache: {'not found' if not os.path.exists(cache_file) else 'expired'})")
            info = await self.get_exchange_info()
            
            for symbol_info in info.get('symbols', []):
                symbol = symbol_info['symbol']
                self.symbols_info[symbol] = {
                    'pricePrecision': symbol_info.get('pricePrecision', 2),
                    'quantityPrecision': symbol_info.get('quantityPrecision', 3),
                    'status': symbol_info.get('status'),
                    'contractType': symbol_info.get('contractType')
                }
            
            # Сохранить в кеш
            try:
                os.makedirs('data', exist_ok=True)
                cache_path = os.path.abspath(cache_file)
                with open(cache_file, 'w') as f:
                    json.dump({
                        'timestamp': datetime.now(pytz.UTC).isoformat(),
                        'symbols_info': self.symbols_info
                    }, f, indent=2)
                
                # Проверить что файл создан
                if os.path.exists(cache_file):
                    file_size = os.path.getsize(cache_file) / 1024  # KB
                    logger.info(f"✅ Loaded precision info for {len(self.symbols_info)} symbols (cached to {cache_path}, {file_size:.1f} KB)")
                else:
                    logger.warning(f"⚠️ Cache file not found after write: {cache_path}")
            except Exception as e:
                logger.error(f"Failed to save cache: {e}")
                logger.info(f"✅ Loaded precision info for {len(self.symbols_info)} symbols (cache save failed)")
            
        except Exception as e:
            logger.error(f"Failed to load symbols info: {e}", exc_info=True)
    
    def format_price(self, symbol: str, price: float) -> str:
        """Форматировать цену согласно precision символа"""
        if symbol not in self.symbols_info:
            # Если нет информации, используем разумное форматирование
            return f"{price:.8f}".rstrip('0').rstrip('.')
        
        precision = self.symbols_info[symbol]['pricePrecision']
        return f"{price:.{precision}f}"
    
    async def get_futures_pairs(self) -> List[str]:
        info = await self.get_exchange_info()
        pairs = []
        for symbol_info in info.get('symbols', []):
            if (symbol_info.get('status') == 'TRADING' and 
                symbol_info.get('quoteAsset') == 'USDT' and
                symbol_info.get('contractType') == 'PERPETUAL'):
                pairs.append(symbol_info['symbol'])
        
        logger.info(f"Found {len(pairs)} USDT-M perpetual futures pairs")
        return pairs
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 500,
                         start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[List]:
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        # Вес зависит от limit (официальная документация Binance):
        # 1-99 = 1, 100-499 = 2, 500-1000 = 5, >1000 = 10
        if limit < 100:
            weight = 1
        elif limit < 500:
            weight = 2
        elif limit <= 1000:
            weight = 5
        else:
            weight = 10
        
        return await self._request('GET', '/fapi/v1/klines', params=params, weight=weight)
    
    async def get_agg_trades(self, symbol: str, limit: int = 500,
                             start_time: Optional[int] = None, end_time: Optional[int] = None,
                             from_id: Optional[int] = None) -> List[Dict]:
        params = {
            'symbol': symbol,
            'limit': limit
        }
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        if from_id:
            params['fromId'] = from_id
        
        return await self._request('GET', '/fapi/v1/aggTrades', params=params, weight=1)
    
    async def get_depth(self, symbol: str, limit: int = 100) -> Dict:
        params = {
            'symbol': symbol,
            'limit': limit
        }
        # Вес согласно официальной документации Binance:
        # 1-100 = 2, 101-500 = 5, 501-1000 = 10, 1001-5000 = 50
        if limit <= 100:
            weight = 2
        elif limit <= 500:
            weight = 5
        elif limit <= 1000:
            weight = 10
        else:
            weight = 50
        
        return await self._request('GET', '/fapi/v1/depth', params=params, weight=weight)
    
    async def get_open_interest(self, symbol: str) -> Dict:
        params = {'symbol': symbol}
        return await self._request('GET', '/fapi/v1/openInterest', params=params, weight=1)
    
    async def get_open_interest_hist(self, symbol: str, period: str = '5m',
                                     limit: int = 30, start_time: Optional[int] = None,
                                     end_time: Optional[int] = None) -> List[Dict]:
        # Open Interest History - это публичный data endpoint
        # Testnet НЕ ПОДДЕРЖИВАЕТ этот endpoint
        if self.use_testnet:
            logger.debug(f"OI History not available on testnet for {symbol}, returning empty data")
            return []
        
        params = {
            'symbol': symbol,
            'period': period,
            'limit': limit
        }
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        # Для OI History используем специальный URL (не FAPI endpoint)
        # Этот endpoint работает только на production
        oi_url = f"https://fapi.binance.com/futures/data/openInterestHist"
        
        async def _do_request():
            if not self.session:
                raise Exception("Session not initialized")
            try:
                async with self.session.request('GET', oi_url, params=params) as response:
                    if response.status == 429 or response.status == 418:
                        logger.warning(f"⚠️ OI History rate limit {response.status} for {symbol}")
                        raise Exception(f"Rate limit error: {response.status}")
                    if response.status != 200:
                        logger.error(f"❌ OI History failed {response.status} for {symbol}: {await response.text()}")
                    response.raise_for_status()
                    data = await response.json()
                    logger.debug(f"✅ OI History OK for {symbol}: {len(data) if data else 0} records")
                    return data
            except Exception as e:
                logger.error(f"❌ OI History request failed for {symbol}: {e}")
                raise
        
        return await self.rate_limiter.execute_with_backoff(_do_request, weight=1)
    
    async def get_funding_rate(self, symbol: str, limit: int = 100) -> List[Dict]:
        params = {
            'symbol': symbol,
            'limit': limit
        }
        return await self._request('GET', '/fapi/v1/fundingRate', params=params, weight=1)
    
    async def get_24h_ticker(self, symbol: Optional[str] = None) -> Dict | List[Dict]:
        params = {}
        if symbol:
            params['symbol'] = symbol
        # Вес: 1 для одного символа, 40 для всех символов
        weight = 1 if symbol else 40
        return await self._request('GET', '/fapi/v1/ticker/24hr', params=params, weight=weight)
    
    async def get_mark_price(self, symbol: str) -> Dict:
        """Получить текущую mark price для символа"""
        params = {'symbol': symbol}
        return await self._request('GET', '/fapi/v1/premiumIndex', params=params, weight=1)
    
    def get_rate_limit_status(self) -> Dict:
        return self.rate_limiter.get_current_usage()
    
    async def get_symbol_age_days(self, symbol: str) -> int:
        """Определить возраст монеты по первой доступной свече
        
        Args:
            symbol: Символ для проверки
        
        Returns:
            int: Количество дней с момента листинга, 0 если ошибка
        """
        try:
            # Получить первую свечу (1d таймфрейм для точности)
            # startTime=0 означает "с самого начала"
            klines = await self.get_klines(
                symbol=symbol,
                interval='1d',
                limit=1,
                start_time=0  # С самого начала истории
            )
            
            if klines and len(klines) > 0:
                # Первая свеча = klines[0][0] (timestamp в ms)
                first_candle_ts = int(klines[0][0])
                first_candle_time = datetime.fromtimestamp(first_candle_ts / 1000, tz=pytz.UTC)
                now = datetime.now(pytz.UTC)
                age_delta = now - first_candle_time
                return age_delta.days
            
            return 0
        except Exception as e:
            logger.debug(f"Failed to get age for {symbol}: {e}")
            return 0
