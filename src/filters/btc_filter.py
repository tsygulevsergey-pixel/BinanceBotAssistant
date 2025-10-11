"""
BTC фильтр согласно мануалу.

Логика:
- H1 импульсы >0.8% блокируют MR-стратегии
- Expansion block для MR (когда BTC волатилен)
- Направленный фильтр для трендовых (−2 если против)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from src.utils.logger import logger


class BTCFilter:
    """BTC фильтр для стратегий"""
    
    def __init__(self, config: Dict):
        self.impulse_threshold = config.get('btc_filter.impulse_threshold', 0.8)
        self.expansion_atr_mult = config.get('btc_filter.expansion_atr_mult', 1.5)
        self.lookback_bars = config.get('btc_filter.lookback_bars', 10)
    
    def get_btc_bias(self, btc_df: pd.DataFrame) -> str:
        """
        Определить bias BTC (Bullish/Bearish/Neutral)
        
        Args:
            btc_df: DataFrame с BTC данными (H1)
            
        Returns:
            'Bullish', 'Bearish', или 'Neutral'
        """
        if len(btc_df) < 20:
            return 'Neutral'
        
        # Простая логика: EMA20/50 crossover
        from src.indicators.technical import calculate_ema
        
        ema20 = calculate_ema(btc_df['close'], period=20)
        ema50 = calculate_ema(btc_df['close'], period=50)
        
        current_ema20 = ema20.iloc[-1]
        current_ema50 = ema50.iloc[-1]
        
        if current_ema20 > current_ema50 * 1.005:  # 0.5% выше
            return 'Bullish'
        elif current_ema20 < current_ema50 * 0.995:  # 0.5% ниже
            return 'Bearish'
        else:
            return 'Neutral'
    
    def check_impulse(self, btc_df: pd.DataFrame) -> Dict:
        """
        Проверить наличие H1 импульса >0.8%
        Блокирует MR стратегии
        
        Returns:
            Dict с информацией об импульсе
        """
        if len(btc_df) < 2:
            return {'has_impulse': False, 'impulse_pct': 0.0}
        
        # Проверяем последний бар
        current_bar = btc_df.iloc[-1]
        bar_range_pct = abs(current_bar['high'] - current_bar['low']) / current_bar['close'] * 100
        
        has_impulse = bar_range_pct >= self.impulse_threshold
        
        if has_impulse:
            logger.debug(f"BTC H1 impulse detected: {bar_range_pct:.2f}% (>{self.impulse_threshold}%)")
        
        return {
            'has_impulse': has_impulse,
            'impulse_pct': bar_range_pct
        }
    
    def check_expansion(self, btc_df: pd.DataFrame) -> bool:
        """
        Проверить expansion block (высокая волатильность BTC)
        Блокирует MR стратегии
        
        Returns:
            True если expansion (блокировать MR)
        """
        if len(btc_df) < 20:
            return False
        
        from src.indicators.technical import calculate_atr
        
        atr = calculate_atr(btc_df['high'], btc_df['low'], btc_df['close'], period=14)
        current_atr = atr.iloc[-1]
        avg_atr = atr.tail(self.lookback_bars).mean()
        
        # Expansion: текущий ATR > 1.5× средний
        is_expansion = current_atr > self.expansion_atr_mult * avg_atr
        
        if is_expansion:
            logger.debug(f"BTC expansion detected: ATR={current_atr:.2f} (avg={avg_atr:.2f})")
        
        return is_expansion
    
    def should_block_mean_reversion(self, btc_df: pd.DataFrame) -> bool:
        """
        Проверить, нужно ли блокировать MR стратегии
        
        Returns:
            True если нужно блокировать
        """
        impulse_check = self.check_impulse(btc_df)
        expansion_check = self.check_expansion(btc_df)
        
        return impulse_check['has_impulse'] or expansion_check
    
    def get_direction_penalty(
        self, 
        signal_direction: str, 
        btc_df: pd.DataFrame
    ) -> float:
        """
        Получить пенальти если BTC идёт против сигнала
        
        Returns:
            0.0 или -2.0 (пенальти)
        """
        if len(btc_df) < 3:
            return 0.0
        
        # Определить направление BTC (последние 3 бара)
        btc_change_pct = (btc_df['close'].iloc[-1] - btc_df['close'].iloc[-3]) / btc_df['close'].iloc[-3] * 100
        
        # Пороговое значение для определения направления (0.3%)
        direction_threshold = 0.3
        
        if abs(btc_change_pct) < direction_threshold:
            return 0.0  # Нейтральный, нет пенальти
        
        btc_direction = 'up' if btc_change_pct > 0 else 'down'
        
        # Пенальти если BTC против
        if signal_direction == 'LONG' and btc_direction == 'down':
            logger.debug(f"BTC against: signal LONG but BTC down {btc_change_pct:.2f}%")
            return -2.0
        elif signal_direction == 'SHORT' and btc_direction == 'up':
            logger.debug(f"BTC against: signal SHORT but BTC up {btc_change_pct:.2f}%")
            return -2.0
        
        return 0.0
