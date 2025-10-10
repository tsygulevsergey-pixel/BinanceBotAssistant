from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.technical import calculate_atr


class RangeFadeStrategy(BaseStrategy):
    """
    Стратегия #8: Range Fade (от границ диапазона)
    
    Логика по мануалу:
    - RANGE-детектор; качественные границы (≥2–3 теста)
    - Конфлюэнс с VA/VWAP/H4 свинг
    - IB не чрезмерно широкий
    - Триггер/стоп/тейки: как в VWAP MR
    - Подтверждения: CVD-дивергенция, imbalance flip, абсорбция-прокси
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.range_fade', {})
        super().__init__("Range Fade", strategy_config)
        
        self.min_tests = strategy_config.get('min_tests', 2)
        self.time_stop = strategy_config.get('time_stop', [6, 8])
        self.timeframe = '15m'
        self.lookback_bars = 100  # Для определения границ рейнджа
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"
    
    def _find_range_boundaries(self, df: pd.DataFrame) -> Optional[Dict]:
        """Найти границы рейнджа с ≥2-3 теста"""
        recent_data = df.tail(self.lookback_bars)
        
        # Упрощённая логика: находим resistance и support
        # Resistance = зона где было ≥2 касания максимумов
        # Support = зона где было ≥2 касания минимумов
        
        highs = recent_data['high']
        lows = recent_data['low']
        
        # Найти potential resistance (верхние 10% цен)
        high_threshold = highs.quantile(0.90)
        high_tests = (highs >= high_threshold).sum()
        
        # Найти potential support (нижние 10% цен)
        low_threshold = lows.quantile(0.10)
        low_tests = (lows <= low_threshold).sum()
        
        if high_tests >= self.min_tests and low_tests >= self.min_tests:
            return {
                'resistance': high_threshold,
                'support': low_threshold,
                'resistance_tests': high_tests,
                'support_tests': low_tests
            }
        
        return None
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает только в RANGE режиме
        if regime not in ['RANGE', 'CHOP']:
            return None
        
        if len(df) < self.lookback_bars:
            return None
        
        # Найти границы рейнджа
        range_bounds = self._find_range_boundaries(df)
        if range_bounds is None:
            return None
        
        resistance = range_bounds['resistance']
        support = range_bounds['support']
        
        # ATR для стопов
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # LONG fade: цена у support, отбой вверх
        if current_low <= support + 0.1 * current_atr:  # Около support
            # Проверка: есть ли признаки отбоя (close выше low)
            if current_close > current_low + 0.2 * current_atr:
                
                entry = current_close
                stop_loss = current_low - 0.25 * current_atr
                
                # TP1 = середина рейнджа, TP2 = resistance
                mid_range = (resistance + support) / 2
                tp1 = mid_range
                tp2 = resistance
                
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
                    base_score=1.0,
                    metadata={
                        'resistance': float(resistance),
                        'support': float(support),
                        'resistance_tests': int(range_bounds['resistance_tests']),
                        'support_tests': int(range_bounds['support_tests']),
                        'fade_from': 'support'
                    }
                )
                return signal
        
        # SHORT fade: цена у resistance, отбой вниз
        elif current_high >= resistance - 0.1 * current_atr:  # Около resistance
            if current_close < current_high - 0.2 * current_atr:
                
                entry = current_close
                stop_loss = current_high + 0.25 * current_atr
                
                mid_range = (resistance + support) / 2
                tp1 = mid_range
                tp2 = support
                
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
                    metadata={
                        'resistance': float(resistance),
                        'support': float(support),
                        'resistance_tests': int(range_bounds['resistance_tests']),
                        'support_tests': int(range_bounds['support_tests']),
                        'fade_from': 'resistance'
                    }
                )
                return signal
        
        return None
