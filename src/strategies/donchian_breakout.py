from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_donchian, calculate_atr, calculate_bollinger_bands
from src.utils.time_of_day import get_adaptive_volume_threshold


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
        self.timeframe = '1h'  # H1 таймфрейм (формат Binance API)
        self.context_tf = '4h'  # H4 контекст
        self.min_close_distance_atr = 0.25  # Точно по мануалу
        self.volume_threshold = 1.5  # >1.5× медианы 20
        self.bbw_percentile_low = 30  # BB width должен быть в p30-40 до пробоя
        self.bbw_percentile_high = 40
        self.lookback_days = 14  # Для перцентилей (14 дней = 336 баров H1, более реалистично)
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "breakout"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает только в TREND режиме
        if regime != 'TREND':
            strategy_logger.debug(f"    ❌ Режим {regime}, требуется TREND")
            return None
        
        # Проверка достаточности данных
        lookback_bars = self.lookback_days * 24  # Для H1
        if len(df) < max(self.period, lookback_bars) + 1:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров")
            return None
        
        # Рассчитать Donchian Channel
        upper, lower = calculate_donchian(df['high'], df['low'], self.period)
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        
        # BB width для проверки сжатия ДО пробоя
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(df['close'], period=20, std=2.0)
        bb_width = (bb_upper - bb_lower) / bb_middle
        
        # Перцентили BB width (для проверки что было сжатие p30-40)
        # Убираем NaN из bb_width перед вычислением квантилей
        bb_width_clean = bb_width.dropna()
        
        # Требуем минимум 20 точек (1 период BB) для расчета квантилей
        if len(bb_width_clean) < 20:
            strategy_logger.debug(f"    ❌ Недостаточно чистых данных BB width: {len(bb_width_clean)} < 20")
            return None
        
        # Вычисляем глобальные квантили по чистым данным (без NaN)
        bb_width_p30 = bb_width_clean.quantile(0.30)
        bb_width_p40 = bb_width_clean.quantile(0.40)
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_upper = upper.iloc[-1]
        current_lower = lower.iloc[-1]
        current_atr = atr.iloc[-1]
        
        # BB width ДО текущего бара (проверяем -2 бар чтобы было "до пробоя")
        prev_bb_width = bb_width.iloc[-2]
        
        # Проверка на NaN
        if pd.isna(prev_bb_width):
            strategy_logger.debug(f"    ❌ BB width[-2] является NaN")
            return None
        
        # Проверка: BB width был низким (p30-40) до пробоя
        if not (bb_width_p30 <= prev_bb_width <= bb_width_p40):
            strategy_logger.debug(f"    ❌ BB width не в диапазоне p30-40: {prev_bb_width:.6f} (p30={bb_width_p30:.6f}, p40={bb_width_p40:.6f})")
            return None
        
        # Средний объём за 20 периодов
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Адаптивный порог объема по времени суток
        adaptive_volume_threshold = get_adaptive_volume_threshold(df.index[-1], self.volume_threshold)
        
        # Проверка пробоя верхней границы (LONG)
        if (current_high > current_upper and 
            current_close > current_upper and
            volume_ratio >= adaptive_volume_threshold and
            (current_close - current_upper) >= self.min_close_distance_atr * current_atr):
            
            # Фильтр по H4 bias
            if bias == 'Bearish':
                strategy_logger.debug(f"    ❌ LONG пробой есть, но H4 bias Bearish")
                return None
            
            # Расчёт уровней
            entry = current_close
            stop_loss = current_lower
            
            # ВАЖНО: Проверить расстояние до стопа (защита от чрезмерного риска)
            is_valid, stop_distance_atr = self.validate_stop_distance(
                entry, stop_loss, current_atr, 'LONG'
            )
            if not is_valid:
                strategy_logger.debug(
                    f"    ❌ LONG стоп слишком широкий: {stop_distance_atr:.2f} ATR"
                )
                return None
            
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
              volume_ratio >= adaptive_volume_threshold and
              (current_lower - current_close) >= self.min_close_distance_atr * current_atr):
            
            # Фильтр по H4 bias
            if bias == 'Bullish':
                strategy_logger.debug(f"    ❌ SHORT пробой есть, но H4 bias Bullish")
                return None
            
            # Расчёт уровней
            entry = current_close
            stop_loss = current_upper
            
            # ВАЖНО: Проверить расстояние до стопа (защита от чрезмерного риска)
            is_valid, stop_distance_atr = self.validate_stop_distance(
                entry, stop_loss, current_atr, 'SHORT'
            )
            if not is_valid:
                strategy_logger.debug(
                    f"    ❌ SHORT стоп слишком широкий: {stop_distance_atr:.2f} ATR"
                )
                return None
            
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
        
        # Логирование причины отсутствия сигнала
        reasons = []
        
        # Проверка LONG условий
        long_high_ok = current_high > current_upper
        long_close_ok = current_close > current_upper
        long_vol_ok = volume_ratio >= self.volume_threshold
        long_dist_ok = (current_close - current_upper) >= self.min_close_distance_atr * current_atr if current_close > current_upper else False
        
        # Проверка SHORT условий
        short_low_ok = current_low < current_lower
        short_close_ok = current_close < current_lower
        short_vol_ok = volume_ratio >= self.volume_threshold
        short_dist_ok = (current_lower - current_close) >= self.min_close_distance_atr * current_atr if current_close < current_lower else False
        
        if not long_high_ok and not short_low_ok:
            reasons.append(f"нет пробоя границ (high={current_high:.4f}, upper={current_upper:.4f}, low={current_low:.4f}, lower={current_lower:.4f})")
        elif long_high_ok and not long_close_ok:
            reasons.append(f"LONG: high пробил, но close не закрылся выше (close={current_close:.4f} < upper={current_upper:.4f})")
        elif short_low_ok and not short_close_ok:
            reasons.append(f"SHORT: low пробил, но close не закрылся ниже (close={current_close:.4f} > lower={current_lower:.4f})")
        elif (long_high_ok and long_close_ok and not long_vol_ok) or (short_low_ok and short_close_ok and not short_vol_ok):
            reasons.append(f"объем низкий: {volume_ratio:.2f}x < {self.volume_threshold}x")
        elif (long_high_ok and long_close_ok and long_vol_ok and not long_dist_ok):
            dist = (current_close - current_upper) / current_atr if current_atr > 0 else 0
            reasons.append(f"LONG: расстояние от границы мало: {dist:.2f} ATR < {self.min_close_distance_atr} ATR")
        elif (short_low_ok and short_close_ok and short_vol_ok and not short_dist_ok):
            dist = (current_lower - current_close) / current_atr if current_atr > 0 else 0
            reasons.append(f"SHORT: расстояние от границы мало: {dist:.2f} ATR < {self.min_close_distance_atr} ATR")
        else:
            reasons.append("условия пробоя не выполнены")
        
        strategy_logger.debug(f"    ❌ {', '.join(reasons)}")
        return None
