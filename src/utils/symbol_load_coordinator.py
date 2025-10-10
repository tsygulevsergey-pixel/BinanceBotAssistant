import asyncio
import threading
from typing import Optional, Set
from dataclasses import dataclass
from src.utils.logger import logger


@dataclass
class LoadProgress:
    """Progress tracking for symbol loading and analysis"""
    total_symbols: int
    loading_queue_size: int
    loaded_count: int
    analyzing_count: int
    failed_symbols: Set[str]


class SymbolLoadCoordinator:
    """Coordinates parallel symbol loading and analysis"""
    
    def __init__(self, total_symbols: int, queue_max_size: int = 50):
        self.total_symbols = total_symbols
        
        self.ready_queue = asyncio.Queue(maxsize=queue_max_size)
        
        self._lock = threading.Lock()
        self._shutdown_event = asyncio.Event()
        
        self._loaded_symbols: Set[str] = set()
        self._analyzing_symbols: Set[str] = set()
        self._failed_symbols: Set[str] = set()
        
        self._loading_count = 0
        self._analyzed_count = 0
    
    async def add_ready_symbol(self, symbol: str):
        """Add a symbol to the ready queue after loading completes"""
        with self._lock:
            self._loaded_symbols.add(symbol)
        
        await self.ready_queue.put(symbol)
        logger.debug(f"Symbol {symbol} added to ready queue (queue size: {self.ready_queue.qsize()})")
    
    async def get_next_symbol(self) -> Optional[str]:
        """Get next symbol from ready queue for analysis"""
        try:
            symbol = await asyncio.wait_for(
                self.ready_queue.get(),
                timeout=1.0
            )
            
            with self._lock:
                self._analyzing_symbols.add(symbol)
            
            return symbol
        except asyncio.TimeoutError:
            return None
    
    def mark_symbol_analyzed(self, symbol: str):
        """Mark symbol as analyzed and remove from analyzing set"""
        with self._lock:
            if symbol in self._analyzing_symbols:
                self._analyzing_symbols.remove(symbol)
            self._analyzed_count += 1
    
    def mark_symbol_failed(self, symbol: str, error: str):
        """Mark symbol as failed to load"""
        with self._lock:
            self._failed_symbols.add(symbol)
        
        logger.error(f"Symbol {symbol} failed to load: {error}")
    
    def increment_loading_count(self):
        """Increment count of symbols currently being loaded"""
        with self._lock:
            self._loading_count += 1
    
    def decrement_loading_count(self):
        """Decrement count of symbols currently being loaded"""
        with self._lock:
            self._loading_count = max(0, self._loading_count - 1)
    
    def get_progress(self) -> LoadProgress:
        """Get current progress snapshot"""
        with self._lock:
            return LoadProgress(
                total_symbols=self.total_symbols,
                loading_queue_size=self.ready_queue.qsize(),
                loaded_count=len(self._loaded_symbols),
                analyzing_count=len(self._analyzing_symbols),
                failed_symbols=self._failed_symbols.copy()
            )
    
    def signal_shutdown(self):
        """Signal all tasks to shutdown gracefully"""
        self._shutdown_event.set()
        logger.info("Shutdown signal sent to coordinator")
    
    async def wait_for_shutdown(self):
        """Wait for shutdown signal"""
        await self._shutdown_event.wait()
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested"""
        return self._shutdown_event.is_set()
    
    def is_loading_complete(self) -> bool:
        """Check if all symbols have been loaded or failed"""
        with self._lock:
            processed = len(self._loaded_symbols) + len(self._failed_symbols)
            return processed >= self.total_symbols and self._loading_count == 0
    
    def get_status_summary(self) -> str:
        """Get human-readable status summary"""
        progress = self.get_progress()
        
        loaded_pct = (progress.loaded_count / progress.total_symbols * 100) if progress.total_symbols > 0 else 0
        
        return (
            f"Loading: {progress.loaded_count}/{progress.total_symbols} ({loaded_pct:.1f}%) | "
            f"Queue: {progress.loading_queue_size} ready | "
            f"Analyzing: {progress.analyzing_count} symbols | "
            f"Failed: {len(progress.failed_symbols)}"
        )
