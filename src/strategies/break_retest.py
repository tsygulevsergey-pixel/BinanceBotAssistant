from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr, calculate_adx
from src.utils.sr_zones_15m import create_sr_zones, find_nearest_zone, calculate_stop_loss_from_zone


class BreakRetestStrategy(BaseStrategy):
    """
    Стратегия #5: Break & Retest
    
    Логика по мануалу:
    - Пробой с close ≥0.25 ATR и объёмом >1.5–2×
    - Зона ретеста = экстремум±0.2–0.3 ATR ∩ AVWAP(бар пробоя)
    - Триггер: 50% лимитом в зоне, 50% — по подтверждению
    - Стоп: за свинг-реакцией +0.2–0.3 ATR
    - Подтверждения: CVD flip, imbalance flip/refill, OI не падает
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.retest', {})
        super().__init__("Break & Retest", strategy_config)
        
        self.breakout_atr = strategy_config.get('breakout_atr', 0.25)
        self.zone_atr = strategy_config.get('zone_atr', [0.2, 0.3])
        self.volume_threshold = strategy_config.get('volume_threshold', 1.5)
        self.split_ratio = strategy_config.get('split_ratio', 0.5)  # 50/50
        self.timeframe = '15m'
        self.breakout_lookback = 20  # Ищем пробои за последние 20 баров
        
        # ФАЗА 1: Разные ADX пороги для разных режимов
        self.adx_threshold_trend = config.get('market_detector.trend.adx_threshold_trend', 25)  # Строже для TREND
        self.adx_threshold_squeeze = config.get('market_detector.trend.adx_threshold_squeeze', 15)  # Мягче для SQUEEZE
        self.adx_threshold_default = config.get('market_detector.trend.adx_threshold', 20)  # По умолчанию
        
        # ФАЗА 1: Разные volume требования для режимов
        self.volume_threshold_trend = config.get('strategies.retest.volume_threshold_trend', 1.8)  # Строже для TREND
        self.volume_threshold_squeeze = config.get('strategies.retest.volume_threshold_squeeze', 1.2)  # Мягче для SQUEEZE
        
        # ФАЗА 1: ATR-based TP/SL опция
        self.use_atr_based_tp_sl = strategy_config.get('use_atr_based_tp_sl', True)
        self.atr_tp1_multiplier = strategy_config.get('atr_tp1_multiplier', 1.5)
        self.atr_tp2_multiplier = strategy_config.get('atr_tp2_multiplier', 2.5)
        self.atr_sl_multiplier = strategy_config.get('atr_sl_multiplier', 1.0)
        
        # ФАЗА 1: Фильтры подтверждения
        self.require_pin_bar_or_engulfing = strategy_config.get('require_pin_bar_or_engulfing', False)
        self.htf_ema200_check = strategy_config.get('htf_ema200_check', True)
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "pullback"
    
    def _find_swing_high_low(self, df: pd.DataFrame, end_pos: int, lookback: int = 20, buffer: int = 3) -> Dict:
        """Найти swing high/low с буфером N баров
        Args:
            end_pos: ПОЛОЖИТЕЛЬНЫЙ индекс окончания поиска
        """
        # Проверка границ
        start_pos = max(buffer, end_pos - lookback)
        
        swing_high = None
        swing_high_idx = None
        swing_low = None
        swing_low_idx = None
        
        # Ищем swing high (пик с buffer баров с каждой стороны)
        for i in range(start_pos, end_pos - buffer):
            if i < buffer or i + buffer >= len(df):
                continue
            
            high_val = df['high'].iloc[i]
            is_swing_high = True
            
            # Проверяем, что это локальный максимум
            for j in range(i - buffer, i + buffer + 1):
                if j != i and df['high'].iloc[j] >= high_val:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                swing_high = high_val
                swing_high_idx = i
        
        # Ищем swing low (впадина с buffer баров с каждой стороны)
        for i in range(start_pos, end_pos - buffer):
            if i < buffer or i + buffer >= len(df):
                continue
            
            low_val = df['low'].iloc[i]
            is_swing_low = True
            
            # Проверяем, что это локальный минимум
            for j in range(i - buffer, i + buffer + 1):
                if j != i and df['low'].iloc[j] <= low_val:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                swing_low = low_val
                swing_low_idx = i
        
        return {
            'swing_high': swing_high,
            'swing_high_idx': swing_high_idx,
            'swing_low': swing_low,
            'swing_low_idx': swing_low_idx
        }
    
    def _check_higher_timeframe_trend(self, df_1h: Optional[pd.DataFrame], df_4h: Optional[pd.DataFrame], 
                                      direction: str) -> tuple[bool, bool]:
        """
        ФАЗА 1: Higher Timeframe Confirmation (ИСПРАВЛЕНО - graceful degradation)
        Проверяет тренд на 1H и 4H таймфреймах используя EMA200 (или меньший период если данных недостаточно)
        Возвращает: (подтверждено, есть_данные)
        """
        from src.indicators.technical import calculate_ema
        
        # ИСПРАВЛЕНИЕ: Graceful degradation - используем максимальный доступный период
        # Проверка 1H: предпочитаем EMA200, но используем EMA50 если данных мало
        if df_1h is None or len(df_1h) < 50:
            strategy_logger.debug(f"    ⚠️ Higher TF: нет данных 1H (минимум 50 баров, есть {len(df_1h) if df_1h is not None else 0})")
            return (False, False)  # Нет подтверждения, нет данных
        
        ema_period_1h = 200 if len(df_1h) >= 200 else 50
        if ema_period_1h == 50:
            strategy_logger.debug(f"    📊 HTF 1H: используем EMA50 (недостаточно данных для EMA200, есть {len(df_1h)} баров)")
        
        # ИСПРАВЛЕНИЕ: Для 4H также graceful degradation
        if df_4h is None or len(df_4h) < 50:
            strategy_logger.debug(f"    ⚠️ Higher TF: нет данных 4H (минимум 50 баров, есть {len(df_4h) if df_4h is not None else 0})")
            return (False, False)  # Нет подтверждения, нет данных
        
        ema_period_4h = 200 if len(df_4h) >= 200 else 50
        if ema_period_4h == 50:
            strategy_logger.debug(f"    📊 HTF 4H: используем EMA50 (недостаточно данных для EMA200, есть {len(df_4h)} баров)")
        
        # Расчёт EMA с адаптивным периодом
        ema_1h = calculate_ema(df_1h['close'], period=ema_period_1h)
        price_1h = df_1h['close'].iloc[-1]
        
        ema_4h = calculate_ema(df_4h['close'], period=ema_period_4h)
        price_4h = df_4h['close'].iloc[-1]
        
        if direction == 'LONG':
            trend_1h = price_1h > ema_1h.iloc[-1]
            trend_4h = price_4h > ema_4h.iloc[-1]
            confirmed = trend_1h and trend_4h
            strategy_logger.debug(f"    📊 HTF Check: 1H={'✅' if trend_1h else '❌'} (price={price_1h:.2f} vs EMA{ema_period_1h}={ema_1h.iloc[-1]:.2f}), "
                                f"4H={'✅' if trend_4h else '❌'} (price={price_4h:.2f} vs EMA{ema_period_4h}={ema_4h.iloc[-1]:.2f})")
            return (confirmed, True)
        else:  # SHORT
            trend_1h = price_1h < ema_1h.iloc[-1]
            trend_4h = price_4h < ema_4h.iloc[-1]
            confirmed = trend_1h and trend_4h
            strategy_logger.debug(f"    📊 HTF Check: 1H={'✅' if trend_1h else '❌'} (price={price_1h:.2f} vs EMA{ema_period_1h}={ema_1h.iloc[-1]:.2f}), "
                                f"4H={'✅' if trend_4h else '❌'} (price={price_4h:.2f} vs EMA{ema_period_4h}={ema_4h.iloc[-1]:.2f})")
            return (confirmed, True)
    
    def _check_bollinger_position(self, df: pd.DataFrame, direction: str) -> bool:
        """
        ФАЗА 2: Bollinger Bands фильтр
        Проверяет, что цена у внешней полосы (сильный импульс)
        """
        from src.indicators.technical import calculate_bollinger_bands
        
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(df['close'], period=20, std=2.0)
        current_close = df['close'].iloc[-1]
        
        if direction == 'LONG':
            # Для LONG: цена должна быть близко к верхней полосе
            distance_to_upper = (bb_upper.iloc[-1] - current_close) / bb_upper.iloc[-1]
            return distance_to_upper <= 0.02  # В пределах 2% от верхней полосы
        else:  # SHORT
            # Для SHORT: цена должна быть близко к нижней полосе
            distance_to_lower = (current_close - bb_lower.iloc[-1]) / current_close
            return distance_to_lower <= 0.02  # В пределах 2% от нижней полосы
    
    def _check_pin_bar(self, bar: Dict, direction: str) -> bool:
        """
        ФАЗА 1: Проверка Pin Bar паттерна
        Pin Bar = длинный хвост (тень) + маленькое тело
        """
        body_size = abs(bar['close'] - bar['open'])
        
        if direction == 'LONG':
            # Bullish Pin Bar: длинный нижний хвост
            lower_wick = min(bar['open'], bar['close']) - bar['low']
            upper_wick = bar['high'] - max(bar['open'], bar['close'])
            
            # Условия: нижний хвост > 2× тела И > верхнего хвоста
            if body_size > 0 and lower_wick > body_size * 2.0 and lower_wick > upper_wick * 1.5:
                return True
                
        else:  # SHORT
            # Bearish Pin Bar: длинный верхний хвост
            upper_wick = bar['high'] - max(bar['open'], bar['close'])
            lower_wick = min(bar['open'], bar['close']) - bar['low']
            
            # Условия: верхний хвост > 2× тела И > нижнего хвоста
            if body_size > 0 and upper_wick > body_size * 2.0 and upper_wick > lower_wick * 1.5:
                return True
        
        return False
    
    def _check_engulfing(self, prev_bar: Dict, current_bar: Dict, direction: str) -> bool:
        """
        ФАЗА 1: Проверка Engulfing (поглощающей) свечи
        Текущая свеча полностью поглощает предыдущую
        """
        if direction == 'LONG':
            # Bullish Engulfing: текущая свеча поглощает предыдущую медвежью
            prev_bearish = prev_bar['close'] < prev_bar['open']
            current_bullish = current_bar['close'] > current_bar['open']
            
            engulfs = (current_bar['close'] > prev_bar['open'] and 
                      current_bar['open'] < prev_bar['close'])
            
            return prev_bearish and current_bullish and engulfs
            
        else:  # SHORT
            # Bearish Engulfing: текущая свеча поглощает предыдущую бычью
            prev_bullish = prev_bar['close'] > prev_bar['open']
            current_bearish = current_bar['close'] < current_bar['open']
            
            engulfs = (current_bar['close'] < prev_bar['open'] and 
                      current_bar['open'] > prev_bar['close'])
            
            return prev_bullish and current_bearish and engulfs
        
        return False
    
    def _check_retest_quality(self, breakout: Dict, retest_bars: list, breakout_level: float) -> float:
        """
        ФАЗА 1+2: Проверка качества ретеста (УЛУЧШЕНО)
        Добавлены проверки Pin Bar и Engulfing patterns
        Возвращает качество 0-1 (0=плохо, 1=отлично)
        """
        if not retest_bars or len(retest_bars) == 0:
            return 0.0
        
        quality_score = 1.0
        direction = breakout['direction']
        
        # 1. Проверка глубины проникновения
        max_penetration = 0
        for bar in retest_bars:
            if direction == 'LONG':
                # Для LONG: насколько низко ушли ниже уровня
                penetration = (breakout_level - bar['low']) / breakout['atr']
                if penetration > max_penetration:
                    max_penetration = penetration
            else:  # SHORT
                penetration = (bar['high'] - breakout_level) / breakout['atr']
                if penetration > max_penetration:
                    max_penetration = penetration
        
        # Штраф за глубокое проникновение (>0.3 ATR плохо)
        if max_penetration > 0.3:
            quality_score -= 0.3
        
        # 2. НОВОЕ: Проверка Pin Bar pattern (СИЛЬНЫЙ сигнал подтверждения)
        has_pin_bar = False
        for bar in retest_bars:
            if self._check_pin_bar(bar, direction):
                has_pin_bar = True
                quality_score += 0.3  # БОНУС за Pin Bar!
                strategy_logger.debug(f"    ✅ Pin Bar обнаружен на ретесте!")
                break
        
        # 3. НОВОЕ: Проверка Engulfing pattern (если есть минимум 2 свечи)
        has_engulfing = False
        if len(retest_bars) >= 2:
            for i in range(1, len(retest_bars)):
                if self._check_engulfing(retest_bars[i-1], retest_bars[i], direction):
                    has_engulfing = True
                    quality_score += 0.3  # БОНУС за Engulfing!
                    strategy_logger.debug(f"    ✅ Engulfing pattern обнаружен на ретесте!")
                    break
        
        # 4. Проверка базового rejection (если нет Pin Bar / Engulfing)
        if not has_pin_bar and not has_engulfing:
            has_rejection = False
            for bar in retest_bars:
                if direction == 'LONG':
                    wick_size = min(bar['open'], bar['close']) - bar['low']
                    body_size = abs(bar['close'] - bar['open'])
                    if wick_size > body_size * 0.5:
                        has_rejection = True
                        break
                else:
                    wick_size = bar['high'] - max(bar['open'], bar['close'])
                    body_size = abs(bar['close'] - bar['open'])
                    if wick_size > body_size * 0.5:
                        has_rejection = True
                        break
            
            if not has_rejection:
                quality_score -= 0.3  # ШТРАФ если нет НИКАКИХ признаков rejection
        
        return max(0.0, min(1.5, quality_score))  # Макс 1.5 если есть Pin Bar + Engulfing
    
    def _calculate_improved_score(self, base_score: float, breakout: Dict, regime: str, 
                                   bias: str, retest_quality: float, 
                                   bb_good: bool, htf_confirmed: bool, htf_has_data: bool,
                                   rsi_confirmed: bool = True,
                                   market_structure_good: bool = True) -> float:
        """
        ФАЗА 2+3: Улучшенная score система
        """
        score = base_score
        
        # ФАЗА 2: Бонусы в зависимости от режима
        if regime == 'TREND':
            # ADX бонусы (для TREND)
            adx = breakout.get('adx', 0)
            if adx > 30:
                score += 1.0  # Очень сильный тренд
            elif adx > 25:
                score += 0.5  # Сильный тренд
            
            # ADX rising бонус (уже проверено в _find_recent_breakout)
            score += 0.5
            
            # Volume бонусы
            vol_ratio = breakout.get('volume_ratio', 1.0)
            if vol_ratio > 2.0:
                score += 1.0  # Мощный объем
            elif vol_ratio > 1.5:
                score += 0.5
            
            # Higher TF confirmation
            if htf_has_data:
                if htf_confirmed:
                    score += 1.0  # Большой бонус если подтверждено
                # Если есть данные но не подтверждено - уже заблокировано в check_signal
            else:
                score -= 0.5  # Небольшой штраф если нет данных для проверки
            
            # Bollinger position
            if bb_good:
                score += 0.5
            
            # Retest quality
            score += retest_quality * 0.5
            
        elif regime == 'SQUEEZE':
            # SQUEEZE бонусы (мягче)
            if breakout.get('volume_ratio', 1.0) > 1.5:
                score += 0.5
            
            score += retest_quality * 0.3
        
        # ФАЗА 3: RSI и Market Structure бонусы
        if rsi_confirmed:
            score += 0.5
        
        if market_structure_good:
            score += 0.5
        
        # Bias бонусы/штрафы
        if bias.lower() == 'neutral':
            score += 0.5  # Нейтральный bias лучше
        elif bias.lower() == 'bearish':
            score -= 0.5  # Небольшой штраф (основной уже в check_signal для TREND)
        
        return score
    
    def _check_rsi_confirmation(self, df: pd.DataFrame, direction: str) -> bool:
        """
        ФАЗА 3: RSI фильтр
        Проверяет импульс через RSI
        """
        from src.indicators.technical import calculate_rsi
        
        rsi = calculate_rsi(df['close'], period=14)
        current_rsi = rsi.iloc[-1]
        
        if direction == 'LONG':
            return current_rsi > 45  # Слабый импульс вверх
        else:  # SHORT
            return current_rsi < 55  # Слабый импульс вниз
    
    def _check_market_structure(self, df: pd.DataFrame, direction: str) -> bool:
        """
        ФАЗА 3: Market Structure проверка
        Проверяет формирование Higher Highs / Lower Lows
        """
        if len(df) < 10:
            return True  # Недостаточно данных - не блокируем
        
        highs = df['high'].tail(6).values
        lows = df['low'].tail(6).values
        
        if direction == 'LONG':
            # Для LONG: Higher Highs и Higher Lows
            hh = highs[-1] >= highs[-3] >= highs[-5]
            hl = lows[-1] >= lows[-3] >= lows[-5]
            return hh or hl  # Хотя бы одно условие
        else:  # SHORT
            # Для SHORT: Lower Lows и Lower Highs
            ll = lows[-1] <= lows[-3] <= lows[-5]
            lh = highs[-1] <= highs[-3] <= highs[-5]
            return ll or lh
    
    def _find_recent_breakout(self, df: pd.DataFrame, atr: pd.Series, vwap: pd.Series, adx: pd.Series, 
                              regime: str, adx_threshold: float, volume_threshold: float) -> Optional[Dict]:
        """Найти недавний пробой с использованием swing levels и ADX фильтром"""
        df_len = len(df)
        
        for i in range(-self.breakout_lookback, -1):  # До -1, чтобы не включать текущий бар
            if abs(i) >= df_len:
                continue
            
            # Конвертируем отрицательный индекс в положительный
            pos_idx = df_len + i
            
            bar_close = df['close'].iloc[i]
            bar_high = df['high'].iloc[i]
            bar_low = df['low'].iloc[i]
            bar_volume = df['volume'].iloc[i]
            bar_atr = atr.iloc[i]
            bar_vwap = vwap.iloc[i] if vwap is not None and i < len(vwap) else None
            bar_adx = adx.iloc[i]
            
            # Найти swing high/low перед этим баром (передаем ПОЛОЖИТЕЛЬНЫЙ индекс!)
            swings = self._find_swing_high_low(df, pos_idx, lookback=20, buffer=3)
            
            if swings['swing_high'] is None and swings['swing_low'] is None:
                continue
            
            # Средний объём
            if i - 20 < -len(df):
                continue
            avg_vol = df['volume'].iloc[i-20:i].mean()
            vol_ratio = bar_volume / avg_vol if avg_vol > 0 else 0
            
            # ADX фильтр: ADX > threshold для валидного breakout (зависит от режима)
            if bar_adx < adx_threshold:
                strategy_logger.debug(f"    ⚠️ Пропуск пробоя на баре {i}: ADX слишком слабый ({bar_adx:.1f} < {adx_threshold})")
                continue
            
            # ФАЗА 1: Проверка что ADX растет (только для TREND режима)
            # Требование: ADX[-1] > ADX[-3] (текущий ADX выше чем 2 бара назад)
            if regime == 'TREND' and abs(i) >= 3:
                adx_prev_2 = adx.iloc[i - 2]  # 2 бара назад
                adx_rising = bar_adx > adx_prev_2
                if not adx_rising:
                    strategy_logger.debug(f"    ⚠️ Пропуск пробоя на баре {i}: ADX падает ({bar_adx:.1f} <= {adx_prev_2:.1f}) в TREND")
                    continue
            
            # Пробой вверх (через swing high) - используем адаптивный volume_threshold
            if (swings['swing_high'] is not None and 
                bar_close > swings['swing_high'] and 
                (bar_close - swings['swing_high']) >= self.breakout_atr * bar_atr and
                vol_ratio >= volume_threshold):
                strategy_logger.debug(f"    ✅ Пробой LONG найден на баре {i}: ADX={bar_adx:.1f}, volume {vol_ratio:.1f}x (порог {volume_threshold}x для {regime})")
                return {
                    'direction': 'LONG',
                    'level': swings['swing_high'],
                    'bar_index': i,
                    'atr': bar_atr,
                    'vwap': bar_vwap,
                    'adx': bar_adx,
                    'volume_ratio': vol_ratio  # ФАЗА 2: сохраняем для score
                }
            
            # Пробой вниз (через swing low) - используем адаптивный volume_threshold
            elif (swings['swing_low'] is not None and 
                  bar_close < swings['swing_low'] and 
                  (swings['swing_low'] - bar_close) >= self.breakout_atr * bar_atr and
                  vol_ratio >= volume_threshold):
                strategy_logger.debug(f"    ✅ Пробой SHORT найден на баре {i}: ADX={bar_adx:.1f}, volume {vol_ratio:.1f}x (порог {volume_threshold}x для {regime})")
                return {
                    'direction': 'SHORT',
                    'level': swings['swing_low'],
                    'bar_index': i,
                    'atr': bar_atr,
                    'vwap': bar_vwap,
                    'adx': bar_adx,
                    'volume_ratio': vol_ratio  # ФАЗА 2: сохраняем для score
                }
        
        return None
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < 50:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется 50")
            return None
        
        # ФАЗА 1: Блокировка bearish bias в TREND режиме
        if regime == 'TREND' and bias.lower() == 'bearish':
            strategy_logger.debug(f"    ❌ TREND + bearish bias = исторически убыточно (WR 12.5%)")
            return None
        
        # Рассчитать ATR, ADX и VWAP
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        adx = calculate_adx(df['high'], df['low'], df['close'], period=14)
        current_adx = adx.iloc[-1]
        
        # Получить VWAP из indicators или рассчитать
        vwap = indicators.get('vwap', None)
        
        # Выбрать правильный ADX порог в зависимости от режима
        if regime == 'TREND':
            adx_threshold = self.adx_threshold_trend  # 25 для TREND
        elif regime == 'SQUEEZE':
            adx_threshold = self.adx_threshold_squeeze  # 15 для SQUEEZE
        else:
            adx_threshold = self.adx_threshold_default  # 20 по умолчанию
        
        # Выбрать правильный volume порог в зависимости от режима
        if regime == 'TREND':
            volume_threshold = self.volume_threshold_trend  # 1.8 для TREND
        elif regime == 'SQUEEZE':
            volume_threshold = self.volume_threshold_squeeze  # 1.2 для SQUEEZE
        else:
            volume_threshold = self.volume_threshold  # 1.5 по умолчанию
        
        # Найти недавний пробой с ADX фильтром (передаем режим и пороги)
        breakout = self._find_recent_breakout(df, atr, vwap, adx, regime, adx_threshold, volume_threshold)
        if breakout is None:
            strategy_logger.debug(f"    ❌ Нет недавнего пробоя swing level (ADX>{adx_threshold}, vol>{volume_threshold}x для режима {regime})")
            return None
        
        # Логирование найденного пробоя
        strategy_logger.debug(f"    📊 Пробой {breakout['direction']} с ADX={breakout.get('adx', 0):.1f}, уровень {breakout['level']:.4f}")
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # Зона ретеста = экстремум ± 0.2-0.3 ATR (используем ATR с момента пробоя!)
        breakout_level = breakout['level']
        breakout_atr = breakout['atr']
        breakout_vwap = breakout.get('vwap')
        
        retest_zone_upper = breakout_level + self.zone_atr[1] * breakout_atr
        retest_zone_lower = breakout_level - self.zone_atr[1] * breakout_atr
        
        # Если есть VWAP, учитываем пересечение (по мануалу)
        if breakout_vwap is not None:
            retest_zone_upper = min(retest_zone_upper, breakout_vwap + 0.1 * breakout_atr)
            retest_zone_lower = max(retest_zone_lower, breakout_vwap - 0.1 * breakout_atr)
        
        # Логирование для debug
        strategy_logger.debug(f"    📊 Пробой найден: {breakout['direction']} на уровне {breakout_level:.4f}, ATR={breakout_atr:.4f}")
        strategy_logger.debug(f"    📊 Зона ретеста: [{retest_zone_lower:.4f}, {retest_zone_upper:.4f}], текущая цена: {current_close:.4f}")
        
        # Проверка касания зоны за последние несколько баров (не только текущий)
        lookback_retest = 5
        touched_zone = False
        reclaimed_level = False
        
        # LONG retest (после пробоя вверх)
        if breakout['direction'] == 'LONG':
            # Проверка: цена касалась зоны ретеста за последние N баров
            for i in range(-lookback_retest, 0):
                if abs(i) >= len(df):
                    continue
                bar_low = df['low'].iloc[i]
                bar_close = df['close'].iloc[i]
                
                # Касание зоны
                if retest_zone_lower <= bar_low <= retest_zone_upper:
                    touched_zone = True
                
                # Рекламирование уровня (close выше уровня пробоя)
                if bar_low <= breakout_level and bar_close > breakout_level:
                    reclaimed_level = True
            
            # Текущий бар также должен быть выше уровня
            if touched_zone and reclaimed_level and current_close > breakout_level:
                    
                    # Фильтр по H4 bias
                    if bias == 'Bearish':
                        strategy_logger.debug(f"    ❌ LONG ретест есть, но H4 bias {bias}")
                        return None
                    
                    # ФАЗА 1: Higher Timeframe Confirmation (только для TREND)
                    htf_confirmed = True
                    htf_has_data = False
                    if regime == 'TREND':
                        df_1h = indicators.get('1h')
                        df_4h = indicators.get('4h')
                        htf_confirmed, htf_has_data = self._check_higher_timeframe_trend(df_1h, df_4h, 'LONG')
                        
                        # Если есть данные но не подтверждается - блокируем
                        if htf_has_data and not htf_confirmed:
                            strategy_logger.debug(f"    ❌ LONG ретест OK, но Higher TF не подтверждает тренд (1H/4H EMA200)")
                            return None  # Строгая блокировка для TREND режима
                        
                        if htf_confirmed:
                            strategy_logger.debug(f"    ✅ Higher TF подтверждает LONG тренд (1H+4H > EMA200)")
                        else:
                            strategy_logger.debug(f"    ⚠️ Higher TF: недостаточно данных для проверки EMA200 (штраф к score)")
                    
                    # ФАЗА 2: Bollinger Bands фильтр (только для TREND)
                    bb_good = True
                    if regime == 'TREND':
                        bb_good = self._check_bollinger_position(df, 'LONG')
                        if not bb_good:
                            strategy_logger.debug(f"    ⚠️ Цена не у верхней полосы Bollinger (слабый импульс)")
                            # Не блокируем, просто понижаем score
                    
                    # ФАЗА 2: Проверка качества ретеста
                    retest_bars_data = []
                    for i in range(-lookback_retest, 0):
                        if abs(i) < len(df):
                            retest_bars_data.append({
                                'low': df['low'].iloc[i],
                                'high': df['high'].iloc[i],
                                'open': df['open'].iloc[i],
                                'close': df['close'].iloc[i]
                            })
                    retest_quality = self._check_retest_quality(breakout, retest_bars_data, breakout_level)
                    strategy_logger.debug(f"    📊 Качество ретеста: {retest_quality:.2f}/1.0")
                    
                    # ФАЗА 3: RSI Confirmation
                    rsi_confirmed = True
                    if regime == 'TREND':
                        rsi_confirmed = self._check_rsi_confirmation(df, 'LONG')
                        if not rsi_confirmed:
                            strategy_logger.debug(f"    ⚠️ RSI не подтверждает импульс вверх")
                    
                    # ФАЗА 3: Market Structure
                    market_structure_good = True
                    if regime == 'TREND':
                        market_structure_good = self._check_market_structure(df, 'LONG')
                        if not market_structure_good:
                            strategy_logger.debug(f"    ⚠️ Market structure не показывает Higher Highs/Lows")
                    
                    entry = current_close
                    
                    # ФАЗА 1: Выбор метода расчёта TP/SL
                    if self.use_atr_based_tp_sl:
                        # ATR-based TP/SL (динамическая адаптация под волатильность)
                        stop_loss = entry - (current_atr * self.atr_sl_multiplier)
                        tp1 = entry + (current_atr * self.atr_tp1_multiplier)
                        tp2 = entry + (current_atr * self.atr_tp2_multiplier)
                        strategy_logger.debug(f"    📊 ATR-based TP/SL: SL={self.atr_sl_multiplier}×ATR, TP1={self.atr_tp1_multiplier}×ATR, TP2={self.atr_tp2_multiplier}×ATR")
                    else:
                        # SR-based TP/SL (старый метод - точные зоны S/R)
                        sr_zones = create_sr_zones(df, current_atr, buffer_mult=0.25)
                        nearest_zone = find_nearest_zone(entry, sr_zones, 'LONG')
                        stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, current_atr, 'LONG', fallback_mult=2.0)
                        
                        # Расчет дистанции и тейков 1R и 2R
                        atr_distance = abs(entry - stop_loss)
                        tp1 = entry + atr_distance * 1.0  # 1R
                        tp2 = entry + atr_distance * 2.0  # 2R
                        strategy_logger.debug(f"    📊 SR-based TP/SL: SL из S/R зоны, TP1=1R, TP2=2R")
                    
                    # ФАЗА 2+3: Улучшенная score система
                    base_score = 2.5
                    improved_score = self._calculate_improved_score(
                        base_score, breakout, regime, bias, retest_quality,
                        bb_good, htf_confirmed, htf_has_data, rsi_confirmed, market_structure_good
                    )
                    
                    strategy_logger.debug(f"    💯 Score: {base_score:.1f} → {improved_score:.1f} (режим {regime})")
                    
                    # Получить CVD и OI из indicators
                    cvd_val = indicators.get(self.timeframe, {}).get('cvd', 0)
                    # Если cvd_val - это Series, взять последнее значение
                    if hasattr(cvd_val, 'iloc'):
                        cvd_val = float(cvd_val.iloc[-1]) if len(cvd_val) > 0 else 0
                    cvd_direction = 'Bullish' if cvd_val > 0 else ('Bearish' if cvd_val < 0 else 'Neutral')
                    oi_delta_pct = indicators.get('doi_pct', 0.0)
                    
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
                        base_score=improved_score,  # Используем улучшенный score
                        volume_ratio=float(breakout.get('volume_ratio', 1.0)),  # ИЗ BREAKOUT
                        cvd_direction=cvd_direction,  # ИЗ INDICATORS
                        oi_delta_percent=float(oi_delta_pct),  # ИЗ INDICATORS
                        metadata={
                            'breakout_level': float(breakout_level),
                            'retest_zone_upper': float(retest_zone_upper),
                            'retest_zone_lower': float(retest_zone_lower),
                            'breakout_bar_index': int(breakout['bar_index']),
                            'adx': float(breakout.get('adx', 0)),
                            'volume_ratio': float(breakout.get('volume_ratio', 1.0)),
                            'retest_quality': float(retest_quality),
                            'htf_confirmed': htf_confirmed,
                            'bb_good': bb_good,
                            'rsi_confirmed': rsi_confirmed,
                            'market_structure_good': market_structure_good
                        }
                    )
                    return signal
        
        # SHORT retest (после пробоя вниз)
        elif breakout['direction'] == 'SHORT':
            # Проверка: цена касалась зоны ретеста за последние N баров
            for i in range(-lookback_retest, 0):
                if abs(i) >= len(df):
                    continue
                bar_high = df['high'].iloc[i]
                bar_close = df['close'].iloc[i]
                
                # Касание зоны
                if retest_zone_lower <= bar_high <= retest_zone_upper:
                    touched_zone = True
                
                # Рекламирование уровня (close ниже уровня пробоя)
                if bar_high >= breakout_level and bar_close < breakout_level:
                    reclaimed_level = True
            
            # Текущий бар также должен быть ниже уровня
            if touched_zone and reclaimed_level and current_close < breakout_level:
                    
                    if bias == 'Bullish':
                        strategy_logger.debug(f"    ❌ SHORT ретест есть, но H4 bias {bias}")
                        return None
                    
                    # ФАЗА 1: Higher Timeframe Confirmation (только для TREND)
                    htf_confirmed = True
                    htf_has_data = False
                    if regime == 'TREND':
                        df_1h = indicators.get('1h')
                        df_4h = indicators.get('4h')
                        htf_confirmed, htf_has_data = self._check_higher_timeframe_trend(df_1h, df_4h, 'SHORT')
                        
                        # Если есть данные но не подтверждается - блокируем
                        if htf_has_data and not htf_confirmed:
                            strategy_logger.debug(f"    ❌ SHORT ретест OK, но Higher TF не подтверждает тренд (1H/4H EMA200)")
                            return None  # Строгая блокировка для TREND режима
                        
                        if htf_confirmed:
                            strategy_logger.debug(f"    ✅ Higher TF подтверждает SHORT тренд (1H+4H < EMA200)")
                        else:
                            strategy_logger.debug(f"    ⚠️ Higher TF: недостаточно данных для проверки EMA200 (штраф к score)")
                    
                    # ФАЗА 2: Bollinger Bands фильтр (только для TREND)
                    bb_good = True
                    if regime == 'TREND':
                        bb_good = self._check_bollinger_position(df, 'SHORT')
                        if not bb_good:
                            strategy_logger.debug(f"    ⚠️ Цена не у нижней полосы Bollinger (слабый импульс)")
                            # Не блокируем, просто понижаем score
                    
                    # ФАЗА 2: Проверка качества ретеста
                    retest_bars_data = []
                    for i in range(-lookback_retest, 0):
                        if abs(i) < len(df):
                            retest_bars_data.append({
                                'low': df['low'].iloc[i],
                                'high': df['high'].iloc[i],
                                'open': df['open'].iloc[i],
                                'close': df['close'].iloc[i]
                            })
                    retest_quality = self._check_retest_quality(breakout, retest_bars_data, breakout_level)
                    strategy_logger.debug(f"    📊 Качество ретеста: {retest_quality:.2f}/1.0")
                    
                    # ФАЗА 3: RSI Confirmation
                    rsi_confirmed = True
                    if regime == 'TREND':
                        rsi_confirmed = self._check_rsi_confirmation(df, 'SHORT')
                        if not rsi_confirmed:
                            strategy_logger.debug(f"    ⚠️ RSI не подтверждает импульс вниз")
                    
                    # ФАЗА 3: Market Structure
                    market_structure_good = True
                    if regime == 'TREND':
                        market_structure_good = self._check_market_structure(df, 'SHORT')
                        if not market_structure_good:
                            strategy_logger.debug(f"    ⚠️ Market structure не показывает Lower Lows/Highs")
                    
                    entry = current_close
                    
                    # ФАЗА 1: Выбор метода расчёта TP/SL
                    if self.use_atr_based_tp_sl:
                        # ATR-based TP/SL (динамическая адаптация под волатильность)
                        stop_loss = entry + (current_atr * self.atr_sl_multiplier)
                        tp1 = entry - (current_atr * self.atr_tp1_multiplier)
                        tp2 = entry - (current_atr * self.atr_tp2_multiplier)
                        strategy_logger.debug(f"    📊 ATR-based TP/SL: SL={self.atr_sl_multiplier}×ATR, TP1={self.atr_tp1_multiplier}×ATR, TP2={self.atr_tp2_multiplier}×ATR")
                    else:
                        # SR-based TP/SL (старый метод - точные зоны S/R)
                        sr_zones = create_sr_zones(df, current_atr, buffer_mult=0.25)
                        nearest_zone = find_nearest_zone(entry, sr_zones, 'SHORT')
                        stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, current_atr, 'SHORT', fallback_mult=2.0)
                        
                        # Расчет дистанции и тейков 1R и 2R
                        atr_distance = abs(stop_loss - entry)
                        tp1 = entry - atr_distance * 1.0  # 1R
                        tp2 = entry - atr_distance * 2.0  # 2R
                        strategy_logger.debug(f"    📊 SR-based TP/SL: SL из S/R зоны, TP1=1R, TP2=2R")
                    
                    # ФАЗА 2+3: Улучшенная score система
                    base_score = 2.5
                    improved_score = self._calculate_improved_score(
                        base_score, breakout, regime, bias, retest_quality,
                        bb_good, htf_confirmed, htf_has_data, rsi_confirmed, market_structure_good
                    )
                    
                    strategy_logger.debug(f"    💯 Score: {base_score:.1f} → {improved_score:.1f} (режим {regime})")
                    
                    # Получить CVD и OI из indicators
                    cvd_val = indicators.get(self.timeframe, {}).get('cvd', 0)
                    # Если cvd_val - это Series, взять последнее значение
                    if hasattr(cvd_val, 'iloc'):
                        cvd_val = float(cvd_val.iloc[-1]) if len(cvd_val) > 0 else 0
                    cvd_direction = 'Bullish' if cvd_val > 0 else ('Bearish' if cvd_val < 0 else 'Neutral')
                    oi_delta_pct = indicators.get('doi_pct', 0.0)
                    
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
                        base_score=improved_score,  # Используем улучшенный score
                        volume_ratio=float(breakout.get('volume_ratio', 1.0)),  # ИЗ BREAKOUT
                        cvd_direction=cvd_direction,  # ИЗ INDICATORS
                        oi_delta_percent=float(oi_delta_pct),  # ИЗ INDICATORS
                        metadata={
                            'breakout_level': float(breakout_level),
                            'retest_zone_upper': float(retest_zone_upper),
                            'retest_zone_lower': float(retest_zone_lower),
                            'breakout_bar_index': int(breakout['bar_index']),
                            'adx': float(breakout.get('adx', 0)),
                            'volume_ratio': float(breakout.get('volume_ratio', 1.0)),
                            'retest_quality': float(retest_quality),
                            'htf_confirmed': htf_confirmed,
                            'bb_good': bb_good,
                            'rsi_confirmed': rsi_confirmed,
                            'market_structure_good': market_structure_good
                        }
                    )
                    return signal
        
        # Детальное логирование причин отклонения
        if not touched_zone:
            strategy_logger.debug(f"    ❌ Цена НЕ касалась зоны ретеста [{retest_zone_lower:.4f}, {retest_zone_upper:.4f}] за последние {lookback_retest} баров")
        elif not reclaimed_level:
            if breakout['direction'] == 'LONG':
                strategy_logger.debug(f"    ❌ Зона касалась, но НЕТ rejection: нужен close ВЫШЕ {breakout_level:.4f} после касания снизу")
            else:
                strategy_logger.debug(f"    ❌ Зона касалась, но НЕТ rejection: нужен close НИЖЕ {breakout_level:.4f} после касания сверху")
        else:
            strategy_logger.debug(f"    ❌ Текущая цена {current_close:.4f} не {'выше' if breakout['direction'] == 'LONG' else 'ниже'} уровня пробоя {breakout_level:.4f}")
        return None
