from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr


class BreakRetestStrategy(BaseStrategy):
    """
    Стратегия #5: Break & Retest
    
    Логика по мануалу:
    - Пробой с close ≥0.25 ATR и объёмом >1.5–2×
    - Зона ретеста = экстремум±0.2–0.3 ATR ∩ AVWAP(бар пробоя)
    - Триггер: 50% лимитом в зоне, 50% — по подтверждению
    - Стоп: за свинг-реакцией +0.2–0.3 ATR
    - Подтверждения: CVD flip, imbalance flip/refill, OI не падает
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.retest', {})
        super().__init__("Break & Retest", strategy_config)
        
        self.breakout_atr = strategy_config.get('breakout_atr', 0.25)
        self.zone_atr = strategy_config.get('zone_atr', [0.2, 0.3])
        self.volume_threshold = strategy_config.get('volume_threshold', 1.5)
        self.split_ratio = strategy_config.get('split_ratio', 0.5)  # 50/50
        self.timeframe = '15m'
        self.breakout_lookback = 20  # Ищем пробои за последние 20 баров
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "pullback"
    
    def _find_recent_breakout(self, df: pd.DataFrame, atr: pd.Series) -> Optional[Dict]:
        """Найти недавний пробой"""
        for i in range(-self.breakout_lookback, 0):
            if abs(i) >= len(df):
                continue
            
            bar_close = df['close'].iloc[i]
            bar_high = df['high'].iloc[i]
            bar_low = df['low'].iloc[i]
            bar_volume = df['volume'].iloc[i]
            bar_atr = atr.iloc[i]
            
            # Проверяем предыдущий максимум/минимум (10 баров до)
            if i - 10 < -len(df):
                continue
                
            prev_high = df['high'].iloc[i-10:i].max() if i < -1 else df['high'].iloc[i-10:i+1].max()
            prev_low = df['low'].iloc[i-10:i].min() if i < -1 else df['low'].iloc[i-10:i+1].min()
            
            # Средний объём
            avg_vol = df['volume'].iloc[i-20:i].mean() if i < -1 else df['volume'].iloc[i-20:i+1].mean()
            vol_ratio = bar_volume / avg_vol if avg_vol > 0 else 0
            
            # Пробой вверх
            if (bar_close > prev_high and 
                (bar_close - prev_high) >= self.breakout_atr * bar_atr and
                vol_ratio >= self.volume_threshold):
                return {
                    'direction': 'LONG',
                    'level': prev_high,
                    'bar_index': i,
                    'atr': bar_atr
                }
            
            # Пробой вниз
            elif (bar_close < prev_low and 
                  (prev_low - bar_close) >= self.breakout_atr * bar_atr and
                  vol_ratio >= self.volume_threshold):
                return {
                    'direction': 'SHORT',
                    'level': prev_low,
                    'bar_index': i,
                    'atr': bar_atr
                }
        
        return None
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < 50:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется 50")
            return None
        
        # Рассчитать ATR
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Найти недавний пробой
        breakout = self._find_recent_breakout(df, atr)
        if breakout is None:
            strategy_logger.debug(f"    ❌ Нет недавнего пробоя с объемом >{self.volume_threshold}x и расстоянием ≥{self.breakout_atr} ATR")
            return None
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # Зона ретеста = экстремум ± 0.2-0.3 ATR
        breakout_level = breakout['level']
        retest_zone_upper = breakout_level + self.zone_atr[1] * current_atr
        retest_zone_lower = breakout_level - self.zone_atr[1] * current_atr
        
        # LONG retest (после пробоя вверх)
        if breakout['direction'] == 'LONG':
            # Проверка: цена вернулась в зону ретеста
            if retest_zone_lower <= current_close <= retest_zone_upper:
                # Проверка: есть ли rebound (отскок)
                # Простая проверка: low коснулся зоны, но close выше
                if current_low <= breakout_level and current_close > breakout_level:
                    
                    # Фильтр по H4 bias
                    if bias == 'Bearish':
                        strategy_logger.debug(f"    ❌ LONG ретест есть, но H4 bias {bias}")
                        return None
                    
                    entry = current_close
                    stop_loss = current_low - 0.25 * current_atr
                    atr_distance = entry - stop_loss
                    
                    rr_min, rr_max = config.get('risk.rr_targets.retest', [1.5, 2.5])
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
                        metadata={
                            'breakout_level': float(breakout_level),
                            'retest_zone_upper': float(retest_zone_upper),
                            'retest_zone_lower': float(retest_zone_lower),
                            'breakout_bar_index': int(breakout['bar_index'])
                        }
                    )
                    return signal
        
        # SHORT retest (после пробоя вниз)
        elif breakout['direction'] == 'SHORT':
            if retest_zone_lower <= current_close <= retest_zone_upper:
                # Проверка: high коснулся зоны, но close ниже
                if current_high >= breakout_level and current_close < breakout_level:
                    
                    if bias == 'Bullish':
                        strategy_logger.debug(f"    ❌ SHORT ретест есть, но H4 bias {bias}")
                        return None
                    
                    entry = current_close
                    stop_loss = current_high + 0.25 * current_atr
                    atr_distance = stop_loss - entry
                    
                    rr_min, rr_max = config.get('risk.rr_targets.retest', [1.5, 2.5])
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
                        metadata={
                            'breakout_level': float(breakout_level),
                            'retest_zone_upper': float(retest_zone_upper),
                            'retest_zone_lower': float(retest_zone_lower),
                            'breakout_bar_index': int(breakout['bar_index'])
                        }
                    )
                    return signal
        
        strategy_logger.debug(f"    ❌ Цена не в зоне ретеста или нет отскока от уровня пробоя")
        return None
