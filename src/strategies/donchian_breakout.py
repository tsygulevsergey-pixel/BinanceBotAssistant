from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.technical import calculate_donchian, calculate_atr


class DonchianBreakoutStrategy(BaseStrategy):
    """
    Стратегия #1: Donchian Breakout
    
    Логика:
    - LONG: цена пробивает верхнюю границу канала Донкина + объём > 1.5x
    - SHORT: цена пробивает нижнюю границу канала Донкина + объём > 1.5x
    - Фильтр: режим TREND, расстояние от границы > 0.25 ATR
    - Контекст: H4 bias должен совпадать с направлением
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.donchian', {})
        super().__init__("Donchian Breakout", strategy_config)
        
        self.period = strategy_config.get('period', 20)
        self.timeframe = strategy_config.get('timeframe', '1h')
        self.context_tf = strategy_config.get('context_timeframe', '4h')
        self.min_close_distance_atr = strategy_config.get('min_close_distance_atr', 0.25)
        self.volume_threshold = strategy_config.get('volume_threshold', 1.5)
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "breakout"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает только в TREND режиме
        if regime != 'TREND':
            return None
        
        # Проверка достаточности данных
        if len(df) < self.period + 1:
            return None
        
        # Рассчитать Donchian Channel
        upper, lower = calculate_donchian(df['high'], df['low'], self.period)
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_upper = upper.iloc[-1]
        current_lower = lower.iloc[-1]
        current_atr = atr.iloc[-1]
        
        # Средний объём за 20 периодов
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Проверка пробоя верхней границы (LONG)
        if (current_high > current_upper and 
            current_close > current_upper and
            volume_ratio >= self.volume_threshold and
            (current_close - current_upper) >= self.min_close_distance_atr * current_atr):
            
            # Фильтр по H4 bias
            if bias == 'Bearish':
                return None
            
            # Расчёт уровней
            entry = current_close
            stop_loss = current_lower
            atr_distance = entry - stop_loss
            
            # R:R targets
            rr_min, rr_max = config.get('risk.rr_targets.breakout', [2.0, 3.0])
            tp1 = entry + atr_distance * rr_min
            tp2 = entry + atr_distance * rr_max
            
            signal = Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(tp1),
                take_profit_2=float(tp2),
                regime=regime,
                bias=bias,
                base_score=1.0,  # Базовый score стратегии
                volume_ratio=float(volume_ratio),
                metadata={
                    'donchian_upper': float(current_upper),
                    'donchian_lower': float(current_lower),
                    'atr': float(current_atr),
                    'breakout_distance_atr': float((current_close - current_upper) / current_atr)
                }
            )
            return signal
        
        # Проверка пробоя нижней границы (SHORT)
        elif (current_low < current_lower and 
              current_close < current_lower and
              volume_ratio >= self.volume_threshold and
              (current_lower - current_close) >= self.min_close_distance_atr * current_atr):
            
            # Фильтр по H4 bias
            if bias == 'Bullish':
                return None
            
            # Расчёт уровней
            entry = current_close
            stop_loss = current_upper
            atr_distance = stop_loss - entry
            
            # R:R targets
            rr_min, rr_max = config.get('risk.rr_targets.breakout', [2.0, 3.0])
            tp1 = entry - atr_distance * rr_min
            tp2 = entry - atr_distance * rr_max
            
            signal = Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(tp1),
                take_profit_2=float(tp2),
                regime=regime,
                bias=bias,
                base_score=1.0,
                volume_ratio=float(volume_ratio),
                metadata={
                    'donchian_upper': float(current_upper),
                    'donchian_lower': float(current_lower),
                    'atr': float(current_atr),
                    'breakout_distance_atr': float((current_lower - current_close) / current_atr)
                }
            )
            return signal
        
        return None
