from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_ema, calculate_atr, calculate_adx
from src.indicators.vwap import calculate_daily_vwap


class MAVWAPPullbackStrategy(BaseStrategy):
    """
    Стратегия #4: MA/VWAP Pullback
    
    Логика по мануалу:
    - H4 тренд (EMA50↑, ADX>20), 1–2‑й откат
    - Зона = EMA20±0.3 ATR или AVWAP от пробоя
    - Глубина 0.38–0.62 Фибо
    - Триггер: свеча‑отклонение + close над EMA20
    - Подтверждения: объём>1.2–1.5×, CVD flip вверх
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.pullback', {})
        super().__init__("MA/VWAP Pullback", strategy_config)
        
        self.ma_periods = strategy_config.get('ma_periods', [20, 50])
        self.fib_levels = strategy_config.get('fib_levels', [0.382, 0.618])
        self.retest_atr = strategy_config.get('retest_atr', 0.3)
        self.volume_threshold = strategy_config.get('volume_threshold', 1.2)
        self.timeframe = '4h'  # H4 pullback по мануалу
        self.adx_threshold = 20
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "pullback"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает в TREND режиме
        if regime != 'TREND':
            strategy_logger.debug(f"    ❌ Режим {regime}, требуется TREND")
            return None
        
        if len(df) < 200:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется 200")
            return None
        
        # Рассчитать индикаторы
        ema20 = calculate_ema(df['close'], period=20)
        ema50 = calculate_ema(df['close'], period=50)
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        adx = calculate_adx(df['high'], df['low'], df['close'], period=14)
        vwap, vwap_upper, vwap_lower = calculate_daily_vwap(df)
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_ema20 = ema20.iloc[-1]
        current_ema50 = ema50.iloc[-1]
        current_atr = atr.iloc[-1]
        current_adx = adx.iloc[-1] if adx is not None and not pd.isna(adx.iloc[-1]) else 0
        current_vwap = vwap.iloc[-1] if vwap is not None and not pd.isna(vwap.iloc[-1]) else current_close
        
        # Проверка H4 тренда (ADX>20)
        if current_adx <= self.adx_threshold:
            strategy_logger.debug(f"    ❌ ADX слабый: {current_adx:.1f} <= {self.adx_threshold}")
            return None
        
        # Определить тренд по EMA50
        ema50_slope = (ema50.iloc[-1] - ema50.iloc[-10]) / ema50.iloc[-10]
        
        # Объём
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Проверка объёма
        if volume_ratio < self.volume_threshold:
            strategy_logger.debug(f"    ❌ Объем низкий: {volume_ratio:.2f}x < {self.volume_threshold}x")
            return None
        
        # Зона отката: EMA20 ± 0.3 ATR или VWAP ± 0.3 ATR
        pullback_zone_upper = current_ema20 + self.retest_atr * current_atr
        pullback_zone_lower = current_ema20 - self.retest_atr * current_atr
        vwap_zone_upper = current_vwap + self.retest_atr * current_atr
        vwap_zone_lower = current_vwap - self.retest_atr * current_atr
        
        # Fibonacci retracement расчет
        recent_swing_high = df['high'].tail(50).max()
        recent_swing_low = df['low'].tail(50).min()
        fib_range = recent_swing_high - recent_swing_low
        fib_382 = recent_swing_high - (fib_range * 0.382)
        fib_618 = recent_swing_high - (fib_range * 0.618)
        
        # LONG pullback (восходящий тренд)
        if ema50_slope > 0 and bias != 'Bearish':
            # Проверка Fibonacci: pullback в зоне 38.2%-61.8%
            in_fib_zone = fib_618 <= current_close <= fib_382
            if not in_fib_zone:
                strategy_logger.debug(f"    ❌ LONG: цена не в Фибо зоне 38.2%-61.8%: {current_close:.2f} вне [{fib_618:.2f}, {fib_382:.2f}]")
                return None
            
            # Проверка: находимся ли в зоне отката (EMA20 или VWAP)
            in_ema_zone = pullback_zone_lower <= current_close <= pullback_zone_upper
            in_vwap_zone = vwap_zone_lower <= current_close <= vwap_zone_upper
            
            if in_ema_zone or in_vwap_zone:
                # Проверка: свеча закрылась над EMA20 (подтверждение)
                if current_close > current_ema20:
                    
                    entry = current_close
                    # Найти swing low для стопа
                    swing_low = df['low'].tail(20).min()
                    stop_loss = swing_low - 0.25 * current_atr
                    atr_distance = entry - stop_loss
                    
                    rr_min, rr_max = config.get('risk.rr_targets.pullback', [1.5, 2.5])
                    tp1 = entry + atr_distance * 1.0  # TP1=+1R
                    tp2 = entry + atr_distance * rr_max
                    
                    base_score = 1.0
                    confirmations = []
                    
                    cvd_change = indicators.get('cvd_change')
                    doi_pct = indicators.get('doi_pct')
                    cvd_valid = indicators.get('cvd_valid', False)
                    oi_valid = indicators.get('oi_valid', False)
                    
                    if cvd_valid and cvd_change is not None and cvd_change > 0:
                        base_score += 0.5
                        confirmations.append('cvd_flip_up')
                    
                    if oi_valid and doi_pct is not None and doi_pct > 5:
                        base_score += 0.5
                        confirmations.append('doi_growth')
                    
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
                        base_score=base_score,
                        volume_ratio=float(volume_ratio),
                        metadata={
                            'ema20': float(current_ema20),
                            'ema50': float(current_ema50),
                            'vwap': float(current_vwap),
                            'adx': float(current_adx),
                            'swing_low': float(swing_low),
                            'fib_382': float(fib_382),
                            'fib_618': float(fib_618),
                            'in_fib_zone': in_fib_zone,
                            'pullback_zone_upper': float(pullback_zone_upper),
                            'pullback_zone_lower': float(pullback_zone_lower),
                            'in_ema_zone': in_ema_zone,
                            'in_vwap_zone': in_vwap_zone,
                            'confirmations': confirmations,
                            'cvd_change': float(cvd_change) if cvd_change is not None else None,
                            'doi_pct': float(doi_pct) if doi_pct is not None else None
                        }
                    )
                    return signal
        
        # SHORT pullback (нисходящий тренд)
        elif ema50_slope < 0 and bias != 'Bullish':
            # Проверка Fibonacci: pullback в зоне 38.2%-61.8% (для SHORT используем те же уровни)
            in_fib_zone = fib_618 <= current_close <= fib_382
            if not in_fib_zone:
                strategy_logger.debug(f"    ❌ SHORT: цена не в Фибо зоне 38.2%-61.8%: {current_close:.2f} вне [{fib_618:.2f}, {fib_382:.2f}]")
                return None
            
            in_ema_zone = pullback_zone_lower <= current_close <= pullback_zone_upper
            in_vwap_zone = vwap_zone_lower <= current_close <= vwap_zone_upper
            
            if in_ema_zone or in_vwap_zone:
                # Проверка: свеча закрылась под EMA20
                if current_close < current_ema20:
                    
                    entry = current_close
                    # Найти swing high для стопа
                    swing_high = df['high'].tail(20).max()
                    stop_loss = swing_high + 0.25 * current_atr
                    atr_distance = stop_loss - entry
                    
                    rr_min, rr_max = config.get('risk.rr_targets.pullback', [1.5, 2.5])
                    tp1 = entry - atr_distance * 1.0
                    tp2 = entry - atr_distance * rr_max
                    
                    base_score = 1.0
                    confirmations = []
                    
                    cvd_change = indicators.get('cvd_change')
                    doi_pct = indicators.get('doi_pct')
                    cvd_valid = indicators.get('cvd_valid', False)
                    oi_valid = indicators.get('oi_valid', False)
                    
                    if cvd_valid and cvd_change is not None and cvd_change < 0:
                        base_score += 0.5
                        confirmations.append('cvd_flip_down')
                    
                    if oi_valid and doi_pct is not None and doi_pct > 5:
                        base_score += 0.5
                        confirmations.append('doi_growth')
                    
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
                        base_score=base_score,
                        volume_ratio=float(volume_ratio),
                        metadata={
                            'ema20': float(current_ema20),
                            'ema50': float(current_ema50),
                            'vwap': float(current_vwap),
                            'adx': float(current_adx),
                            'swing_high': float(swing_high),
                            'fib_382': float(fib_382),
                            'fib_618': float(fib_618),
                            'in_fib_zone': in_fib_zone,
                            'pullback_zone_upper': float(pullback_zone_upper),
                            'pullback_zone_lower': float(pullback_zone_lower),
                            'in_ema_zone': in_ema_zone,
                            'in_vwap_zone': in_vwap_zone,
                            'confirmations': confirmations,
                            'cvd_change': float(cvd_change) if cvd_change is not None else None,
                            'doi_pct': float(doi_pct) if doi_pct is not None else None
                        }
                    )
                    return signal
        
        strategy_logger.debug(f"    ❌ Нет подтверждения отката: цена не в зоне EMA20±{self.retest_atr} ATR или нет закрытия нужной стороны")
        return None
