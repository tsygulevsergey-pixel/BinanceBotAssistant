from typing import Dict, Optional
import pandas as pd
from datetime import datetime
import pytz
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr
from src.utils.sr_zones_15m import create_sr_zones, find_nearest_zone, calculate_stop_loss_from_zone


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
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется 100")
            return None
        
        # Текущее время в UTC
        current_time = df['open_time'].iloc[-1]
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
            strategy_logger.debug(f"    ❌ Час {current_hour} не в активных окнах торговли")
            return None
        
        # Проверка объёма и волатильности
        current_volume = df['volume'].iloc[-1]
        median_volume = df['volume'].tail(100).median()
        
        if current_volume < self.volume_threshold * median_volume:
            strategy_logger.debug(f"    ❌ Объем низкий: {current_volume / median_volume:.2f}x < {self.volume_threshold}x")
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
            strategy_logger.debug(f"    ❌ Волатильность низкая: ATR% {atr_pct:.3f}% < медиана {atr_pct_median:.3f}%")
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
        
        strategy_logger.debug(f"    ❌ Неопределенный тип временного окна")
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
            strategy_logger.debug(f"    ❌ Breakout окно: режим {regime}, требуется TREND или EXPANSION")
            return None
        
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        # Определяем направление по bias или движению цены
        if bias == 'Bullish' or current_close > prev_close:
            direction = 'long'
        elif bias == 'Bearish' or current_close < prev_close:
            direction = 'short'
        else:
            strategy_logger.debug(f"    ❌ Breakout окно: нет четкого направления bias или движения цены")
            return None
        
        if direction == 'long':
            entry = current_close
            
            # Расчет зон S/R для точного стопа
            sr_zones = create_sr_zones(df, atr, buffer_mult=0.25)
            nearest_zone = find_nearest_zone(entry, sr_zones, 'LONG')
            stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, atr, 'LONG', fallback_mult=2.0, max_distance_atr=5.0)
            
            # Расчет дистанции и тейков 1R и 2R
            atr_distance = abs(entry - stop_loss)
            take_profit_1 = entry + atr_distance * 1.0  # 1R
            take_profit_2 = entry + atr_distance * 2.0  # 2R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                regime=regime,
                bias=bias,
                base_score=2.5,
                metadata={
                    'type': 'time_of_day_breakout',
                    'session': 'active',
                    'hour': current_time.hour if isinstance(current_time, pd.Timestamp) else 0
                }
            )
        else:
            entry = current_close
            
            # Расчет зон S/R для точного стопа
            sr_zones = create_sr_zones(df, atr, buffer_mult=0.25)
            nearest_zone = find_nearest_zone(entry, sr_zones, 'SHORT')
            stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, atr, 'SHORT', fallback_mult=2.0, max_distance_atr=5.0)
            
            # Расчет дистанции и тейков 1R и 2R
            atr_distance = abs(stop_loss - entry)
            take_profit_1 = entry - atr_distance * 1.0  # 1R
            take_profit_2 = entry - atr_distance * 2.0  # 2R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                regime=regime,
                bias=bias,
                base_score=2.5,
                metadata={
                    'type': 'time_of_day_breakout',
                    'session': 'active',
                    'hour': current_time.hour if isinstance(current_time, pd.Timestamp) else 0
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
            
            # Расчет зон S/R для точного стопа
            sr_zones = create_sr_zones(df, atr, buffer_mult=0.25)
            nearest_zone = find_nearest_zone(entry, sr_zones, 'SHORT')
            stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, atr, 'SHORT', fallback_mult=2.0, max_distance_atr=5.0)
            
            # Расчет дистанции и тейков 1R и 2R
            atr_distance = abs(stop_loss - entry)
            take_profit_1 = entry - atr_distance * 1.0  # 1R
            take_profit_2 = entry - atr_distance * 2.0  # 2R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                regime=indicators.get('regime', ''),
                bias=indicators.get('bias', ''),
                base_score=2.0,
                metadata={
                    'type': 'time_of_day_mr',
                    'session': 'quiet',
                    'hour': current_time.hour if isinstance(current_time, pd.Timestamp) else 0
                }
            )
        
        # Если близко к низу → long
        elif abs(current_close - recent_low) <= 0.3 * atr:
            entry = current_close
            
            # Расчет зон S/R для точного стопа
            sr_zones = create_sr_zones(df, atr, buffer_mult=0.25)
            nearest_zone = find_nearest_zone(entry, sr_zones, 'LONG')
            stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, atr, 'LONG', fallback_mult=2.0, max_distance_atr=5.0)
            
            # Расчет дистанции и тейков 1R и 2R
            atr_distance = abs(entry - stop_loss)
            take_profit_1 = entry + atr_distance * 1.0  # 1R
            take_profit_2 = entry + atr_distance * 2.0  # 2R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                regime=indicators.get('regime', ''),
                bias=indicators.get('bias', ''),
                base_score=2.0,
                metadata={
                    'type': 'time_of_day_mr',
                    'session': 'quiet',
                    'hour': current_time.hour if isinstance(current_time, pd.Timestamp) else 0
                }
            )
        
        strategy_logger.debug(f"    ❌ MR окно: цена не около экстремумов (расстояние > 0.3 ATR)")
        return None
