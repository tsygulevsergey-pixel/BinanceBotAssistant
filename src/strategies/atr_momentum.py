from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr, calculate_ema, calculate_adx
from src.utils.time_of_day import get_adaptive_volume_threshold
from src.utils.sr_zones_15m import create_sr_zones, find_nearest_zone, calculate_stop_loss_from_zone


class ATRMomentumStrategy(BaseStrategy):
    """
    Стратегия #6: ATR Momentum (протяжка)
    
    Логика по мануалу:
    - Импульс-бар ≥1.4× ATR, close в верхн.20%
    - Follow-through; H4 тренд; до сопротивления ≥1.5 ATR
    - Триггер: пробой high импульса/флага ≥0.2–0.3 ATR или micro-pullback к EMA9/20
    - Подтверждения: объём>2×, CVD dir, ΔOI +1…+3%
    - Тайм-стоп: 6–8 баров без 0.5 ATR прогресса
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.momentum', {})
        super().__init__("ATR Momentum", strategy_config)
        
        self.impulse_atr = strategy_config.get('impulse_atr', 1.4)
        self.close_percentile = strategy_config.get('close_percentile', 20)  # top 20%
        self.min_distance_resistance = strategy_config.get('min_distance_resistance', 2.0)  # УЛУЧШЕНО: 2.0 ATR
        self.pullback_ema = strategy_config.get('pullback_ema', [9, 20])
        self.volume_threshold = strategy_config.get('volume_threshold', 2.0)
        self.breakout_atr_min = 0.2
        self.breakout_atr_max = 0.3
        self.timeframe = '15m'  # Для отслеживания импульсов
        
        # НОВЫЕ ФИЛЬТРЫ 2025:
        self.htf_ema200_check = strategy_config.get('htf_ema200_check', True)
        self.prefer_pin_bar = strategy_config.get('prefer_pin_bar', True)
        self.rsi_overextension_filter = strategy_config.get('rsi_overextension_filter', True)
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "breakout"
    
    def _check_higher_timeframe_trend(self, df_1h: Optional[pd.DataFrame], df_4h: Optional[pd.DataFrame], 
                                      direction: str) -> tuple[bool, bool]:
        """
        НОВОЕ 2025: Higher Timeframe Confirmation
        Проверяет тренд на 1H и 4H таймфреймах используя EMA200 (или EMA50 если данных мало)
        Возвращает: (подтверждено, есть_данные)
        """
        from src.indicators.technical import calculate_ema
        
        # Проверка 1H
        if df_1h is None or len(df_1h) < 50:
            strategy_logger.debug(f"    ⚠️ HTF: нет данных 1H (минимум 50 баров)")
            return (False, False)
        
        ema_period_1h = 200 if len(df_1h) >= 200 else 50
        
        # Проверка 4H
        if df_4h is None or len(df_4h) < 50:
            strategy_logger.debug(f"    ⚠️ HTF: нет данных 4H (минимум 50 баров)")
            return (False, False)
        
        ema_period_4h = 200 if len(df_4h) >= 200 else 50
        
        # Расчёт EMA
        ema_1h = calculate_ema(df_1h['close'], period=ema_period_1h)
        price_1h = df_1h['close'].iloc[-1]
        
        ema_4h = calculate_ema(df_4h['close'], period=ema_period_4h)
        price_4h = df_4h['close'].iloc[-1]
        
        if direction == 'LONG':
            trend_1h = price_1h > ema_1h.iloc[-1]
            trend_4h = price_4h > ema_4h.iloc[-1]
            confirmed = trend_1h and trend_4h
            strategy_logger.debug(f"    📊 HTF Check LONG: 1H={'✅' if trend_1h else '❌'}, 4H={'✅' if trend_4h else '❌'}")
            return (confirmed, True)
        else:  # SHORT
            trend_1h = price_1h < ema_1h.iloc[-1]
            trend_4h = price_4h < ema_4h.iloc[-1]
            confirmed = trend_1h and trend_4h
            strategy_logger.debug(f"    📊 HTF Check SHORT: 1H={'✅' if trend_1h else '❌'}, 4H={'✅' if trend_4h else '❌'}")
            return (confirmed, True)
    
    def _check_pin_bar(self, bar_data: Dict, direction: str) -> bool:
        """
        НОВОЕ 2025: Проверка Pin Bar паттерна
        Pin Bar = длинный хвост (тень) + маленькое тело
        """
        body_size = abs(bar_data['close'] - bar_data['open'])
        
        if direction == 'LONG':
            # Bullish Pin Bar: длинный нижний хвост
            lower_wick = min(bar_data['open'], bar_data['close']) - bar_data['low']
            upper_wick = bar_data['high'] - max(bar_data['open'], bar_data['close'])
            
            # Условия: нижний хвост > 2× тела И > верхнего хвоста
            if body_size > 0 and lower_wick > body_size * 2.0 and lower_wick > upper_wick * 1.5:
                return True
                
        else:  # SHORT
            # Bearish Pin Bar: длинный верхний хвост
            upper_wick = bar_data['high'] - max(bar_data['open'], bar_data['close'])
            lower_wick = min(bar_data['open'], bar_data['close']) - bar_data['low']
            
            # Условия: верхний хвост > 2× тела И > нижнего хвоста
            if body_size > 0 and upper_wick > body_size * 2.0 and upper_wick > lower_wick * 1.5:
                return True
        
        return False
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает в TREND режиме
        if regime != 'TREND':
            strategy_logger.debug(f"    ❌ Режим {regime}, требуется TREND")
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
        
        # НОВОЕ 2025: Проверка Pin Bar на impulse bar (бонус к score)
        impulse_bar_data = {
            'high': df['high'].iloc[impulse_bar_idx],
            'low': df['low'].iloc[impulse_bar_idx],
            'open': df['open'].iloc[impulse_bar_idx],
            'close': df['close'].iloc[impulse_bar_idx]
        }
        has_pin_bar = False
        if self.prefer_pin_bar:
            # Проверяем LONG Pin Bar на impulse bar
            has_pin_bar = self._check_pin_bar(impulse_bar_data, 'LONG')
            if has_pin_bar:
                strategy_logger.debug(f"    ✅ Pin Bar обнаружен на импульс-баре {impulse_bar_idx}!")
        
        # Объём
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Проверка объёма
        # Адаптивный порог объема по времени суток
        adaptive_volume_threshold = get_adaptive_volume_threshold(df['open_time'].iloc[-1], self.volume_threshold)
        
        if volume_ratio < adaptive_volume_threshold:
            strategy_logger.debug(f"    ❌ Объем низкий: {volume_ratio:.2f}x < {adaptive_volume_threshold:.2f}x (адаптивный)")
            return None
        
        # Проверка расстояния до сопротивления (упрощённо - проверяем есть ли место)
        # Сопротивление = недавний максимум
        resistance = df['high'].tail(50).max()
        distance_to_resistance = (resistance - current_close) / current_atr
        
        if distance_to_resistance < self.min_distance_resistance:
            strategy_logger.debug(f"    ❌ Слишком близко к сопротивлению: {distance_to_resistance:.2f} ATR < {self.min_distance_resistance} ATR")
            return None
        
        # НОВОЕ 2025: RSI Overextension Filter
        if self.rsi_overextension_filter:
            rsi_14 = indicators.get('15m', {}).get('rsi_14') if isinstance(indicators.get('15m'), dict) else None
            
            # Если RSI не в закешированных индикаторах, вычисляем напрямую
            if rsi_14 is None:
                from src.indicators.technical import calculate_rsi
                rsi_14 = calculate_rsi(df['close'], period=14)
            
            if rsi_14 is not None and len(rsi_14) > 0:
                current_rsi = rsi_14.iloc[-1]
                
                # Для LONG: избегать overbought (RSI > 70)
                if bias != 'Bearish' and current_rsi > 70:
                    strategy_logger.debug(f"    ❌ RSI overbought: {current_rsi:.1f} > 70 (избегаем покупок на экстремумах)")
                    return None
                
                # Для SHORT: избегать oversold (RSI < 30)
                if bias == 'Bearish' and current_rsi < 30:
                    strategy_logger.debug(f"    ❌ RSI oversold: {current_rsi:.1f} < 30 (избегаем продаж на экстремумах)")
                    return None
                
                strategy_logger.debug(f"    ✅ RSI в норме: {current_rsi:.1f} (30-70 диапазон)")
        
        # НОВОЕ 2025: HTF Trend Confirmation
        if self.htf_ema200_check:
            df_1h = indicators.get('1h')  # ИСПРАВЛЕНО: правильный ключ
            df_4h = indicators.get('4h')  # ИСПРАВЛЕНО: правильный ключ
            htf_confirmed, htf_data_available = self._check_higher_timeframe_trend(df_1h, df_4h, 'LONG')
            
            if htf_data_available and not htf_confirmed:
                strategy_logger.debug(f"    ❌ LONG импульс OK, но Higher TF не подтверждает тренд (1H/4H EMA200)")
                return None
            
            if htf_confirmed:
                strategy_logger.debug(f"    ✅ Higher TF подтверждает LONG тренд (1H+4H > EMA200)")
        
        # LONG: пробой high импульса или pullback к EMA9/20
        if bias != 'Bearish':
            # Вариант 1: пробой high импульса ≥0.2-0.3 ATR
            if (current_high > impulse_high and 
                (current_high - impulse_high) >= self.breakout_atr_min * current_atr):
                
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
                
                # НОВОЕ 2025: Pin Bar бонус
                if has_pin_bar:
                    base_score += 0.5
                    confirmations.append('pin_bar_impulse')
                    strategy_logger.debug(f"    ✅ Pin Bar на импульсе - бонус +0.5 к score")
                
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
                        'has_pin_bar': has_pin_bar,  # НОВОЕ 2025
                        'htf_check_enabled': self.htf_ema200_check,  # НОВОЕ 2025
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
                
                # НОВОЕ 2025: Pin Bar бонус
                if has_pin_bar:
                    base_score += 0.5
                    confirmations.append('pin_bar_impulse')
                    strategy_logger.debug(f"    ✅ Pin Bar на импульсе - бонус +0.5 к score")
                
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
                        'has_pin_bar': has_pin_bar,  # НОВОЕ 2025
                        'htf_check_enabled': self.htf_ema200_check,  # НОВОЕ 2025
                        'cvd_change': float(cvd_change) if cvd_change is not None else None,
                        'doi_pct': float(doi_pct) if doi_pct is not None else None,
                        'depth_imbalance': float(depth_imbalance) if depth_imbalance is not None else None
                    }
                )
                return signal
        
        strategy_logger.debug(f"    ❌ Нет пробоя high импульса или pullback к EMA9/20 при подходящем bias")
        return None
