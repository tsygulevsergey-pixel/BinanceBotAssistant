from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.technical import calculate_atr


class LiquiditySweepStrategy(BaseStrategy):
    """
    Стратегия #11: Liquidity Sweep (Stop-Hunt)
    
    Логика:
    - Укол за high/low (sweep) и быстрый reclaim → fade
    - При acceptance (продолжение движения) → continuation
    
    FADE: reclaim внутрь в том же/след. баре + CVD flip + imbalance flip
    CONTINUATION: acceptance (2 close/0.25 ATR) + объём/POC-сдвиг + OI↑
    
    Сканер: прокол ≥0.1–0.3 ATR или ≥0.1–0.2%; объём свейпа >1.5–2×
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.liquidity_sweep', {})
        super().__init__("Liquidity Sweep", strategy_config)
        
        self.timeframe = '15m'
        self.lookback_bars = 50
        self.sweep_min_atr = 0.1  # Минимальный прокол 0.1 ATR
        self.sweep_max_atr = 0.3  # Максимальный прокол 0.3 ATR
        self.sweep_min_pct = 0.001  # 0.1% минимум
        self.sweep_max_pct = 0.002  # 0.2% максимум
        self.volume_threshold = 1.5  # Объём свейпа >1.5×
        self.acceptance_min_closes = 2  # Минимум 2 close для acceptance
        self.acceptance_atr_distance = 0.25
        
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"  # Fade базово MR, continuation - breakout
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < self.lookback_bars:
            return None
        
        # ATR для измерений
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Текущая и предыдущая свеча
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_close = df['close'].iloc[-1]
        current_volume = df['volume'].iloc[-1]
        
        prev_high = df['high'].iloc[-2]
        prev_low = df['low'].iloc[-2]
        prev_close = df['close'].iloc[-2]
        
        # Медианный объём
        median_volume = df['volume'].tail(20).median()
        
        # Найти локальные экстремумы
        recent_high = df['high'].tail(self.lookback_bars).max()
        recent_low = df['low'].tail(self.lookback_bars).min()
        
        # --- ПРОВЕРКА SWEEP UP (прокол вверх) ---
        sweep_up_atr = current_high - recent_high
        sweep_up_pct = sweep_up_atr / recent_high
        
        if (self.sweep_min_atr * current_atr <= sweep_up_atr <= self.sweep_max_atr * current_atr or
            self.sweep_min_pct <= sweep_up_pct <= self.sweep_max_pct):
            
            # Объём свейпа
            if current_volume > self.volume_threshold * median_volume:
                
                # Проверка FADE vs ACCEPTANCE
                signal_type = self._check_fade_or_continuation(
                    df, 'up', recent_high, current_atr, indicators
                )
                
                if signal_type == 'fade':
                    return self._create_fade_signal(
                        symbol, df, 'short', recent_high, current_atr, indicators
                    )
                elif signal_type == 'continuation':
                    return self._create_continuation_signal(
                        symbol, df, 'long', recent_high, current_atr, indicators
                    )
        
        # --- ПРОВЕРКА SWEEP DOWN (прокол вниз) ---
        sweep_down_atr = recent_low - current_low
        sweep_down_pct = sweep_down_atr / recent_low
        
        if (self.sweep_min_atr * current_atr <= sweep_down_atr <= self.sweep_max_atr * current_atr or
            self.sweep_min_pct <= sweep_down_pct <= self.sweep_max_pct):
            
            if current_volume > self.volume_threshold * median_volume:
                
                signal_type = self._check_fade_or_continuation(
                    df, 'down', recent_low, current_atr, indicators
                )
                
                if signal_type == 'fade':
                    return self._create_fade_signal(
                        symbol, df, 'long', recent_low, current_atr, indicators
                    )
                elif signal_type == 'continuation':
                    return self._create_continuation_signal(
                        symbol, df, 'short', recent_low, current_atr, indicators
                    )
        
        return None
    
    def _check_fade_or_continuation(self, df: pd.DataFrame, sweep_direction: str,
                                    sweep_level: float, atr: float, 
                                    indicators: Dict) -> Optional[str]:
        """
        Определяет fade или continuation после sweep
        """
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        cvd = indicators.get('cvd', 0)
        depth_imbalance = indicators.get('depth_imbalance', 1.0)
        doi_pct = indicators.get('doi_pct', 0)
        
        # История последних 3 closes
        recent_closes = df['close'].tail(3).values
        
        if sweep_direction == 'up':
            # Sweep вверх
            # FADE: reclaim внутрь (close вернулся ниже уровня)
            if current_close < sweep_level:
                # CVD flip вниз (было покупки на свейпе, стали продажи)
                if cvd < 0:
                    # Imbalance flip (давление продаж)
                    if depth_imbalance > 1.1:
                        return 'fade'
            
            # CONTINUATION: acceptance выше (≥2 close за уровень или ≥0.25 ATR)
            closes_above = sum(c >= sweep_level for c in recent_closes)
            distance_above = current_close - sweep_level
            
            if closes_above >= self.acceptance_min_closes or distance_above >= self.acceptance_atr_distance * atr:
                # CVD/OI по выходу (покупки продолжаются)
                if cvd > 0 or doi_pct > 1.0:
                    return 'continuation'
        
        else:  # sweep_direction == 'down'
            # Sweep вниз
            # FADE: reclaim вверх
            if current_close > sweep_level:
                # CVD flip вверх
                if cvd > 0:
                    # Imbalance flip (давление покупок)
                    if depth_imbalance < 0.9:
                        return 'fade'
            
            # CONTINUATION: acceptance ниже
            closes_below = sum(c <= sweep_level for c in recent_closes)
            distance_below = sweep_level - current_close
            
            if closes_below >= self.acceptance_min_closes or distance_below >= self.acceptance_atr_distance * atr:
                # CVD/OI вниз
                if cvd < 0 or doi_pct < -1.0:
                    return 'continuation'
        
        return None
    
    def _create_fade_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                           sweep_level: float, atr: float, indicators: Dict) -> Signal:
        """
        Создать сигнал FADE - возврат после sweep
        """
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        if direction == 'long':
            # Fade вниз после sweep down → long
            entry = current_close
            stop_loss = current_low - 0.25 * atr  # За хвост свейпа
            
            # TP как в mean reversion
            take_profit_1 = sweep_level + 0.5 * atr  # TP1 обратно к уровню
            take_profit_2 = sweep_level + 1.5 * atr  # TP2 дальше
            
            return Signal(
                symbol=symbol,
                direction='long',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.5,
                strategy_name=self.name,
                metadata={
                    'type': 'liquidity_sweep_fade',
                    'sweep_level': sweep_level,
                    'sweep_direction': 'down'
                }
            )
        else:
            # Fade вверх после sweep up → short
            entry = current_close
            stop_loss = current_high + 0.25 * atr
            
            take_profit_1 = sweep_level - 0.5 * atr
            take_profit_2 = sweep_level - 1.5 * atr
            
            return Signal(
                symbol=symbol,
                direction='short',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.5,
                strategy_name=self.name,
                metadata={
                    'type': 'liquidity_sweep_fade',
                    'sweep_level': sweep_level,
                    'sweep_direction': 'up'
                }
            )
    
    def _create_continuation_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                    sweep_level: float, atr: float, indicators: Dict) -> Signal:
        """
        Создать сигнал CONTINUATION - продолжение после acceptance
        """
        current_close = df['close'].iloc[-1]
        
        if direction == 'long':
            entry = current_close
            stop_loss = sweep_level - 0.3 * atr  # За уровень свейпа
            
            # TP как в breakout
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
                    'type': 'liquidity_sweep_continuation',
                    'sweep_level': sweep_level,
                    'sweep_direction': 'up'
                }
            )
        else:
            entry = current_close
            stop_loss = sweep_level + 0.3 * atr
            
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
                    'type': 'liquidity_sweep_continuation',
                    'sweep_level': sweep_level,
                    'sweep_direction': 'down'
                }
            )
