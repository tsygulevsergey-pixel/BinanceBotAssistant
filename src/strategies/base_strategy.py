from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
from src.utils.logger import logger


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
