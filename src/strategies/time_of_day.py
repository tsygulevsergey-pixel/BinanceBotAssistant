from typing import Dict, Optional
import pandas as pd
from datetime import datetime
import pytz
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.technical import calculate_atr


class TimeOfDayStrategy(BaseStrategy):
    """
    Стратегия #14: Time-of-Day (временные паттерны)
    
    Логика:
    - Сессии EU/US дают лучшие импульсы для пробоев/momentum
    - Тонкие окна лучше для mean reversion
    - Работает только в выбранных временных слотах при объёме >1.5× и волатильности выше медианы
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.time_of_day', {})
        super().__init__("Time-of-Day", strategy_config)
        
        self.timeframe = '15m'
        
        # Жирные окна для пробоев (UTC)
        self.breakout_windows = [
            (7, 9),    # EU открытие 07:00-09:00
            (13, 15),  # US открытие 13:00-15:00 (13:30-14:30)
        ]
        
        # Тонкие окна для MR
        self.mr_windows = [
            (0, 2),    # Азиатская ночь 00:00-02:00
            (22, 24),  # Вечер после закрытия US 22:00-24:00
        ]
        
        self.volume_threshold = 1.5
        self.volatility_threshold_percentile = 50  # Выше p50
        
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "breakout"  # Зависит от времени суток
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < 100:
            return None
        
        # Текущее время в UTC
        current_time = df.index[-1]
        if not isinstance(current_time, pd.Timestamp):
            current_time = pd.Timestamp(current_time, tz='UTC')
        else:
            if current_time.tz is None:
                current_time = current_time.tz_localize('UTC')
            else:
                current_time = current_time.tz_convert('UTC')
        
        current_hour = current_time.hour
        
        # Определяем тип окна
        window_type = self._get_window_type(current_hour)
        
        if window_type is None:
            return None
        
        # Проверка объёма и волатильности
        current_volume = df['volume'].iloc[-1]
        median_volume = df['volume'].tail(100).median()
        
        if current_volume < self.volume_threshold * median_volume:
            return None
        
        # Волатильность (ATR%)
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        current_close = df['close'].iloc[-1]
        atr_pct = (current_atr / current_close) * 100
        
        # Медиана волатильности
        atr_series = atr.tail(100)
        atr_pct_series = (atr_series / df['close'].tail(100)) * 100
        atr_pct_median = atr_pct_series.median()
        
        if atr_pct < atr_pct_median:
            return None
        
        # Генерация сигнала в зависимости от окна
        if window_type == 'breakout':
            return self._create_breakout_signal(
                symbol, df, regime, bias, current_atr, indicators
            )
        elif window_type == 'mean_reversion':
            return self._create_mr_signal(
                symbol, df, current_atr, indicators
            )
        
        return None
    
    def _get_window_type(self, hour: int) -> Optional[str]:
        """
        Определяет тип временного окна
        """
        # Проверка жирных окон (breakout)
        for start, end in self.breakout_windows:
            if start <= hour < end:
                return 'breakout'
        
        # Проверка тонких окон (MR)
        for start, end in self.mr_windows:
            if start <= hour < end:
                return 'mean_reversion'
        
        return None
    
    def _create_breakout_signal(self, symbol: str, df: pd.DataFrame, regime: str,
                                bias: str, atr: float, indicators: Dict) -> Optional[Signal]:
        """
        Создать сигнал пробоя в жирном окне
        """
        # Пробой только в TREND/EXPANSION режиме
        if regime not in ['TREND', 'EXPANSION']:
            return None
        
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        # Определяем направление по bias или движению цены
        if bias == 'Bullish' or current_close > prev_close:
            direction = 'long'
        elif bias == 'Bearish' or current_close < prev_close:
            direction = 'short'
        else:
            return None
        
        if direction == 'long':
            entry = current_close
            stop_loss = entry - 0.5 * atr
            take_profit_1 = entry + 1.5 * atr
            take_profit_2 = entry + 3.0 * atr
            
            return Signal(
                symbol=symbol,
                direction='long',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.0,
                strategy_name=self.name,
                metadata={
                    'type': 'time_of_day_breakout',
                    'session': 'active',
                    'hour': df.index[-1].hour if isinstance(df.index[-1], pd.Timestamp) else 0
                }
            )
        else:
            entry = current_close
            stop_loss = entry + 0.5 * atr
            take_profit_1 = entry - 1.5 * atr
            take_profit_2 = entry - 3.0 * atr
            
            return Signal(
                symbol=symbol,
                direction='short',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.0,
                strategy_name=self.name,
                metadata={
                    'type': 'time_of_day_breakout',
                    'session': 'active',
                    'hour': df.index[-1].hour if isinstance(df.index[-1], pd.Timestamp) else 0
                }
            )
    
    def _create_mr_signal(self, symbol: str, df: pd.DataFrame, 
                         atr: float, indicators: Dict) -> Optional[Signal]:
        """
        Создать mean reversion сигнал в тонком окне
        """
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # Простая логика MR: откат от недавнего экстремума
        recent_high = df['high'].tail(20).max()
        recent_low = df['low'].tail(20).min()
        
        # Если близко к верху → short
        if abs(current_close - recent_high) <= 0.3 * atr:
            entry = current_close
            stop_loss = current_high + 0.25 * atr
            take_profit_1 = entry - 1.0 * atr
            take_profit_2 = entry - 2.0 * atr
            
            return Signal(
                symbol=symbol,
                direction='short',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.0,
                strategy_name=self.name,
                metadata={
                    'type': 'time_of_day_mr',
                    'session': 'quiet',
                    'hour': df.index[-1].hour if isinstance(df.index[-1], pd.Timestamp) else 0
                }
            )
        
        # Если близко к низу → long
        elif abs(current_close - recent_low) <= 0.3 * atr:
            entry = current_close
            stop_loss = current_low - 0.25 * atr
            take_profit_1 = entry + 1.0 * atr
            take_profit_2 = entry + 2.0 * atr
            
            return Signal(
                symbol=symbol,
                direction='long',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.0,
                strategy_name=self.name,
                metadata={
                    'type': 'time_of_day_mr',
                    'session': 'quiet',
                    'hour': df.index[-1].hour if isinstance(df.index[-1], pd.Timestamp) else 0
                }
            )
        
        return None
