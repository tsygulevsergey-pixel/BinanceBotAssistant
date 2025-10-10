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
        
        # ОБЯЗАТЕЛЬНЫЕ проверки по мануалу: ADX<20, ATR%<p40, BBw<p30
        from src.indicators.technical import calculate_adx, calculate_atr, calculate_bollinger_bands, calculate_ema
        
        adx = calculate_adx(df['high'], df['low'], df['close'], period=14)
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        atr_pct = (atr / df['close']) * 100
        
        current_adx = adx.iloc[-1]
        current_atr_pct = atr_pct.iloc[-1]
        
        # ADX<20 (должен быть низкий)
        if current_adx >= 20:
            return None
        
        # ATR% < p40 (проверка низкой волатильности)
        atr_pct_p40 = atr_pct.rolling(60*24).quantile(0.40).iloc[-1] if len(atr_pct) > 60*24 else atr_pct.quantile(0.40)
        if current_atr_pct >= atr_pct_p40:
            return None
        
        # BB width < p30
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(df['close'], period=20, std=2.0)
        bb_width = (bb_upper - bb_lower) / bb_middle
        current_bb_width = bb_width.iloc[-1]
        bb_width_p30 = bb_width.rolling(90).quantile(0.30).iloc[-1] if len(bb_width) > 90 else bb_width.quantile(0.30)
        
        if current_bb_width >= bb_width_p30:
            return None
        
        # EMA20/50 должны быть плоскими
        ema20 = calculate_ema(df['close'], period=20)
        ema50 = calculate_ema(df['close'], period=50)
        ema20_slope = abs((ema20.iloc[-1] - ema20.iloc[-10]) / ema20.iloc[-10])
        ema50_slope = abs((ema50.iloc[-1] - ema50.iloc[-10]) / ema50.iloc[-10])
        
        if ema20_slope > 0.02 or ema50_slope > 0.02:  # Наклон >2% = не плоские
            return None
        
        # EXPANSION BLOCK проверка: был ли недавний импульс/compression
        # Проверяем что текущий range сжат относительно недавнего
        recent_high = df['high'].tail(20).max()
        recent_low = df['low'].tail(20).min()
        recent_range = recent_high - recent_low
        prev_session_high = df['high'].tail(100).iloc[-40:-20].max()
        prev_session_low = df['low'].tail(100).iloc[-40:-20].min()
        prev_range = prev_session_high - prev_session_low
        
        # Текущий range должен быть существенно меньше предыдущего (compression после expansion)
        if recent_range >= prev_range * 0.7:  # Если сжатие < 30%, это не compression
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
        
        # H4 swing для confluence (получаем из indicators - реальные H4 данные)
        h4_swing_low = indicators.get('h4_swing_low')
        h4_swing_high = indicators.get('h4_swing_high')
        
        if h4_swing_low is None or h4_swing_high is None:
            return None
        
        # LONG: отклонение вниз от value + reclaim обратно
        # Зона покупки: около VAL или VWAP-σ
        if current_close < val or current_close < current_lower:
            # CONFLUENCE проверка: VAL должен совпадать с H4 swing low
            confluence_zone = abs(val - h4_swing_low) <= 0.3 * current_atr
            if not confluence_zone:
                return None
            
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
            # CONFLUENCE проверка: VAH должен совпадать с H4 swing high
            confluence_zone = abs(vah - h4_swing_high) <= 0.3 * current_atr
            if not confluence_zone:
                return None
            
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
