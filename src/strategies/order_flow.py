from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr
from src.indicators.volume_profile import calculate_volume_profile


class OrderFlowStrategy(BaseStrategy):
    """
    Стратегия #12: Order Flow / Imbalance / Absorption
    
    Логика:
    - Торговать только когда поток подтверждает уровень
    - Imbalance, refill (абсорбция) из WS depth
    - Серии агрессора из aggTrades
    - Триггер: только вместе с ценовым подтверждением (reclaim/acceptance)
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.order_flow', {})
        super().__init__("Order Flow", strategy_config)
        
        self.timeframe = '15m'
        self.lookback_bars = 50
        self.imbalance_threshold = 1.2  # Порог имбаланса bid/ask
        self.refill_check_window = 5   # Баров для проверки refill
        
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < self.lookback_bars:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется {self.lookback_bars}")
            return None
        
        # Получаем depth imbalance и CVD из indicators
        depth_imbalance = indicators.get('depth_imbalance', 1.0)
        cvd = indicators.get('cvd', 0)
        
        # ATR
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Volume Profile для уровней
        vp_result = calculate_volume_profile(df, num_bins=50)
        vah = vp_result['vah']
        val = vp_result['val']
        poc = vp_result['poc']
        
        current_close = df['close'].iloc[-1]
        
        # Проверка близости к ключевому уровню
        near_vah = abs(current_close - vah) <= 0.3 * current_atr
        near_val = abs(current_close - val) <= 0.3 * current_atr
        near_poc = abs(current_close - poc) <= 0.3 * current_atr
        
        if not (near_vah or near_val or near_poc):
            strategy_logger.debug(f"    ❌ Цена не около ключевого уровня VAH/VAL/POC (расстояние > 0.3 ATR)")
            return None
        
        # Определяем направление по imbalance
        signal_type = self._check_order_flow(
            df, depth_imbalance, cvd, current_atr, indicators
        )
        
        if signal_type is None:
            strategy_logger.debug(f"    ❌ Нет подтверждения order flow: imbalance или CVD не совпадают с ценовым движением")
            return None
        
        # Генерация сигнала
        if signal_type == 'long':
            return self._create_of_signal(
                symbol, df, 'long', current_atr, indicators, 
                level=val if near_val else (poc if near_poc else vah)
            )
        elif signal_type == 'short':
            return self._create_of_signal(
                symbol, df, 'short', current_atr, indicators,
                level=vah if near_vah else (poc if near_poc else val)
            )
        
        strategy_logger.debug(f"    ❌ Неопределенный тип order flow сигнала")
        return None
    
    def _check_order_flow(self, df: pd.DataFrame, depth_imbalance: float,
                          cvd: float, atr: float, indicators: Dict) -> Optional[str]:
        """
        Проверка order flow для подтверждения
        """
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        # BULLISH ORDER FLOW: depth_imbalance < 0.9 (больше bid = покупки)
        if depth_imbalance < 1.0 / self.imbalance_threshold:
            # CVD подтверждает покупки
            if cvd > 0:
                # Ценовое подтверждение: reclaim или acceptance
                if current_close > prev_close:
                    return 'long'
        
        # BEARISH ORDER FLOW: depth_imbalance > 1.2 (больше ask = продажи)
        if depth_imbalance > self.imbalance_threshold:
            # CVD подтверждает продажи
            if cvd < 0:
                # Ценовое подтверждение
                if current_close < prev_close:
                    return 'short'
        
        return None
    
    def _create_of_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                         atr: float, indicators: Dict, level: float) -> Signal:
        """
        Создать сигнал по order flow
        """
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        if direction == 'long':
            entry = current_close
            stop_loss = current_low - 0.3 * atr
            take_profit_1 = level + 0.5 * atr  # TP к уровню
            take_profit_2 = level + 1.5 * atr
            
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
                    'type': 'order_flow',
                    'level': level,
                    'imbalance': 'buy_side'
                }
            )
        else:
            entry = current_close
            stop_loss = current_high + 0.3 * atr
            take_profit_1 = level - 0.5 * atr
            take_profit_2 = level - 1.5 * atr
            
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
                    'type': 'order_flow',
                    'level': level,
                    'imbalance': 'sell_side'
                }
            )
