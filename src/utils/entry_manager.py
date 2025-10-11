"""
Entry Manager - управление гибридным входом (MARKET/LIMIT)

Отслеживает LIMIT orders с timeout логикой
"""
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
import pandas as pd
from src.strategies.base_strategy import Signal
from src.utils.logger import logger


@dataclass
class PendingEntry:
    """Отложенный LIMIT ордер с timeout"""
    signal: Signal
    bars_elapsed: int = 0
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    def is_expired(self) -> bool:
        """Проверить, истёк ли timeout"""
        return self.bars_elapsed >= self.signal.entry_timeout
    
    def increment_bar(self):
        """Увеличить счётчик баров"""
        self.bars_elapsed += 1


class EntryManager:
    """
    Управление гибридным входом в позиции
    
    Логика:
    - MARKET orders → немедленное исполнение
    - LIMIT orders → ожидание цены в течение N баров
    - Timeout → отмена ордера
    """
    
    def __init__(self):
        self.pending_limits: Dict[str, PendingEntry] = {}
        logger.info("EntryManager initialized with hybrid entry logic")
    
    def process_signal(self, signal: Signal) -> tuple[str, Optional[Signal]]:
        """
        Обработать сигнал и определить действие
        
        Returns:
            (action, signal) где action: 'EXECUTE' / 'PENDING' / 'SKIP'
        """
        key = self._get_entry_key(signal)
        
        if signal.entry_type == "MARKET":
            logger.info(f"✓ {signal.symbol} {signal.direction} - MARKET entry at {signal.entry_price:.4f}")
            return ("EXECUTE", signal)
        
        elif signal.entry_type == "LIMIT":
            # Проверяем, нет ли уже активного LIMIT ордера
            if key in self.pending_limits:
                logger.debug(f"⏳ {signal.symbol} {signal.direction} already has pending LIMIT order")
                return ("SKIP", None)
            
            # Создаём новый pending entry
            pending = PendingEntry(signal=signal)
            self.pending_limits[key] = pending
            
            logger.info(
                f"⏳ {signal.symbol} {signal.direction} - LIMIT order placed at "
                f"{signal.target_entry_price:.4f} (timeout: {signal.entry_timeout} bars)"
            )
            return ("PENDING", signal)
        
        else:
            logger.warning(f"Unknown entry_type: {signal.entry_type} for {signal.symbol}")
            return ("SKIP", None)
    
    def check_pending_limits(self, symbol: str, current_df: pd.DataFrame) -> List[Signal]:
        """
        Проверить pending LIMIT orders для символа
        
        Returns:
            List[Signal] - список сигналов готовых к исполнению (price reached или timeout)
        """
        executed_signals = []
        expired_keys = []
        
        # Получить последнюю свечу с low/high для проверки wicks
        last_candle = current_df.iloc[-1]
        candle_low = last_candle['low']
        candle_high = last_candle['high']
        
        # Проверяем все pending orders для этого символа
        for key, pending in list(self.pending_limits.items()):
            if pending.signal.symbol != symbol:
                continue
            
            signal = pending.signal
            
            # Проверка: достигнута ли целевая цена через low/high?
            price_reached = False
            fill_price = signal.target_entry_price  # Default fill at target
            
            if signal.direction == "LONG":
                # Для LONG: покупаем когда low свечи касается или ниже target
                if candle_low <= signal.target_entry_price:
                    price_reached = True
                    fill_price = signal.target_entry_price  # Filled at target
            else:  # SHORT
                # Для SHORT: продаём когда high свечи касается или выше target
                if candle_high >= signal.target_entry_price:
                    price_reached = True
                    fill_price = signal.target_entry_price  # Filled at target
            
            if price_reached:
                logger.info(
                    f"✓ {signal.symbol} {signal.direction} - LIMIT filled at "
                    f"{fill_price:.4f} (target: {signal.target_entry_price:.4f}, "
                    f"candle low: {candle_low:.4f}, high: {candle_high:.4f})"
                )
                # Обновляем entry_price на target (фактическая цена исполнения LIMIT)
                signal.entry_price = fill_price
                executed_signals.append(signal)
                expired_keys.append(key)
                continue
            
            # Увеличиваем счётчик баров
            pending.increment_bar()
            
            # Проверка timeout
            if pending.is_expired():
                logger.warning(
                    f"⏱️ {signal.symbol} {signal.direction} - LIMIT timeout after "
                    f"{pending.bars_elapsed} bars (target: {signal.target_entry_price:.4f}, "
                    f"close: {last_candle['close']:.4f})"
                )
                expired_keys.append(key)
        
        # Удаляем исполненные и просроченные orders
        for key in expired_keys:
            del self.pending_limits[key]
        
        return executed_signals
    
    def cancel_pending(self, symbol: str, direction: Optional[str] = None) -> int:
        """
        Отменить pending orders для символа
        
        Args:
            symbol: Торговая пара
            direction: Направление (LONG/SHORT) или None для всех
            
        Returns:
            Количество отменённых ордеров
        """
        cancelled_keys = []
        
        for key, pending in self.pending_limits.items():
            if pending.signal.symbol == symbol:
                if direction is None or pending.signal.direction == direction:
                    cancelled_keys.append(key)
        
        for key in cancelled_keys:
            signal = self.pending_limits[key].signal
            logger.info(f"❌ Cancelled LIMIT order: {signal.symbol} {signal.direction}")
            del self.pending_limits[key]
        
        return len(cancelled_keys)
    
    def get_pending_count(self) -> int:
        """Получить количество активных pending orders"""
        return len(self.pending_limits)
    
    def get_pending_for_symbol(self, symbol: str) -> List[Signal]:
        """Получить все pending orders для символа"""
        return [
            pending.signal 
            for pending in self.pending_limits.values() 
            if pending.signal.symbol == symbol
        ]
    
    def _get_entry_key(self, signal: Signal) -> str:
        """Создать уникальный ключ для entry"""
        return f"{signal.symbol}:{signal.direction}:{signal.strategy_name}"
    
    def get_stats(self) -> Dict:
        """Статистика EntryManager"""
        stats = {
            'pending_limits': self.get_pending_count(),
            'by_symbol': {}
        }
        
        for pending in self.pending_limits.values():
            symbol = pending.signal.symbol
            if symbol not in stats['by_symbol']:
                stats['by_symbol'][symbol] = {'LONG': 0, 'SHORT': 0}
            stats['by_symbol'][symbol][pending.signal.direction] += 1
        
        return stats
