from typing import Dict, Optional
import pandas as pd
import numpy as np
from datetime import time
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.technical import calculate_atr


class ORBStrategy(BaseStrategy):
    """
    Стратегия #3: ORB/IRB (Opening/Initial Range Breakout)
    
    Логика по мануалу:
    - Слоты: 00:00-01:00, 07:00-08:00, 13:30-14:30 UTC
    - IB_width < p30 (60 дней) и <0.8·ATR(14)
    - H4 тренд в сторону
    - Пробой: close за IB ≥0.25 ATR
    - Подтверждения: объём>1.5×, BTC в ту же сторону
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.orb', {})
        super().__init__("ORB/IRB", strategy_config)
        
        # Слоты по мануалу (UTC)
        self.slots = [
            (time(0, 0), time(1, 0)),      # Asia open
            (time(7, 0), time(8, 0)),      # EU open
            (time(13, 30), time(14, 30))   # US open
        ]
        self.ib_duration_minutes = 60
        self.width_percentile = 30  # p30
        self.lookback_days = 60
        self.atr_multiplier = 0.8  # <0.8·ATR
        self.breakout_atr = 0.25  # ≥0.25 ATR
        self.volume_threshold = 1.5
        self.timeframe = '15m'  # Для отслеживания IB используем 15m
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "breakout"
    
    def _is_in_slot(self, timestamp: pd.Timestamp) -> bool:
        """Проверить, находится ли timestamp в одном из торговых слотов"""
        current_time = timestamp.time()
        for start, end in self.slots:
            if start <= current_time < end:
                return True
        return False
    
    def _calculate_ib_range(self, df: pd.DataFrame) -> tuple:
        """
        Рассчитать Initial Balance (первый час диапазона)
        Возвращает (ib_high, ib_low, ib_width)
        """
        # Находим бары за последний час (4 бара по 15m)
        ib_bars = df.tail(4)
        ib_high = ib_bars['high'].max()
        ib_low = ib_bars['low'].min()
        ib_width = ib_high - ib_low
        
        return ib_high, ib_low, ib_width
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < self.lookback_days * 24 * 4:  # 60 дней по 15m
            return None
        
        current_timestamp = df.index[-1]
        
        # Проверка: находимся ли мы в одном из слотов
        if not self._is_in_slot(current_timestamp):
            return None
        
        # Рассчитать IB range
        ib_high, ib_low, ib_width = self._calculate_ib_range(df)
        
        # ATR для фильтрации
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Проверка: IB_width < 0.8·ATR
        if ib_width >= self.atr_multiplier * current_atr:
            return None
        
        # Проверка: IB_width < p30 (60 дней)
        # Рассчитываем width за предыдущие дни
        historical_widths = []
        for i in range(1, self.lookback_days + 1):
            lookback_bars = i * 24 * 4  # Дни назад
            if len(df) > lookback_bars + 4:
                hist_bars = df.iloc[-(lookback_bars + 4):-lookback_bars]
                if len(hist_bars) >= 4:
                    hist_width = hist_bars['high'].max() - hist_bars['low'].min()
                    historical_widths.append(hist_width)
        
        if historical_widths:
            width_p30 = np.percentile(historical_widths, 30)
            if ib_width >= width_p30:
                return None
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # Объём
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Проверка объёма
        if volume_ratio < self.volume_threshold:
            return None
        
        # LONG: пробой IB вверх
        if (current_high > ib_high and 
            current_close > ib_high and
            (current_close - ib_high) >= self.breakout_atr * current_atr):
            
            # Фильтр по H4 bias
            if bias == 'Bearish':
                return None
            
            entry = current_close
            stop_loss = ib_low - 0.25 * current_atr  # За противоположной границей IB +0.2-0.3 ATR
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
                    'ib_high': float(ib_high),
                    'ib_low': float(ib_low),
                    'ib_width': float(ib_width),
                    'ib_width_atr': float(ib_width / current_atr),
                    'slot_time': str(current_timestamp.time())
                }
            )
            return signal
        
        # SHORT: пробой IB вниз
        elif (current_low < ib_low and 
              current_close < ib_low and
              (ib_low - current_close) >= self.breakout_atr * current_atr):
            
            # Фильтр по H4 bias
            if bias == 'Bullish':
                return None
            
            entry = current_close
            stop_loss = ib_high + 0.25 * current_atr
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
                    'ib_high': float(ib_high),
                    'ib_low': float(ib_low),
                    'ib_width': float(ib_width),
                    'ib_width_atr': float(ib_width / current_atr),
                    'slot_time': str(current_timestamp.time())
                }
            )
            return signal
        
        return None
