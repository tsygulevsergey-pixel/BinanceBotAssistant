from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr
from src.indicators.volume_profile import calculate_volume_profile
from src.utils.reclaim_checker import check_value_area_reclaim


class VolumeProfileStrategy(BaseStrategy):
    """
    Стратегия #9: Volume Profile (VAH/VPOC/VAL)
    
    Логика:
    - У края value различаем rejection (fade) vs acceptance (продолжение)
    - REJECTION: close обратно в value, POC не сдвигается, CVD flip, imbalance flip, OI не растёт
    - ACCEPTANCE: ≥2 close за VA или ≥0.25 ATR, объём/POC смещаются, CVD/OI по выходу
    
    Триггеры:
    - Fade: как mean reversion (стоп за экстремум, TP к VWAP/POC)
    - Acceptance: как breakout (стоп за ретест, TP по R-множителю)
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.volume_profile', {})
        super().__init__("Volume Profile", strategy_config)
        
        self.timeframe = '15m'  # Основной таймфрейм
        self.lookback_bars = 100
        self.atr_threshold = 0.25  # ATR для acceptance
        self.min_closes_outside = 2  # Минимум 2 close за VA для acceptance
        self.poc_shift_threshold = 0.1  # Порог смещения POC (% от range)
        self.reclaim_bars = strategy_config.get('reclaim_bars', 2)  # Hold N bars для reclaim
        
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"  # Базово MR, но может быть breakout при acceptance
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < self.lookback_bars:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется {self.lookback_bars}")
            return None
        
        # Рассчитать Volume Profile
        vp_result = calculate_volume_profile(df, num_bins=50)
        vah = vp_result['vah']
        val = vp_result['val']
        poc = vp_result['poc']
        
        # ATR для измерений
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Текущая цена и история
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # Проверка близости к краям value area
        near_vah = abs(current_close - vah) <= 0.3 * current_atr
        near_val = abs(current_close - val) <= 0.3 * current_atr
        
        if not (near_vah or near_val):
            strategy_logger.debug(f"    ❌ Цена не около VAH/VAL (расстояние > 0.3 ATR)")
            return None
        
        # Определяем: rejection или acceptance
        signal_type = self._detect_rejection_or_acceptance(
            df, vah, val, poc, current_atr, indicators
        )
        
        if signal_type is None:
            strategy_logger.debug(f"    ❌ Нет четкого rejection или acceptance паттерна")
            return None
        
        # Генерация сигнала в зависимости от типа
        if signal_type == 'rejection_long':
            # FADE SHORT: rejection от VAH, ожидаем возврат вниз
            return self._create_rejection_signal(
                symbol, df, 'short', vah, poc, current_atr, indicators
            )
        elif signal_type == 'rejection_short':
            # FADE LONG: rejection от VAL, ожидаем возврат вверх
            return self._create_rejection_signal(
                symbol, df, 'long', val, poc, current_atr, indicators
            )
        elif signal_type == 'acceptance_long':
            # BREAKOUT LONG: acceptance выше VAH
            return self._create_acceptance_signal(
                symbol, df, 'long', vah, current_atr, indicators
            )
        elif signal_type == 'acceptance_short':
            # BREAKOUT SHORT: acceptance ниже VAL
            return self._create_acceptance_signal(
                symbol, df, 'short', val, current_atr, indicators
            )
        
        strategy_logger.debug(f"    ❌ Неопределенный тип сигнала")
        return None
    
    def _detect_rejection_or_acceptance(self, df: pd.DataFrame, vah: float, val: float, 
                                        poc: float, atr: float, indicators: Dict) -> Optional[str]:
        """
        Определяет rejection vs acceptance
        """
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        # CVD из своего timeframe, fallback к верхнеуровневому или 0
        cvd = indicators.get(self.timeframe, {}).get('cvd', indicators.get('cvd', 0))
        depth_imbalance = indicators.get('depth_imbalance', 1.0)
        doi_pct = indicators.get('doi_pct', 0)
        
        # История closes за последние 3 бара
        recent_closes = df['close'].tail(3).values
        
        # --- ПРОВЕРКА ACCEPTANCE ---
        # Acceptance выше VAH
        if current_close > vah:
            closes_above = sum(c > vah for c in recent_closes)
            distance_above = current_close - vah
            
            # ≥2 close за VA ИЛИ ≥0.25 ATR
            if closes_above >= self.min_closes_outside or distance_above >= self.atr_threshold * atr:
                # Подтверждения: CVD/OI по направлению (вверх)
                if cvd > 0 or doi_pct > 1.0:
                    return 'acceptance_long'
        
        # Acceptance ниже VAL
        if current_close < val:
            closes_below = sum(c < val for c in recent_closes)
            distance_below = val - current_close
            
            if closes_below >= self.min_closes_outside or distance_below >= self.atr_threshold * atr:
                # Подтверждения: CVD/OI вниз
                if cvd < 0 or doi_pct < -1.0:
                    return 'acceptance_short'
        
        # --- ПРОВЕРКА REJECTION с RECLAIM механизмом ---
        # Rejection от VAH: RECLAIM - цена была выше VAH, вернулась в value area и удержалась
        vah_reclaim = check_value_area_reclaim(
            df=df,
            val=val,
            vah=vah,
            direction='short',  # для rejection от VAH
            hold_bars=self.reclaim_bars
        )
        
        if vah_reclaim:
            # CVD flip (было покупки, стали продажи)
            if cvd < 0:
                # Imbalance flip (depth показывает давление вниз)
                if depth_imbalance > 1.1:  # Больше ask = давление продаж
                    # OI не растёт сильно
                    if doi_pct < 2.0:
                        return 'rejection_long'  # Rejection вниз = fade short (но вход long при откате)
        
        # Rejection от VAL: RECLAIM - цена была ниже VAL, вернулась в value area и удержалась
        val_reclaim = check_value_area_reclaim(
            df=df,
            val=val,
            vah=vah,
            direction='long',  # для rejection от VAL
            hold_bars=self.reclaim_bars
        )
        
        if val_reclaim:
            # CVD flip вверх
            if cvd > 0:
                # Imbalance flip вверх
                if depth_imbalance < 0.9:  # Больше bid = давление покупок
                    if doi_pct < 2.0:
                        return 'rejection_short'  # Rejection вверх = fade long
        
        return None
    
    def _create_rejection_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                 level: float, poc: float, atr: float, 
                                 indicators: Dict) -> Signal:
        """
        Создать сигнал FADE (rejection) - как mean reversion
        """
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        if direction == 'long':
            entry = current_close
            stop_loss = current_low - 0.25 * atr
            take_profit_1 = poc  # TP1 к POC
            take_profit_2 = level + 0.5 * atr  # TP2 к противоположной стороне value
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(take_profit_1),
                take_profit_2=float(take_profit_2),
                regime='RANGE',
                bias='neutral',
                base_score=2.5,
                metadata={
                    'type': 'rejection_fade',
                    'level': float(level),
                    'poc': float(poc),
                    'reclaim_bars': self.reclaim_bars
                }
            )
        else:
            entry = current_close
            stop_loss = current_high + 0.25 * atr
            take_profit_1 = poc
            take_profit_2 = level - 0.5 * atr
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(take_profit_1),
                take_profit_2=float(take_profit_2),
                regime='RANGE',
                bias='neutral',
                base_score=2.5,
                metadata={
                    'type': 'rejection_fade',
                    'level': float(level),
                    'poc': float(poc),
                    'reclaim_bars': self.reclaim_bars
                }
            )
    
    def _create_acceptance_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                  level: float, atr: float, indicators: Dict) -> Signal:
        """
        Создать сигнал ACCEPTANCE (breakout) - как трендовая стратегия
        """
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        if direction == 'long':
            entry = current_close
            stop_loss = level - 0.3 * atr  # Стоп за уровень пробоя
            take_profit_1 = entry + 1.5 * atr  # TP1 = +1.5R
            take_profit_2 = entry + 3.0 * atr  # TP2 = +3R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(take_profit_1),
                take_profit_2=float(take_profit_2),
                regime='EXPANSION',
                bias='neutral',
                base_score=2.0,
                metadata={
                    'type': 'acceptance_breakout',
                    'level': float(level)
                }
            )
        else:
            entry = current_close
            stop_loss = level + 0.3 * atr
            take_profit_1 = entry - 1.5 * atr
            take_profit_2 = entry - 3.0 * atr
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(take_profit_1),
                take_profit_2=float(take_profit_2),
                regime='EXPANSION',
                bias='neutral',
                base_score=2.0,
                metadata={
                    'type': 'acceptance_breakout',
                    'level': float(level)
                }
            )
