from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.technical import calculate_rsi, calculate_stochastic, calculate_atr


class RSIStochMRStrategy(BaseStrategy):
    """
    Стратегия #10: RSI/Stochastic Mean Reversion
    
    Логика по мануалу:
    - RANGE-дни; RSI пороги по перцентилям (p15/p85 на 90d)
    - Стохастик крест обратно
    - Зона = край рейнджа ∩ VWAP/VA
    - Триггер/стоп/тейки: как в VWAP MR
    - Подтверждения: CVD-дивергенция, imbalance flip
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.oscillator_mr', {})
        super().__init__("RSI/Stoch MR", strategy_config)
        
        self.rsi_period = strategy_config.get('rsi_period', 14)
        self.stoch_period = strategy_config.get('stoch_period', 14)
        self.oversold_percentile = strategy_config.get('oversold_percentile', 20)  # p15-20
        self.overbought_percentile = strategy_config.get('overbought_percentile', 80)  # p80-85
        self.lookback = strategy_config.get('lookback', 90)  # 90 дней
        self.timeframe = '15m'
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает только в RANGE режиме
        if regime not in ['RANGE', 'CHOP']:
            return None
        
        lookback_bars = self.lookback * 24 * 4  # 90 дней * 24 часа * 4 (15m bars)
        if len(df) < lookback_bars:
            return None
        
        # Рассчитать осцилляторы
        rsi = calculate_rsi(df['close'], period=self.rsi_period)
        stoch_k, stoch_d = calculate_stochastic(
            df['high'], df['low'], df['close'], 
            period=self.stoch_period
        )
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        
        # Адаптивные пороги RSI (перцентили за lookback)
        rsi_history = rsi.tail(lookback_bars)
        rsi_oversold = rsi_history.quantile(self.oversold_percentile / 100.0)
        rsi_overbought = rsi_history.quantile(self.overbought_percentile / 100.0)
        
        # Текущие значения
        current_rsi = rsi.iloc[-1]
        current_stoch_k = stoch_k.iloc[-1]
        current_stoch_d = stoch_d.iloc[-1]
        prev_stoch_k = stoch_k.iloc[-2]
        prev_stoch_d = stoch_d.iloc[-2]
        
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_atr = atr.iloc[-1]
        
        # LONG: RSI в oversold + stoch крест вверх
        if current_rsi <= rsi_oversold:
            # Стохастик крест: K пересекает D снизу вверх
            if prev_stoch_k <= prev_stoch_d and current_stoch_k > current_stoch_d:
                
                entry = current_close
                stop_loss = current_low - 0.25 * current_atr
                
                # TP1 = средний уровень RSI (50), TP2 = overbought
                # Упрощённо: TP в расчёте от entry
                atr_distance = entry - stop_loss
                tp1 = entry + atr_distance * 1.0
                tp2 = entry + atr_distance * 2.0
                
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
                        'rsi': float(current_rsi),
                        'rsi_oversold': float(rsi_oversold),
                        'rsi_overbought': float(rsi_overbought),
                        'stoch_k': float(current_stoch_k),
                        'stoch_d': float(current_stoch_d),
                        'cross_type': 'bullish'
                    }
                )
                return signal
        
        # SHORT: RSI в overbought + stoch крест вниз
        elif current_rsi >= rsi_overbought:
            # Стохастик крест: K пересекает D сверху вниз
            if prev_stoch_k >= prev_stoch_d and current_stoch_k < current_stoch_d:
                
                entry = current_close
                stop_loss = current_high + 0.25 * current_atr
                
                atr_distance = stop_loss - entry
                tp1 = entry - atr_distance * 1.0
                tp2 = entry - atr_distance * 2.0
                
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
                        'rsi': float(current_rsi),
                        'rsi_oversold': float(rsi_oversold),
                        'rsi_overbought': float(rsi_overbought),
                        'stoch_k': float(current_stoch_k),
                        'stoch_d': float(current_stoch_d),
                        'cross_type': 'bearish'
                    }
                )
                return signal
        
        return None
