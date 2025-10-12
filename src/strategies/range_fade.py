from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr, calculate_rsi
from src.utils.reclaim_checker import check_range_reclaim
from src.utils.sr_zones_15m import create_sr_zones, find_nearest_zone, calculate_stop_loss_from_zone


class RangeFadeStrategy(BaseStrategy):
    """
    Стратегия #8: Range Fade (от границ диапазона)
    
    Логика по мануалу:
    - RANGE-детектор; качественные границы (≥2–3 теста)
    - Конфлюэнс с VA/VWAP/H4 свинг
    - IB не чрезмерно широкий
    - Триггер/стоп/тейки: как в VWAP MR
    - Подтверждения: CVD-дивергенция, imbalance flip, абсорбция-прокси
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.range_fade', {})
        super().__init__("Range Fade", strategy_config)
        
        self.min_tests = strategy_config.get('min_tests', 2)
        self.time_stop = strategy_config.get('time_stop', [6, 8])
        self.reclaim_bars = strategy_config.get('reclaim_bars', 2)  # Hold N bars для reclaim
        self.timeframe = '15m'
        self.lookback_bars = 100  # Для определения границ рейнджа
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"
    
    def _find_range_boundaries_with_h4(self, df: pd.DataFrame, vah: float, val: float, vwap: float, 
                                        h4_high: float, h4_low: float) -> Optional[Dict]:
        """
        Найти качественные границы рейнджа с ≥2-3 теста и confluence с VA/VWAP/H4 свинг
        Согласно мануалу: границы должны совпадать с VAH/VAL/VWAP/H4 свингами
        Использует РЕАЛЬНЫЕ H4 swing levels
        """
        from src.indicators.technical import calculate_atr
        
        recent_data = df.tail(self.lookback_bars)
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Ищем resistance: должен быть confluence с VAH или H4 swing high
        resistance_candidates = []
        
        # Проверка VAH как resistance
        vah_tests = ((recent_data['high'] >= vah - 0.1*current_atr) & 
                     (recent_data['high'] <= vah + 0.1*current_atr)).sum()
        if vah_tests >= self.min_tests:
            resistance_candidates.append({'level': vah, 'tests': vah_tests, 'type': 'VAH'})
        
        # Проверка H4 swing high как resistance
        h4_high_tests = ((recent_data['high'] >= h4_high - 0.2*current_atr) & 
                         (recent_data['high'] <= h4_high + 0.2*current_atr)).sum()
        if h4_high_tests >= self.min_tests:
            resistance_candidates.append({'level': h4_high, 'tests': h4_high_tests, 'type': 'H4_high'})
        
        # Ищем support: должен быть confluence с VAL или H4 swing low
        support_candidates = []
        
        # Проверка VAL как support
        val_tests = ((recent_data['low'] >= val - 0.1*current_atr) & 
                     (recent_data['low'] <= val + 0.1*current_atr)).sum()
        if val_tests >= self.min_tests:
            support_candidates.append({'level': val, 'tests': val_tests, 'type': 'VAL'})
        
        # Проверка H4 swing low как support
        h4_low_tests = ((recent_data['low'] >= h4_low - 0.2*current_atr) & 
                        (recent_data['low'] <= h4_low + 0.2*current_atr)).sum()
        if h4_low_tests >= self.min_tests:
            support_candidates.append({'level': h4_low, 'tests': h4_low_tests, 'type': 'H4_low'})
        
        # ТРЕБОВАНИЕ: должно быть минимум 2 confluence для каждой границы
        # (например VAH + H4_high или VAL + H4_low)
        if len(resistance_candidates) < 2 or len(support_candidates) < 2:
            return None
        
        # Выбираем лучшие уровни
        best_resistance = max(resistance_candidates, key=lambda x: x['tests'])
        best_support = max(support_candidates, key=lambda x: x['tests'])
        
        # Дополнительная проверка: уровни должны быть достаточно близки друг к другу
        # (показывает confluence)
        res_confluence = any(abs(best_resistance['level'] - c['level']) <= 0.2*current_atr 
                            for c in resistance_candidates if c != best_resistance)
        sup_confluence = any(abs(best_support['level'] - c['level']) <= 0.2*current_atr 
                            for c in support_candidates if c != best_support)
        
        if not (res_confluence and sup_confluence):
            return None
        
        return {
            'resistance': best_resistance['level'],
            'support': best_support['level'],
            'resistance_tests': best_resistance['tests'],
            'support_tests': best_support['tests'],
            'resistance_type': best_resistance['type'],
            'support_type': best_support['type']
        }
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает только в RANGE режиме
        if regime not in ['RANGE', 'CHOP']:
            strategy_logger.debug(f"    ❌ Режим {regime}, требуется RANGE или CHOP")
            return None
        
        if len(df) < self.lookback_bars:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется {self.lookback_bars}")
            return None
        
        # Получить VA/VWAP для confluence проверки
        from src.indicators.vwap import calculate_daily_vwap
        from src.indicators.volume_profile import calculate_volume_profile
        
        vwap, vwap_upper, vwap_lower = calculate_daily_vwap(df)
        vp_result = calculate_volume_profile(df, num_bins=50)
        vah = vp_result['vah']
        val = vp_result['val']
        
        # Получить H4 swings из indicators (реальные 4h данные)
        h4_swing_high = indicators.get('h4_swing_high')
        h4_swing_low = indicators.get('h4_swing_low')
        
        if h4_swing_high is None or h4_swing_low is None:
            strategy_logger.debug(f"    ❌ Нет H4 swing данных")
            return None
        
        # Найти границы рейнджа с confluence проверкой (передаём реальные H4 swings)
        range_bounds = self._find_range_boundaries_with_h4(df, vah, val, vwap.iloc[-1], h4_swing_high, h4_swing_low)
        if range_bounds is None:
            strategy_logger.debug(f"    ❌ Нет качественных границ рейнджа с ≥{self.min_tests} теста и confluence с VA/H4")
            return None
        
        # Проверка IB width (не чрезмерно широкий)
        # IB = первый час дня (упрощённо - последние 4 бара на 15m)
        ib_high = df['high'].tail(4).max()
        ib_low = df['low'].tail(4).min()
        ib_width = ib_high - ib_low
        
        from src.indicators.technical import calculate_atr
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # IB не должен быть >1.5 ATR (чрезмерно широкий)
        if ib_width > 1.5 * current_atr:
            strategy_logger.debug(f"    ❌ IB чрезмерно широкий: {ib_width:.6f} > 1.5·ATR ({1.5 * current_atr:.6f})")
            return None
        
        resistance = range_bounds['resistance']
        support = range_bounds['support']
        
        # ATR для стопов и RSI для divergence
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        rsi = calculate_rsi(df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_rsi = rsi.iloc[-1] if rsi is not None and not pd.isna(rsi.iloc[-1]) else 50
        
        # Вспомогательная функция для RSI divergence detection
        def detect_rsi_divergence(df, rsi, lookback=10):
            """Обнаружить RSI дивергенцию"""
            if len(df) < lookback:
                return None, None
            
            # Для LONG: price makes new low, RSI не делает new low (bullish divergence)
            recent_price_low = df['low'].tail(lookback).min()
            recent_rsi_low = rsi.tail(lookback).min()
            current_price = df['close'].iloc[-1]
            current_rsi_val = rsi.iloc[-1]
            
            # Bullish divergence: цена делает lower low, RSI делает higher low
            price_idx_min = df['low'].tail(lookback).idxmin()
            rsi_idx_min = rsi.tail(lookback).idxmin()
            
            bullish_div = False
            if price_idx_min != rsi_idx_min:
                # Проверяем: есть ли второй минимум цены ниже первого, но RSI выше
                price_lows = df['low'].tail(lookback).nsmallest(2)
                rsi_at_lows = rsi.loc[price_lows.index]
                if len(price_lows) >= 2 and price_lows.iloc[0] < price_lows.iloc[1]:
                    if rsi_at_lows.iloc[0] > rsi_at_lows.iloc[1]:
                        bullish_div = True
            
            # Для SHORT: price makes new high, RSI не делает new high (bearish divergence)
            recent_price_high = df['high'].tail(lookback).max()
            recent_rsi_high = rsi.tail(lookback).max()
            
            price_idx_max = df['high'].tail(lookback).idxmax()
            rsi_idx_max = rsi.tail(lookback).idxmax()
            
            bearish_div = False
            if price_idx_max != rsi_idx_max:
                price_highs = df['high'].tail(lookback).nlargest(2)
                rsi_at_highs = rsi.loc[price_highs.index]
                if len(price_highs) >= 2 and price_highs.iloc[0] > price_highs.iloc[1]:
                    if rsi_at_highs.iloc[0] < rsi_at_highs.iloc[1]:
                        bearish_div = True
            
            return bullish_div, bearish_div
        
        bullish_rsi_div, bearish_rsi_div = detect_rsi_divergence(df, rsi, lookback=10)
        
        # LONG fade: цена ОКОЛО support + RECLAIM механизм
        # 1. Proximity check: цена около support (в пределах 0.3 ATR)
        near_support = current_close <= support + 0.3 * current_atr
        
        # 2. RSI extreme zone: RSI < 30 для LONG
        rsi_oversold = current_rsi < 30
        
        if near_support and rsi_oversold:
            # 2. RECLAIM проверка: цена была ниже support, вернулась и удержалась
            long_reclaim = check_range_reclaim(
                df=df,
                range_low=support,
                range_high=resistance,
                direction='long',
                hold_bars=self.reclaim_bars
            )
            
            if long_reclaim:
                entry = current_close
                
                # Расчет зон S/R для точного стопа
                sr_zones = create_sr_zones(df, current_atr, buffer_mult=0.25)
                nearest_zone = find_nearest_zone(entry, sr_zones, 'LONG')
                stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, current_atr, 'LONG', fallback_mult=2.0, max_distance_atr=5.0)
                
                # Расчет дистанции и тейков 1R и 2R
                atr_distance = abs(entry - stop_loss)
                tp1 = entry + atr_distance * 1.0  # 1R
                tp2 = entry + atr_distance * 2.0  # 2R
                
                base_score = 1.0
                confirmations = []
                
                cvd_change = indicators.get('cvd_change')
                depth_imbalance = indicators.get('depth_imbalance')
                cvd_valid = indicators.get('cvd_valid', False)
                depth_valid = indicators.get('depth_valid', False)
                
                # RSI divergence добавляет +0.5 score
                if bullish_rsi_div:
                    base_score += 0.5
                    confirmations.append('rsi_bullish_divergence')
                
                if cvd_valid and cvd_change is not None and cvd_change < 0:
                    base_score += 0.5
                    confirmations.append('cvd_divergence')
                
                if depth_valid and depth_imbalance is not None and depth_imbalance < 0:
                    base_score += 0.5
                    confirmations.append('ask_pressure_fade')
                
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
                    metadata={
                        'resistance': float(resistance),
                        'support': float(support),
                        'resistance_tests': int(range_bounds['resistance_tests']),
                        'support_tests': int(range_bounds['support_tests']),
                        'rsi': float(current_rsi),
                        'rsi_oversold': rsi_oversold,
                        'bullish_rsi_div': bullish_rsi_div,
                        'fade_from': 'support',
                        'reclaim_bars': self.reclaim_bars,
                        'confirmations': confirmations,
                        'cvd_change': float(cvd_change) if cvd_change is not None else None,
                        'depth_imbalance': float(depth_imbalance) if depth_imbalance is not None else None
                    }
                )
                return signal
        
        # SHORT fade: цена ОКОЛО resistance + RECLAIM механизм
        # 1. Proximity check: цена около resistance (в пределах 0.3 ATR)
        near_resistance = current_close >= resistance - 0.3 * current_atr
        
        # 2. RSI extreme zone: RSI > 70 для SHORT
        rsi_overbought = current_rsi > 70
        
        if near_resistance and rsi_overbought:
            # 2. RECLAIM проверка: цена была выше resistance, вернулась и удержалась
            short_reclaim = check_range_reclaim(
                df=df,
                range_low=support,
                range_high=resistance,
                direction='short',
                hold_bars=self.reclaim_bars
            )
            
            if short_reclaim:
                entry = current_close
                
                # Расчет зон S/R для точного стопа
                sr_zones = create_sr_zones(df, current_atr, buffer_mult=0.25)
                nearest_zone = find_nearest_zone(entry, sr_zones, 'SHORT')
                stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, current_atr, 'SHORT', fallback_mult=2.0, max_distance_atr=5.0)
                
                # Расчет дистанции и тейков 1R и 2R
                atr_distance = abs(stop_loss - entry)
                tp1 = entry - atr_distance * 1.0  # 1R
                tp2 = entry - atr_distance * 2.0  # 2R
                
                base_score = 1.0
                confirmations = []
                
                cvd_change = indicators.get('cvd_change')
                depth_imbalance = indicators.get('depth_imbalance')
                cvd_valid = indicators.get('cvd_valid', False)
                depth_valid = indicators.get('depth_valid', False)
                
                # RSI divergence добавляет +0.5 score
                if bearish_rsi_div:
                    base_score += 0.5
                    confirmations.append('rsi_bearish_divergence')
                
                if cvd_valid and cvd_change is not None and cvd_change > 0:
                    base_score += 0.5
                    confirmations.append('cvd_divergence')
                
                if depth_valid and depth_imbalance is not None and depth_imbalance > 0:
                    base_score += 0.5
                    confirmations.append('bid_pressure_fade')
                
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
                    metadata={
                        'resistance': float(resistance),
                        'support': float(support),
                        'resistance_tests': int(range_bounds['resistance_tests']),
                        'support_tests': int(range_bounds['support_tests']),
                        'rsi': float(current_rsi),
                        'rsi_overbought': rsi_overbought,
                        'bearish_rsi_div': bearish_rsi_div,
                        'fade_from': 'resistance',
                        'reclaim_bars': self.reclaim_bars,
                        'confirmations': confirmations,
                        'cvd_change': float(cvd_change) if cvd_change is not None else None,
                        'depth_imbalance': float(depth_imbalance) if depth_imbalance is not None else None
                    }
                )
                return signal
        
        strategy_logger.debug(f"    ❌ Цена не около границ рейнджа или нет reclaim подтверждения")
        return None
