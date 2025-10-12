from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr
from src.indicators.volume_profile import calculate_volume_profile
from src.utils.sr_zones_15m import create_sr_zones, find_nearest_zone, calculate_stop_loss_from_zone


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
        self.imbalance_threshold = 0.6  # Depth imbalance threshold (>0.6 сильный, <-0.6 слабый)
        self.oi_delta_threshold = 5.0  # ΔOI threshold в %
        self.volume_threshold = 1.5  # Множитель среднего объема
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
        depth_imbalance = indicators.get('depth_imbalance', 0.0)  # -1..+1 format
        # CVD из своего timeframe, fallback к верхнеуровневому
        cvd_series = indicators.get(self.timeframe, {}).get('cvd', indicators.get('cvd'))
        # ΔOI из indicators
        oi_delta = indicators.get('oi_delta_pct', 0.0)
        
        # ATR
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Volume Profile для уровней
        vp_result = calculate_volume_profile(df, num_bins=50)
        vah = vp_result['vah']
        val = vp_result['val']
        poc = vp_result['poc']
        
        current_close = df['close'].iloc[-1]
        
        # Volume check
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        if volume_ratio < self.volume_threshold:
            strategy_logger.debug(f"    ❌ Объем низкий: {volume_ratio:.2f}x < {self.volume_threshold}x")
            return None
        
        # Проверка близости к ключевому уровню
        near_vah = abs(current_close - vah) <= 0.3 * current_atr
        near_val = abs(current_close - val) <= 0.3 * current_atr
        near_poc = abs(current_close - poc) <= 0.3 * current_atr
        
        if not (near_vah or near_val or near_poc):
            strategy_logger.debug(f"    ❌ Цена не около ключевого уровня VAH/VAL/POC (расстояние > 0.3 ATR)")
            return None
        
        # Определяем направление по imbalance
        signal_type = self._check_order_flow(
            df, depth_imbalance, cvd_series, oi_delta, current_atr, indicators
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
                          cvd_series, oi_delta: float, atr: float, indicators: Dict) -> Optional[str]:
        """
        Проверка order flow для подтверждения
        depth_imbalance: -1..+1 формат (>0.6 = сильный buy, <-0.6 = сильный sell)
        """
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        # CVD delta (изменение между барами)
        cvd_delta = 0.0
        if cvd_series is not None and len(cvd_series) >= 2:
            if isinstance(cvd_series, pd.Series):
                cvd_delta = cvd_series.iloc[-1] - cvd_series.iloc[-2]
            elif isinstance(cvd_series, (int, float)):
                # Если это скаляр, используем как есть (fallback)
                cvd_delta = cvd_series
        
        # BULLISH ORDER FLOW
        # depth_imbalance > 0.6 (сильное давление покупателей)
        if depth_imbalance > self.imbalance_threshold:
            # CVD delta положительная (больше покупок)
            if cvd_delta > 0:
                # ΔOI положительная (приток новых лонгов)
                if oi_delta > self.oi_delta_threshold:
                    # Ценовое подтверждение: reclaim или acceptance
                    if current_close > prev_close:
                        return 'long'
        
        # BEARISH ORDER FLOW
        # depth_imbalance < -0.6 (сильное давление продавцов)
        if depth_imbalance < -self.imbalance_threshold:
            # CVD delta отрицательная (больше продаж)
            if cvd_delta < 0:
                # ΔOI положительная (приток новых шортов)
                if oi_delta > self.oi_delta_threshold:
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
                base_score=2.5,
                metadata={
                    'type': 'order_flow',
                    'level': level,
                    'imbalance': 'buy_side'
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
                regime=indicators.get('regime', ''),
                bias=indicators.get('bias', ''),
                base_score=2.5,
                metadata={
                    'type': 'order_flow',
                    'level': level,
                    'imbalance': 'sell_side'
                }
            )
