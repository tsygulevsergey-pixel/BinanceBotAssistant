import asyncio
import json
import websockets
from typing import Dict, Callable, Optional, List
from datetime import datetime, timedelta
import pytz
from src.utils.logger import logger
from src.utils.config import config


class BinanceWebSocket:
    WS_BASE_URL = "wss://fstream.binance.com"
    WS_TESTNET_URL = "wss://stream.binancefuture.com"
    
    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.callbacks: Dict[str, List[Callable]] = {}
        self.use_testnet = config.get('binance.use_testnet', False)
        self.reconnect_delay = config.get('binance.ws_reconnect_delay', 5)
        self.last_message_time = datetime.now(pytz.UTC)
        self.stale_threshold = timedelta(
            milliseconds=config.get('websocket.stale_threshold_ms', 500)
        )
    
    def subscribe(self, stream_type: str, callback: Callable):
        if stream_type not in self.callbacks:
            self.callbacks[stream_type] = []
        self.callbacks[stream_type].append(callback)
    
    async def _handle_message(self, message: str):
        try:
            data = json.loads(message)
            self.last_message_time = datetime.now(pytz.UTC)
            
            if 'e' in data:
                event_type = data['e']
                if event_type in self.callbacks:
                    for callback in self.callbacks[event_type]:
                        await callback(data)
            elif 'stream' in data:
                stream_name = data['stream']
                if '@' in stream_name:
                    stream_type = stream_name.split('@')[1]
                    if stream_type in self.callbacks:
                        for callback in self.callbacks[stream_type]:
                            await callback(data['data'])
        
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
    
    async def _connect(self, streams: List[str]):
        stream_names = '/'.join([f"{self.symbol}@{s}" for s in streams])
        base_url = self.WS_TESTNET_URL if self.use_testnet else self.WS_BASE_URL
        url = f"{base_url}/stream?streams={stream_names}"
        
        # КРИТИЧНО: Добавить timeout чтобы избежать бесконечного зависания при подключении
        # Если timeout сработает - Exception будет обработан в start() и произойдёт reconnect
        self.ws = await asyncio.wait_for(
            websockets.connect(url),
            timeout=30
        )
        env = "TESTNET" if self.use_testnet else "PRODUCTION"
        logger.info(f"WebSocket connected [{env}] for {self.symbol} with streams: {streams}")
    
    async def start(self, streams: List[str]):
        self.running = True
        
        while self.running:
            try:
                await self._connect(streams)
                
                async for message in self.ws:
                    await self._handle_message(message)
            
            except websockets.ConnectionClosed:
                logger.warning(f"WebSocket connection closed for {self.symbol}, reconnecting...")
                await asyncio.sleep(self.reconnect_delay)
            
            except Exception as e:
                logger.error(f"WebSocket error for {self.symbol}: {e}")
                await asyncio.sleep(self.reconnect_delay)
    
    async def stop(self):
        self.running = False
        if self.ws:
            await self.ws.close()
    
    def is_stale(self) -> bool:
        return datetime.now(pytz.UTC) - self.last_message_time > self.stale_threshold


class WebSocketManager:
    def __init__(self):
        self.connections: Dict[str, BinanceWebSocket] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
    
    def add_symbol(self, symbol: str, streams: List[str]) -> BinanceWebSocket:
        if symbol in self.connections:
            return self.connections[symbol]
        
        ws = BinanceWebSocket(symbol)
        self.connections[symbol] = ws
        task = asyncio.create_task(ws.start(streams))
        self.tasks[symbol] = task
        
        return ws
    
    async def remove_symbol(self, symbol: str):
        if symbol in self.connections:
            await self.connections[symbol].stop()
            if symbol in self.tasks:
                self.tasks[symbol].cancel()
                del self.tasks[symbol]
            del self.connections[symbol]
    
    async def stop_all(self):
        for symbol in list(self.connections.keys()):
            await self.remove_symbol(symbol)
    
    def get_stale_symbols(self) -> List[str]:
        stale = []
        for symbol, ws in self.connections.items():
            if ws.is_stale():
                stale.append(symbol)
        return stale
