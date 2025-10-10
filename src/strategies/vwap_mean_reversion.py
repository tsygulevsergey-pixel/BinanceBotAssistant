from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.vwap import calculate_daily_vwap
from src.indicators.volume_profile import calculate_volume_profile


class VWAPMeanReversionStrategy(BaseStrategy):
    """
    Стратегия #7: VWAP/Value Mean Reversion (рейндж-дни)
    
    Логика по мануалу:
    - RANGE/CHOP: ADX<20, ATR%<p40, BBw<p30, EMA20/50 плоские, BTC нейтральный
    - Зоны: VAH/VAL/POC, ленты VWAP±σ, H4-свинг
    - Триггер: свеча-отклонение + reclaim внутрь value; вход 50/50
    - Стоп: за экстремум +0.25 ATR
    - TP1=VWAP/POC, TP2=середина/противоположная лента
    - Тайм-стоп: 6–8 баров
    - Подтверждения: CVD-дивергенция, imbalance flip
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.vwap_mr', {})
        super().__init__("VWAP Mean Reversion", strategy_config)
        
        self.sigma_bands = strategy_config.get('sigma_bands', [1, 2])
        self.reclaim_bars = strategy_config.get('reclaim_bars', 2)
        self.time_stop = strategy_config.get('time_stop', [6, 8])
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
        
        # BTC должен быть нейтральным (из indicators)
        btc_bias = indicators.get('btc_bias', 'Neutral')
        if btc_bias != 'Neutral':
            return None
        
        if len(df) < 100:
            return None
        
        # Рассчитать VWAP и ленты
        vwap, vwap_upper, vwap_lower = calculate_daily_vwap(df)
        
        # Рассчитать Volume Profile для VAH/VAL/POC
        vp_result = calculate_volume_profile(df, num_bins=50)
        vah = vp_result['vah']
        val = vp_result['val']
        vpoc = vp_result['vpoc']
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_vwap = vwap.iloc[-1]
        current_upper = vwap_upper.iloc[-1]
        current_lower = vwap_lower.iloc[-1]
        
        # ATR для стопов
        from src.indicators.technical import calculate_atr
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # LONG: отклонение вниз от value + reclaim обратно
        # Зона покупки: около VAL или VWAP-σ
        if current_close < val or current_close < current_lower:
            # Проверка: была ли свеча-отклонение и reclaim
            prev_low = df['low'].iloc[-2]
            
            # Свеча reclaim: low был ниже, но close выше зоны
            if prev_low < current_lower and current_close > current_lower:
                
                entry = current_close
                stop_loss = current_low - 0.25 * current_atr
                
                # TP1 = VWAP/POC
                tp1 = max(current_vwap, vpoc)
                # TP2 = противоположная лента
                tp2 = current_upper
                
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
                        'vwap': float(current_vwap),
                        'vwap_upper': float(current_upper),
                        'vwap_lower': float(current_lower),
                        'vah': float(vah),
                        'val': float(val),
                        'vpoc': float(vpoc),
                        'entry_zone': 'val/lower_band'
                    }
                )
                return signal
        
        # SHORT: отклонение вверх от value + reclaim обратно
        elif current_close > vah or current_close > current_upper:
            prev_high = df['high'].iloc[-2]
            
            if prev_high > current_upper and current_close < current_upper:
                
                entry = current_close
                stop_loss = current_high + 0.25 * current_atr
                
                tp1 = min(current_vwap, vpoc)
                tp2 = current_lower
                
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
                        'vwap': float(current_vwap),
                        'vwap_upper': float(current_upper),
                        'vwap_lower': float(current_lower),
                        'vah': float(vah),
                        'val': float(val),
                        'vpoc': float(vpoc),
                        'entry_zone': 'vah/upper_band'
                    }
                )
                return signal
        
        return None
