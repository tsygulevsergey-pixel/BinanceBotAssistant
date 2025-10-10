import asyncio
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import pytz
from collections import OrderedDict
from src.utils.logger import logger
from src.utils.config import config
from src.binance.client import BinanceClient
from src.binance.websocket import BinanceWebSocket


class OrderBook:
    def __init__(self, symbol: str, levels: int = 20):
        self.symbol = symbol
        self.levels = levels
        self.bids: OrderedDict[float, float] = OrderedDict()
        self.asks: OrderedDict[float, float] = OrderedDict()
        self.last_update_id = 0
        self.last_sync_time = None
        self.is_synced = False
        self.sequence_gap_count = 0
        self.max_gap_count = config.get('websocket.stale_warning_count', 3)
    
    async def init_snapshot(self, client: BinanceClient):
        depth = await client.get_depth(self.symbol, limit=self.levels * 2)
        
        self.last_update_id = depth['lastUpdateId']
        
        self.bids.clear()
        for price, qty in depth['bids'][:self.levels]:
            self.bids[float(price)] = float(qty)
        
        self.asks.clear()
        for price, qty in depth['asks'][:self.levels]:
            self.asks[float(price)] = float(qty)
        
        self.is_synced = True
        self.last_sync_time = datetime.now(pytz.UTC)
        logger.info(f"OrderBook snapshot initialized for {self.symbol}, lastUpdateId: {self.last_update_id}")
    
    async def process_update(self, data: Dict):
        if not self.is_synced:
            return
        
        if 'U' in data and 'u' in data:
            first_update_id = data['U']
            last_update_id = data['u']
            
            if last_update_id <= self.last_update_id:
                return
            
            if first_update_id > self.last_update_id + 1:
                self.sequence_gap_count += 1
                logger.warning(
                    f"Sequence gap detected for {self.symbol}: "
                    f"expected {self.last_update_id + 1}, got {first_update_id} "
                    f"(gap count: {self.sequence_gap_count})"
                )
                
                if self.sequence_gap_count >= self.max_gap_count:
                    logger.critical(f"Critical sequence gaps for {self.symbol}, needs resync")
                    self.is_synced = False
                return
            
            self.sequence_gap_count = 0
            
            for price, qty in data.get('b', []):
                price, qty = float(price), float(qty)
                if qty == 0:
                    self.bids.pop(price, None)
                else:
                    self.bids[price] = qty
            
            for price, qty in data.get('a', []):
                price, qty = float(price), float(qty)
                if qty == 0:
                    self.asks.pop(price, None)
                else:
                    self.asks[price] = qty
            
            self._trim_levels()
            
            self.last_update_id = last_update_id
            
            if not self._validate_book():
                logger.error(f"OrderBook validation failed for {self.symbol}")
                self.is_synced = False
    
    def _trim_levels(self):
        if len(self.bids) > self.levels:
            sorted_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)
            self.bids = OrderedDict(sorted_bids[:self.levels])
        
        if len(self.asks) > self.levels:
            sorted_asks = sorted(self.asks.items(), key=lambda x: x[0])
            self.asks = OrderedDict(sorted_asks[:self.levels])
    
    def _validate_book(self) -> bool:
        if not self.bids or not self.asks:
            return True
        
        best_bid = max(self.bids.keys())
        best_ask = min(self.asks.keys())
        
        return best_bid < best_ask
    
    def get_best_bid(self) -> Optional[Tuple[float, float]]:
        if not self.bids:
            return None
        best_price = max(self.bids.keys())
        return (best_price, self.bids[best_price])
    
    def get_best_ask(self) -> Optional[Tuple[float, float]]:
        if not self.asks:
            return None
        best_price = min(self.asks.keys())
        return (best_price, self.asks[best_price])
    
    def get_mid_price(self) -> Optional[float]:
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid and ask:
            return (bid[0] + ask[0]) / 2
        return None
    
    def get_imbalance(self) -> Optional[float]:
        if not self.bids or not self.asks:
            return None
        
        bid_volume = sum(self.bids.values())
        ask_volume = sum(self.asks.values())
        
        if bid_volume + ask_volume == 0:
            return None
        
        return ask_volume / bid_volume if bid_volume > 0 else None
    
    def get_spread(self) -> Optional[float]:
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid and ask:
            return ask[0] - bid[0]
        return None


class OrderBookManager:
    def __init__(self, client: BinanceClient):
        self.client = client
        self.orderbooks: Dict[str, OrderBook] = {}
        self.snapshot_interval = config.get('binance.snapshot_interval', 60)
        self.resync_tasks: Dict[str, asyncio.Task] = {}
    
    async def add_symbol(self, symbol: str, ws: BinanceWebSocket) -> OrderBook:
        levels = config.get('binance.orderbook_levels', 20)
        orderbook = OrderBook(symbol, levels)
        
        await orderbook.init_snapshot(self.client)
        
        ws.subscribe('depthUpdate', orderbook.process_update)
        
        self.orderbooks[symbol] = orderbook
        
        task = asyncio.create_task(self._periodic_snapshot(symbol, orderbook))
        self.resync_tasks[symbol] = task
        
        return orderbook
    
    async def _periodic_snapshot(self, symbol: str, orderbook: OrderBook):
        while True:
            try:
                await asyncio.sleep(self.snapshot_interval)
                
                if not orderbook.is_synced:
                    logger.warning(f"Resyncing orderbook for {symbol}")
                    await orderbook.init_snapshot(self.client)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic snapshot for {symbol}: {e}")
    
    async def remove_symbol(self, symbol: str):
        if symbol in self.resync_tasks:
            self.resync_tasks[symbol].cancel()
            del self.resync_tasks[symbol]
        
        if symbol in self.orderbooks:
            del self.orderbooks[symbol]
    
    def get_orderbook(self, symbol: str) -> Optional[OrderBook]:
        return self.orderbooks.get(symbol)
