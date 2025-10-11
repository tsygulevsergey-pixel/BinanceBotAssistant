from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.technical import calculate_bollinger_bands, calculate_atr, calculate_ema, calculate_keltner_channels, calculate_adx
from src.utils.strategy_logger import strategy_logger


class SqueezeBreakoutStrategy(BaseStrategy):
    """
    Стратегия #2: Squeeze→Breakout
    
    Логика:
    - Обнаружить squeeze: BB width в нижнем 25-м перцентиле за 90 баров
    - Минимум 12 баров сжатия
    - Пробой: цена закрывается за EMA20 ± 0.25 ATR
    - Фильтр: не далее 1.5 ATR от EMA20
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.squeeze', {})
        super().__init__("Squeeze Breakout", strategy_config)
        
        self.lookback = strategy_config.get('lookback', 90)
        self.bb_percentile = strategy_config.get('bb_percentile', 25)
        self.min_duration = strategy_config.get('min_duration', 12)
        self.breakout_atr = strategy_config.get('breakout_atr', 0.25)
        self.max_distance_ema20 = strategy_config.get('max_distance_ema20', 1.5)
        self.timeframe = '1h'
        self.adx_threshold = config.get('market_detector.trend.adx_threshold', 20)
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "breakout"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает только в SQUEEZE режиме
        if regime != 'SQUEEZE':
            strategy_logger.debug(f"    ❌ Режим {regime}, требуется SQUEEZE")
            return None
        
        if len(df) < self.lookback:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется {self.lookback}")
            return None
        
        # Рассчитать индикаторы
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(df['close'], period=20, std=2.0)
        bb_width = bb_upper - bb_lower
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        ema20 = calculate_ema(df['close'], period=20)
        adx = calculate_adx(df['high'], df['low'], df['close'], period=14)
        
        # Keltner Channels для TTM Squeeze
        kc_upper, kc_middle, kc_lower = calculate_keltner_channels(df['close'], atr, period=20, atr_mult=1.5)
        kc_width = kc_upper - kc_lower
        
        # TTM Squeeze logic: squeeze когда BB width < KC width
        is_squeeze = bb_width < kc_width
        
        # Подсчёт баров сжатия
        squeeze_bars = 0
        for i in range(len(is_squeeze) - 1, -1, -1):
            if is_squeeze.iloc[i]:
                squeeze_bars += 1
            else:
                break
        
        # Минимальная длительность squeeze
        if squeeze_bars < self.min_duration:
            strategy_logger.debug(f"    ❌ Squeeze слишком короткий: {squeeze_bars} баров < {self.min_duration}")
            return None
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_ema20 = ema20.iloc[-1]
        current_atr = atr.iloc[-1]
        current_bb_upper = bb_upper.iloc[-1]
        current_bb_lower = bb_lower.iloc[-1]
        current_adx = adx.iloc[-1] if adx is not None and not pd.isna(adx.iloc[-1]) else 0
        
        # ADX фильтр: ADX > threshold для breakout
        if current_adx <= self.adx_threshold:
            strategy_logger.debug(f"    ❌ ADX слабый для breakout: {current_adx:.1f} <= {self.adx_threshold}")
            return None
        
        # Расстояние от EMA20
        distance_from_ema20 = abs(current_close - current_ema20) / current_atr
        
        # Фильтр: не слишком далеко от EMA20
        if distance_from_ema20 > self.max_distance_ema20:
            strategy_logger.debug(f"    ❌ Слишком далеко от EMA20: {distance_from_ema20:.2f} ATR > {self.max_distance_ema20} ATR")
            return None
        
        # Средний объём
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # LONG: пробой вверх
        if current_close > current_ema20 + self.breakout_atr * current_atr:
            if bias == 'Bearish':
                strategy_logger.debug(f"    ❌ LONG пробой есть, но H4 bias {bias}")
                return None
            
            entry = current_close
            stop_loss = current_bb_lower
            
            # Проверить расстояние до стопа (защита от чрезмерного риска)
            is_valid, stop_distance_atr = self.validate_stop_distance(
                entry, stop_loss, current_atr, 'LONG'
            )
            if not is_valid:
                return None
            
            atr_distance = entry - stop_loss
            
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
                base_score=1.0,
                volume_ratio=float(volume_ratio),
                metadata={
                    'squeeze_bars': squeeze_bars,
                    'bb_width': float(bb_width.iloc[-1]),
                    'kc_width': float(kc_width.iloc[-1]),
                    'ema20': float(current_ema20),
                    'adx': float(current_adx),
                    'distance_from_ema20_atr': float(distance_from_ema20),
                    'squeeze_type': 'TTM'
                }
            )
            return signal
        
        # SHORT: пробой вниз
        elif current_close < current_ema20 - self.breakout_atr * current_atr:
            if bias == 'Bullish':
                strategy_logger.debug(f"    ❌ SHORT пробой есть, но H4 bias {bias}")
                return None
            
            entry = current_close
            stop_loss = current_bb_upper
            
            # Проверить расстояние до стопа (защита от чрезмерного риска)
            is_valid, stop_distance_atr = self.validate_stop_distance(
                entry, stop_loss, current_atr, 'SHORT'
            )
            if not is_valid:
                return None
            
            atr_distance = stop_loss - entry
            
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
                    'squeeze_bars': squeeze_bars,
                    'bb_width': float(bb_width.iloc[-1]),
                    'kc_width': float(kc_width.iloc[-1]),
                    'ema20': float(current_ema20),
                    'adx': float(current_adx),
                    'distance_from_ema20_atr': float(distance_from_ema20),
                    'squeeze_type': 'TTM'
                }
            )
            return signal
        
        strategy_logger.debug(f"    ❌ Нет пробоя: цена в пределах EMA20 ± {self.breakout_atr} ATR")
        return None
