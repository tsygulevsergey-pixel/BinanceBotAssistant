from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
from src.utils.logger import logger
from src.utils.config import config


@dataclass
class Signal:
    """Торговый сигнал от стратегии"""
    strategy_name: str
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    timestamp: datetime
    timeframe: str
    
    # Entry parameters
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float] = None
    
    # Entry execution (hybrid approach)
    entry_type: str = "MARKET"  # MARKET or LIMIT
    target_entry_price: Optional[float] = None  # For LIMIT orders
    entry_timeout: int = 6  # Bars to wait for LIMIT fill
    
    # Risk offsets for SL/TP recalculation (preserves R:R when entry changes)
    stop_offset: Optional[float] = None  # Distance from entry to SL
    tp1_offset: Optional[float] = None   # Distance from entry to TP1
    tp2_offset: Optional[float] = None   # Distance from entry to TP2
    
    # Market context
    regime: str = ""  # TREND/RANGE/SQUEEZE
    bias: str = ""  # Bullish/Bearish/Neutral
    
    # Base score from strategy logic
    base_score: float = 0.0
    
    # Additional context
    volume_ratio: float = 1.0
    cvd_direction: str = ""  # Bullish/Bearish/Neutral
    oi_delta_percent: float = 0.0
    imbalance_detected: bool = False
    
    # Filters
    late_trend: bool = False
    funding_extreme: bool = False
    btc_against: bool = False
    
    # Final score after modifiers
    final_score: float = 0.0
    
    # Additional metadata
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseStrategy(ABC):
    """Базовый класс для всех торговых стратегий"""
    
    def __init__(self, name: str, config: Dict):
        self.name = name
        self.config = config
        self.enabled = True
        self.signals_generated = 0
        
    @abstractmethod
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        """
        Проверить условия для сигнала
        
        Args:
            symbol: Торговая пара
            df: DataFrame с OHLCV данными
            regime: Рыночный режим (TREND/RANGE/SQUEEZE)
            bias: Направление тренда на H4 (Bullish/Bearish/Neutral)
            indicators: Словарь с рассчитанными индикаторами
            
        Returns:
            Signal если условия выполнены, иначе None
        """
        pass
    
    @abstractmethod
    def get_timeframe(self) -> str:
        """Вернуть таймфрейм стратегии"""
        pass
    
    @abstractmethod
    def get_category(self) -> str:
        """Вернуть категорию: breakout, pullback, mean_reversion"""
        pass
    
    def calculate_position_size(self, entry: float, stop_loss: float, 
                                risk_percent: float = 0.01) -> float:
        """Рассчитать размер позиции на основе риска"""
        risk_per_unit = abs(entry - stop_loss) / entry
        position_size = risk_percent / risk_per_unit if risk_per_unit > 0 else 0
        return position_size
    
    def is_enabled(self) -> bool:
        """Проверить, включена ли стратегия"""
        return self.enabled
    
    def enable(self):
        """Включить стратегию"""
        self.enabled = True
        logger.info(f"Strategy {self.name} enabled")
    
    def disable(self):
        """Выключить стратегию"""
        self.enabled = False
        logger.info(f"Strategy {self.name} disabled")
    
    def increment_signal_count(self):
        """Увеличить счётчик сгенерированных сигналов"""
        self.signals_generated += 1
    
    def get_stats(self) -> Dict:
        """Получить статистику стратегии"""
        return {
            'name': self.name,
            'enabled': self.enabled,
            'signals_generated': self.signals_generated,
            'category': self.get_category(),
            'timeframe': self.get_timeframe()
        }
    
    def validate_stop_distance(self, entry: float, stop_loss: float, 
                                current_atr: float, direction: str) -> Tuple[bool, float]:
        """
        Проверить расстояние до стопа (защита от чрезмерного риска)
        
        Returns:
            (is_valid, stop_distance_atr)
        """
        # Рассчитать расстояние в ATR
        stop_distance = abs(entry - stop_loss)
        stop_distance_atr = stop_distance / current_atr if current_atr > 0 else 999
        
        # Получить максимально допустимое расстояние
        # Приоритет: per-strategy override → global config → default 3.0
        max_stop_atr = self.config.get('max_stop_distance_atr') or \
                       config.get('risk.max_stop_distance_atr', 3.0)
        
        # Проверка
        if stop_distance_atr > max_stop_atr:
            logger.warning(
                f"{self.name} - Stop too wide: {stop_distance_atr:.2f} ATR "
                f"(max: {max_stop_atr:.2f} ATR), signal rejected"
            )
            return False, stop_distance_atr
        
        return True, stop_distance_atr
    
    def calculate_risk_offsets(self, signal: Signal) -> Signal:
        """
        Рассчитать и сохранить offset'ы для SL/TP
        Это позволяет корректно пересчитать уровни при изменении entry_price
        """
        if signal.direction == "LONG":
            signal.stop_offset = signal.entry_price - signal.stop_loss  # Положительное
            signal.tp1_offset = signal.take_profit_1 - signal.entry_price  # Положительное
            if signal.take_profit_2:
                signal.tp2_offset = signal.take_profit_2 - signal.entry_price
        else:  # SHORT
            signal.stop_offset = signal.stop_loss - signal.entry_price  # Положительное
            signal.tp1_offset = signal.entry_price - signal.take_profit_1  # Положительное
            if signal.take_profit_2:
                signal.tp2_offset = signal.entry_price - signal.take_profit_2
        
        return signal
    
    def determine_entry_type(self, entry_price: float, df: pd.DataFrame) -> tuple:
        """
        Определить тип входа на основе категории стратегии (ГИБРИДНЫЙ подход)
        
        Returns:
            (entry_type, target_entry_price, entry_timeout)
        """
        category = self.get_category()
        
        # BREAKOUT → MARKET entry для скорости
        if category == "breakout":
            return ("MARKET", None, 6)
        
        # PULLBACK → LIMIT entry на уровень отката
        elif category == "pullback":
            # Для pullback стратегий entry_price уже содержит целевой уровень
            return ("LIMIT", entry_price, 6)
        
        # MEAN REVERSION → LIMIT entry в зону интереса
        elif category == "mean_reversion":
            # Для MR стратегий entry_price - это целевая зона
            return ("LIMIT", entry_price, 4)  # Меньший timeout для MR
        
        # ORDER FLOW, CVD и другие → MARKET (агрессивный вход)
        else:
            return ("MARKET", None, 6)
