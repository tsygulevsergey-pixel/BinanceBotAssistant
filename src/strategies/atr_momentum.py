from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr, calculate_ema, calculate_adx


class ATRMomentumStrategy(BaseStrategy):
    """
    Стратегия #6: ATR Momentum (протяжка)
    
    Логика по мануалу:
    - Импульс-бар ≥1.4× ATR, close в верхн.20%
    - Follow-through; H4 тренд; до сопротивления ≥1.5 ATR
    - Не LATE_TREND
    - Триггер: пробой high импульса/флага ≥0.2–0.3 ATR или micro-pullback к EMA9/20
    - Подтверждения: объём>2×, CVD dir, ΔOI +1…+3%
    - Тайм-стоп: 6–8 баров без 0.5 ATR прогресса
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.momentum', {})
        super().__init__("ATR Momentum", strategy_config)
        
        self.impulse_atr = strategy_config.get('impulse_atr', 1.4)
        self.close_percentile = strategy_config.get('close_percentile', 20)  # top 20%
        self.min_distance_resistance = strategy_config.get('min_distance_resistance', 1.5)
        self.pullback_ema = strategy_config.get('pullback_ema', [9, 20])
        self.volume_threshold = 2.0  # >2× по мануалу
        self.breakout_atr_min = 0.2
        self.breakout_atr_max = 0.3
        self.timeframe = '15m'  # Для отслеживания импульсов
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "breakout"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает в TREND режиме, но не LATE_TREND
        if regime != 'TREND':
            strategy_logger.debug(f"    ❌ Режим {regime}, требуется TREND")
            return None
        
        # Проверка на LATE_TREND (это должен передать детектор)
        late_trend = indicators.get('late_trend', False)
        if late_trend:
            strategy_logger.debug(f"    ❌ Режим LATE_TREND, стратегия не работает")
            return None
        
        if len(df) < 100:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется 100")
            return None
        
        # Рассчитать индикаторы
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        ema9 = calculate_ema(df['close'], period=9)
        ema20 = calculate_ema(df['close'], period=20)
        ema200 = calculate_ema(df['close'], period=200)
        adx = calculate_adx(df['high'], df['low'], df['close'], period=14)
        
        # Rolling median ATR для expansion сравнения
        atr_median = atr.rolling(window=20).median().iloc[-1]
        
        # Текущие и предыдущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_atr = atr.iloc[-1]
        current_ema200 = ema200.iloc[-1] if ema200 is not None and not pd.isna(ema200.iloc[-1]) else current_close
        current_adx = adx.iloc[-1] if adx is not None and not pd.isna(adx.iloc[-1]) else 0
        
        # ADX фильтр: ADX > 25 для momentum
        if current_adx <= 25:
            strategy_logger.debug(f"    ❌ ADX слабый для momentum: {current_adx:.1f} <= 25")
            return None
        
        # Найти импульс-бар (проверяем последние 5 баров)
        impulse_bar_idx = None
        for i in range(-5, 0):
            bar_range = df['high'].iloc[i] - df['low'].iloc[i]
            bar_close = df['close'].iloc[i]
            bar_low = df['low'].iloc[i]
            bar_high = df['high'].iloc[i]
            bar_atr_median = atr.rolling(window=20).median().iloc[i]
            
            # Проверка: бар ≥1.4× median ATR (не current ATR)
            if bar_range >= self.impulse_atr * bar_atr_median:
                # Проверка: close в верхн.20% (для LONG)
                bar_position = (bar_close - bar_low) / bar_range if bar_range > 0 else 0
                if bar_position >= 0.80:  # top 20% = > 80% от low
                    impulse_bar_idx = i
                    break
        
        if impulse_bar_idx is None:
            strategy_logger.debug(f"    ❌ Нет импульс-бара ≥{self.impulse_atr}× median ATR с close в верхн.20%")
            return None
        
        impulse_high = df['high'].iloc[impulse_bar_idx]
        impulse_low = df['low'].iloc[impulse_bar_idx]
        
        # Объём
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Проверка объёма
        if volume_ratio < self.volume_threshold:
            strategy_logger.debug(f"    ❌ Объем низкий: {volume_ratio:.2f}x < {self.volume_threshold}x")
            return None
        
        # Проверка расстояния до сопротивления (упрощённо - проверяем есть ли место)
        # Сопротивление = недавний максимум
        resistance = df['high'].tail(50).max()
        distance_to_resistance = (resistance - current_close) / current_atr
        
        if distance_to_resistance < self.min_distance_resistance:
            strategy_logger.debug(f"    ❌ Слишком близко к сопротивлению: {distance_to_resistance:.2f} ATR < {self.min_distance_resistance} ATR")
            return None
        
        # LONG: пробой high импульса или pullback к EMA9/20
        if bias != 'Bearish':
            # Вариант 1: пробой high импульса ≥0.2-0.3 ATR
            if (current_high > impulse_high and 
                (current_high - impulse_high) >= self.breakout_atr_min * current_atr):
                
                entry = current_close
                stop_loss = impulse_low - 0.25 * current_atr
                atr_distance = entry - stop_loss
                
                rr_min, rr_max = config.get('risk.rr_targets.breakout', [2.0, 3.0])
                tp1 = entry + atr_distance * rr_min
                tp2 = entry + atr_distance * rr_max
                
                base_score = 1.0
                confirmations = []
                
                cvd_change = indicators.get('cvd_change')
                doi_pct = indicators.get('doi_pct')
                depth_imbalance = indicators.get('depth_imbalance')
                cvd_valid = indicators.get('cvd_valid', False)
                oi_valid = indicators.get('oi_valid', False)
                depth_valid = indicators.get('depth_valid', False)
                
                if cvd_valid and cvd_change is not None and cvd_change > 0:
                    base_score += 0.5
                    confirmations.append('cvd_direction')
                
                if oi_valid and doi_pct is not None and doi_pct > 5:
                    base_score += 0.5
                    confirmations.append('doi_growth')
                
                if depth_valid and depth_imbalance is not None and depth_imbalance > 0:
                    base_score += 0.5
                    confirmations.append('bid_pressure')
                
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
                        'impulse_high': float(impulse_high),
                        'impulse_low': float(impulse_low),
                        'impulse_bar_index': int(impulse_bar_idx),
                        'ema200': float(current_ema200),
                        'adx': float(current_adx),
                        'atr_median': float(atr_median),
                        'distance_to_resistance_atr': float(distance_to_resistance),
                        'entry_type': 'breakout',
                        'confirmations': confirmations,
                        'cvd_change': float(cvd_change) if cvd_change is not None else None,
                        'doi_pct': float(doi_pct) if doi_pct is not None else None,
                        'depth_imbalance': float(depth_imbalance) if depth_imbalance is not None else None
                    }
                )
                return signal
            
            # Вариант 2: micro-pullback к EMA9/20
            ema9_val = ema9.iloc[-1]
            ema20_val = ema20.iloc[-1]
            
            if (current_low <= ema20_val and current_close > ema20_val):
                entry = current_close
                stop_loss = current_low - 0.25 * current_atr
                atr_distance = entry - stop_loss
                
                rr_min, rr_max = config.get('risk.rr_targets.breakout', [2.0, 3.0])
                tp1 = entry + atr_distance * rr_min
                tp2 = entry + atr_distance * rr_max
                
                base_score = 1.0
                confirmations = []
                
                cvd_change = indicators.get('cvd_change')
                doi_pct = indicators.get('doi_pct')
                depth_imbalance = indicators.get('depth_imbalance')
                cvd_valid = indicators.get('cvd_valid', False)
                oi_valid = indicators.get('oi_valid', False)
                depth_valid = indicators.get('depth_valid', False)
                
                if cvd_valid and cvd_change is not None and cvd_change > 0:
                    base_score += 0.5
                    confirmations.append('cvd_direction')
                
                if oi_valid and doi_pct is not None and doi_pct > 5:
                    base_score += 0.5
                    confirmations.append('doi_growth')
                
                if depth_valid and depth_imbalance is not None and depth_imbalance > 0:
                    base_score += 0.5
                    confirmations.append('bid_pressure')
                
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
                        'impulse_high': float(impulse_high),
                        'impulse_low': float(impulse_low),
                        'ema9': float(ema9_val),
                        'ema20': float(ema20_val),
                        'ema200': float(current_ema200),
                        'adx': float(current_adx),
                        'atr_median': float(atr_median),
                        'entry_type': 'pullback',
                        'confirmations': confirmations,
                        'cvd_change': float(cvd_change) if cvd_change is not None else None,
                        'doi_pct': float(doi_pct) if doi_pct is not None else None,
                        'depth_imbalance': float(depth_imbalance) if depth_imbalance is not None else None
                    }
                )
                return signal
        
        strategy_logger.debug(f"    ❌ Нет пробоя high импульса или pullback к EMA9/20 при подходящем bias")
        return None
