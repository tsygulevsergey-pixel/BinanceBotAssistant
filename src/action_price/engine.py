"""
Action Price Engine - EMA200 Body Cross Strategy
Полная переработка на основе новой логики скоринга
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import hashlib
import pytz
import logging
import pandas_ta as ta

logger = logging.getLogger(__name__)

from .signal_logger import ActionPriceSignalLogger
from .cooldown import ActionPriceCooldown


class ActionPriceEngine:
    """EMA200 Body Cross Strategy с профессиональной системой скоринга"""
    
    def __init__(self, config: dict, binance_client=None, signal_logger=None):
        """
        Args:
            config: Конфигурация из config.yaml['action_price']
            binance_client: BinanceClient для получения актуальной цены
            signal_logger: Внешний JSONL логгер (если None, создаётся новый)
        """
        self.config = config
        self.enabled = config.get('enabled', True)
        self.client = binance_client
        
        # JSONL логгер для детальных метрик (используем переданный или создаём новый)
        self.signal_logger = signal_logger if signal_logger else ActionPriceSignalLogger()
        
        # Cooldown система
        self.cooldown = ActionPriceCooldown(config.get('cooldown', {}))
        
        # Таймфрейм работы (из конфига или дефолт 15m)
        self.timeframe = config.get('timeframe', '15m')
        
        # Параметры ATR полос
        self.atr_length = config.get('atr_length', 14)
        self.atr_multiplier = config.get('atr_multiplier', 1.5)
        
        # Swing период
        self.swing_length = config.get('swing_length', 20)
        
        # Score пороги
        self.score_standard_min = config.get('score_standard_min', 3)
        self.score_scalp_min = config.get('score_scalp_min', 1)
        
        # TP/SL параметры
        self.tp1_rr = config.get('tp1_rr', 1.0)
        self.tp2_rr = config.get('tp2_rr', 2.0)
        self.sl_buffer_atr = config.get('sl_buffer_atr', 0.1)
        self.max_sl_percent = config.get('max_sl_percent', 10.0)  # Максимальный SL в %
        
        logger.info(f"✅ Action Price Engine initialized (EMA200 Body Cross, TF={self.timeframe})")
    
    async def analyze(self, symbol: str, df: pd.DataFrame, df_1h: pd.DataFrame = None) -> Optional[Dict]:
        """
        Анализ рынка и генерация сигнала
        
        Args:
            symbol: Символ
            df: Данные таймфрейма (15m)
            df_1h: Часовые данные (опционально, для фильтров)
            
        Returns:
            Словарь с сигналом или None
        """
        if not self.enabled:
            return None
        
        if len(df) < 250:  # Нужно минимум для EMA200
            return None
        
        # КРИТИЧНО: Валидация и подготовка датафрейма
        # 1. Создать копию чтобы не менять original
        df = df.copy()
        
        # 2. Убедиться что есть open_time колонка
        if 'open_time' not in df.columns:
            logger.error(f"{symbol} - No 'open_time' column in dataframe!")
            return None
        
        # 3. Сортировать по open_time (ASC - от старых к новым)
        df = df.sort_values('open_time', ascending=True).reset_index(drop=True)
        
        # Рассчитать индикаторы
        indicators = self._calculate_indicators(df)
        if indicators is None:
            return None
        
        # Определить инициатор и подтверждение
        pattern_result = self._detect_body_cross_pattern(df, indicators)
        if pattern_result is None:
            return None
        
        direction, initiator_idx, confirm_idx = pattern_result
        
        # Проверить cooldown ПОСЛЕ определения direction
        from datetime import datetime
        if hasattr(self.cooldown, 'is_duplicate'):
            if self.cooldown.is_duplicate(symbol, direction, 'body_cross', 'body_cross', 
                                          self.timeframe, datetime.now()):
                logger.debug(f"{symbol} - Cooldown active for {direction}")
                return None
        
        # Рассчитать score компоненты
        score_result = self._calculate_score_components(
            df, indicators, direction, initiator_idx, confirm_idx
        )
        
        if score_result is None:
            return None
        
        score_total, score_components = score_result
        
        # Определить режим (STANDARD/SCALP/SKIP)
        mode = self._determine_mode(score_total)
        if mode == 'SKIP':
            logger.debug(f"{symbol} - Score {score_total:.1f} → SKIP")
            return None
        
        # Рассчитать SL/TP уровни (НОВАЯ ЛОГИКА: Entry через REST API)
        levels = await self._calculate_sl_tp_levels(
            symbol, df, indicators, direction, initiator_idx, confirm_idx, mode
        )
        
        if levels is None:
            return None
        
        # Собрать все метрики для JSONL лога
        signal_data = self._build_signal_data(
            symbol=symbol,
            direction=direction,
            mode=mode,
            score_total=score_total,
            score_components=score_components,
            df=df,
            indicators=indicators,
            initiator_idx=initiator_idx,
            confirm_idx=confirm_idx,
            levels=levels
        )
        
        # Записать в JSONL лог
        self.signal_logger.log_signal(signal_data)
        
        # Установить cooldown (регистрировать сигнал)
        from datetime import datetime
        if hasattr(self.cooldown, 'register_signal'):
            self.cooldown.register_signal(symbol, direction, 'body_cross', 'body_cross',
                                         self.timeframe, datetime.now())
        
        # Вернуть полный формат для основного бота (совместимость с БД)
        return {
            # Базовые поля
            'context_hash': signal_data['signal_id'],  # Используем signal_id как context_hash
            'symbol': symbol,
            'timeframe': self.timeframe,
            'direction': direction,
            'pattern_type': 'body_cross',
            
            # Для совместимости с БД (старые поля zone-based)
            'zone_id': 'ema200_body_cross',
            'zone_low': float(levels['sl']),  # SL как zone_low
            'zone_high': float(levels['entry']),  # Entry как zone_high
            
            # Уровни входа/выхода
            'entry_price': float(levels['entry']),
            'stop_loss': float(levels['sl']),
            'take_profit_1': float(levels['tp1']),
            'take_profit_2': float(levels['tp2']) if levels['tp2'] is not None else None,
            
            # EMA данные
            'ema_50_4h': None,
            'ema_200_4h': None,
            'ema_50_1h': None,
            'ema_200_1h': None,
            
            # Confluences (пустые для EMA200)
            'avwap_primary': None,
            'avwap_secondary': None,
            'daily_vwap': None,
            'confluence_flags': {},
            
            # Score и режим
            'confidence_score': float(score_total),
            'regime': '',
            
            # Мета данные
            'meta_data': {
                'score_components': score_components,
                'mode': mode,
                'rr1': self.tp1_rr,
                'rr2': self.tp2_rr
            }
        }
    
    def _calculate_indicators(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Рассчитать все необходимые индикаторы"""
        try:
            df = df.copy()
            
            # EMA
            df['ema5'] = ta.ema(df['close'], length=5)
            df['ema9'] = ta.ema(df['close'], length=9)
            df['ema13'] = ta.ema(df['close'], length=13)
            df['ema21'] = ta.ema(df['close'], length=21)
            df['ema200'] = ta.ema(df['close'], length=200)
            
            # ATR
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=self.atr_length)
            
            # ATR полосы
            df['atr_upper'] = df['ema200'] + df['atr'] * self.atr_multiplier
            df['atr_lower'] = df['ema200'] - df['atr'] * self.atr_multiplier
            
            # Swing High/Low
            df['swing_high'] = df['high'].rolling(window=self.swing_length).max()
            df['swing_low'] = df['low'].rolling(window=self.swing_length).min()
            
            # Проверить наличие NaN
            if df[['ema200', 'atr']].iloc[-3:].isna().any().any():
                return None
            
            return df
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return None
    
    def _detect_body_cross_pattern(
        self, df: pd.DataFrame, indicators: pd.DataFrame
    ) -> Optional[Tuple[str, int, int]]:
        """
        Определить паттерн Body Cross
        
        Returns:
            (direction, initiator_idx, confirm_idx) или None
        """
        # КРИТИЧНО: Анализировать последние ДВЕ ЗАКРЫТЫЕ свечи!
        # 
        # Пример: сейчас 00:16
        # - Свеча -1: 00:00-00:15 (последняя закрытая) = ПОДТВЕРЖДАЮЩАЯ
        # - Свеча -2: 23:45-00:00 (предыдущая) = ИНИЦИАТОР
        #
        # Инициатор: проверяем пересекло ли тело EMA200 (значение EMA200 на момент начала свечи)
        # Подтверждение: close и тень не касаются EMA200 (значение EMA200 на момент начала свечи)
        #
        # Проверяем что у нас минимум 2 свечи
        if len(indicators) < 2:
            return None
        
        # Индексы: инициатор = -2 (предпоследняя), подтверждение = -1 (последняя)
        initiator_idx = -2
        confirm_idx = -1
        
        # Данные инициатора
        init_open = indicators['open'].iloc[initiator_idx]
        init_close = indicators['close'].iloc[initiator_idx]
        ema200_init = indicators['ema200'].iloc[initiator_idx]
        init_time = indicators['open_time'].iloc[initiator_idx] if 'open_time' in indicators.columns else None
        
        # Данные подтверждения
        conf_open = indicators['open'].iloc[confirm_idx]
        conf_close = indicators['close'].iloc[confirm_idx]
        conf_high = indicators['high'].iloc[confirm_idx]
        conf_low = indicators['low'].iloc[confirm_idx]
        ema200_conf = indicators['ema200'].iloc[confirm_idx]
        conf_time = indicators['open_time'].iloc[confirm_idx] if 'open_time' in indicators.columns else None
        
        # ДИАГНОСТИКА: Логировать timestamp и OHLC для проверки
        logger.info(
            f"🔍 Candle Selection | "
            f"Initiator[-2]: {init_time} O:{init_open:.5f} C:{init_close:.5f} EMA200:{ema200_init:.5f} | "
            f"Confirm[-1]: {conf_time} O:{conf_open:.5f} H:{conf_high:.5f} L:{conf_low:.5f} C:{conf_close:.5f} EMA200:{ema200_conf:.5f}"
        )
        
        # === LONG PATTERN ===
        # Инициатор: body пересекает EMA200 снизу вверх (закрытие выше)
        initiator_long = (
            init_close > ema200_init and 
            init_open < ema200_init and
            min(init_close, init_open) < ema200_init
        )
        
        # Подтверждение: close выше EMA200, без касания
        confirm_long = (
            conf_close > ema200_conf and
            conf_low > ema200_conf  # Нет касания низом
        )
        
        # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для LONG
        if initiator_long:
            logger.info(
                f"✅ LONG Initiator OK | "
                f"O:{init_open:.5f} < EMA:{ema200_init:.5f} < C:{init_close:.5f}"
            )
            if confirm_long:
                logger.info(
                    f"✅ LONG Confirm OK | "
                    f"L:{conf_low:.5f} > EMA:{ema200_conf:.5f}, C:{conf_close:.5f} > EMA:{ema200_conf:.5f}"
                )
            else:
                # КРИТИЧНО: Почему confirm НЕ прошла
                logger.warning(
                    f"❌ LONG Confirm FAILED | "
                    f"L:{conf_low:.5f} {'>' if conf_low > ema200_conf else '<='} EMA:{ema200_conf:.5f} "
                    f"(low must be ABOVE EMA200!) | "
                    f"C:{conf_close:.5f} {'>' if conf_close > ema200_conf else '<='} EMA:{ema200_conf:.5f}"
                )
        
        if initiator_long and confirm_long:
            return ('long', initiator_idx, confirm_idx)
        
        # === SHORT PATTERN ===
        # Инициатор: body пересекает EMA200 сверху вниз (закрытие ниже)
        initiator_short = (
            init_close < ema200_init and
            init_open > ema200_init and
            max(init_close, init_open) > ema200_init
        )
        
        # Подтверждение: close ниже EMA200, без касания
        confirm_short = (
            conf_close < ema200_conf and
            conf_high < ema200_conf  # Нет касания верхом
        )
        
        # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для SHORT
        if initiator_short:
            logger.info(
                f"✅ SHORT Initiator OK | "
                f"C:{init_close:.5f} < EMA:{ema200_init:.5f} < O:{init_open:.5f}"
            )
            if confirm_short:
                logger.info(
                    f"✅ SHORT Confirm OK | "
                    f"H:{conf_high:.5f} < EMA:{ema200_conf:.5f}, C:{conf_close:.5f} < EMA:{ema200_conf:.5f}"
                )
            else:
                # КРИТИЧНО: Почему confirm НЕ прошла
                logger.warning(
                    f"❌ SHORT Confirm FAILED | "
                    f"H:{conf_high:.5f} {'<' if conf_high < ema200_conf else '>='} EMA:{ema200_conf:.5f} "
                    f"(high must be BELOW EMA200!) | "
                    f"C:{conf_close:.5f} {'<' if conf_close < ema200_conf else '>='} EMA:{ema200_conf:.5f}"
                )
        
        if initiator_short and confirm_short:
            return ('short', initiator_idx, confirm_idx)
        
        return None
    
    def _calculate_score_components(
        self,
        df: pd.DataFrame,
        indicators: pd.DataFrame,
        direction: str,
        initiator_idx: int,
        confirm_idx: int
    ) -> Optional[Tuple[float, Dict[str, float]]]:
        """
        Рассчитать все компоненты score согласно спецификации
        
        Returns:
            (score_total, score_components) или None
        """
        components = {}
        
        # Данные свечей
        init_open = indicators['open'].iloc[initiator_idx]
        init_close = indicators['close'].iloc[initiator_idx]
        init_high = indicators['high'].iloc[initiator_idx]
        init_low = indicators['low'].iloc[initiator_idx]
        
        conf_open = indicators['open'].iloc[confirm_idx]
        conf_close = indicators['close'].iloc[confirm_idx]
        conf_high = indicators['high'].iloc[confirm_idx]
        conf_low = indicators['low'].iloc[confirm_idx]
        
        # EMA на подтверждении
        ema5 = indicators['ema5'].iloc[confirm_idx]
        ema9 = indicators['ema9'].iloc[confirm_idx]
        ema13 = indicators['ema13'].iloc[confirm_idx]
        ema21 = indicators['ema21'].iloc[confirm_idx]
        ema200 = indicators['ema200'].iloc[confirm_idx]
        ema200_init = indicators['ema200'].iloc[initiator_idx]
        
        # ATR
        atr_init = indicators['atr'].iloc[initiator_idx]
        atr_conf = indicators['atr'].iloc[confirm_idx]
        atr_upper = indicators['atr_upper'].iloc[confirm_idx]
        atr_lower = indicators['atr_lower'].iloc[confirm_idx]
        
        if direction == 'long':
            # 1. Размер инициатора (|body| в ATR)
            init_body = abs(init_close - init_open)
            init_body_atr = init_body / atr_init
            if init_body_atr >= 1.10:
                components['initiator_size'] = 2
            elif init_body_atr >= 0.80:
                components['initiator_size'] = 1
            else:
                components['initiator_size'] = 0
            
            # 2. Глубина подтверждения (|close−EMA200| в ATR)
            depth = conf_close - ema200
            depth_atr = depth / atr_conf
            if depth_atr >= 0.40:
                components['confirm_depth'] = 2
            elif depth_atr >= 0.35:
                components['confirm_depth'] = 1
            elif depth_atr < 0.30:
                components['confirm_depth'] = -1
            else:
                components['confirm_depth'] = 0
            
            # 3. Положение close подтверждения
            if conf_close > max(ema5, ema9, ema13, ema21):
                components['close_position'] = 1
            elif conf_close < ema21:
                components['close_position'] = -1
            else:
                components['close_position'] = 0
            
            # 4. Наклон EMA200 (за 10 баров)
            ema200_10bars_ago = indicators['ema200'].iloc[confirm_idx - 10]
            slope200 = ema200 - ema200_10bars_ago
            slope200_norm = slope200 / atr_conf
            if slope200_norm >= 0.20:
                components['slope200'] = 1
            elif slope200_norm <= -0.20:
                components['slope200'] = -1
            else:
                components['slope200'] = 0
            
            # 5. Веер EMA
            bullish_fan = ema5 > ema9 and ema9 > ema13 and ema13 > ema21
            fan_spread = (ema5 - ema21) / atr_conf
            if bullish_fan and fan_spread >= 0.10:
                components['ema_fan'] = 1
            elif ema5 < ema9 and ema9 < ema13 and ema13 < ema21:  # Медвежий
                components['ema_fan'] = -1
            else:
                components['ema_fan'] = 0
            
            # 6. Запас до внешней ATR-полосы
            gap_to_outer = atr_upper - conf_close
            gap_atr = gap_to_outer / atr_conf
            if gap_atr >= 0.50:
                components['gap_to_atr'] = 1
            elif gap_atr < 0.30:
                components['gap_to_atr'] = -1
            else:
                components['gap_to_atr'] = 0
            
            # 7. Липучка к EMA200 (касания за 5 баров до инициатора)
            touches = 0
            for i in range(initiator_idx - 5, initiator_idx):
                bar_low = indicators['low'].iloc[i]
                bar_high = indicators['high'].iloc[i]
                ema200_bar = indicators['ema200'].iloc[i]
                if bar_low <= ema200_bar <= bar_high:
                    touches += 1
            
            components['lipuchka'] = -1 if touches >= 3 else 0
            
            # 8. Цвет подтверждения
            confirm_green = conf_close > conf_open
            if confirm_green:
                components['confirm_color'] = 1
            elif not confirm_green and depth_atr < 0.30:
                components['confirm_color'] = -1
            else:
                components['confirm_color'] = 0
            
            # 9. Break-and-Base (2-4 узких бара над EMA200 с удержанием EMA13/21)
            # Упрощённая реализация: проверка 3 баров до подтверждения
            base_bars = 0
            for i in range(confirm_idx - 3, confirm_idx):
                bar_close = indicators['close'].iloc[i]
                bar_low = indicators['low'].iloc[i]
                bar_ema13 = indicators['ema13'].iloc[i]
                bar_ema21 = indicators['ema21'].iloc[i]
                bar_range = indicators['high'].iloc[i] - indicators['low'].iloc[i]
                bar_atr = indicators['atr'].iloc[i]
                
                if (bar_close > bar_ema13 and 
                    bar_low > bar_ema21 and 
                    bar_range < 0.5 * bar_atr):
                    base_bars += 1
            
            components['break_and_base'] = 1 if base_bars >= 2 else 0
            
            # 10. Retest-tag (продолжение тренда)
            # Упрощённо: если был контакт с EMA13/21 за 5 баров и структура бычья
            retest = False
            for i in range(confirm_idx - 5, confirm_idx):
                bar_low = indicators['low'].iloc[i]
                bar_close = indicators['close'].iloc[i]
                bar_ema13 = indicators['ema13'].iloc[i]
                bar_ema21 = indicators['ema21'].iloc[i]
                
                if ((bar_low <= bar_ema13 and bar_close > bar_ema13) or
                    (bar_low <= bar_ema21 and bar_close > bar_ema21)):
                    retest = True
                    break
            
            components['retest_tag'] = 1 if retest else 0
            
            # 11. Хвост инициатора (нижняя тень)
            init_lower_wick = init_low - min(init_open, init_close)
            init_lower_wick_atr = init_lower_wick / atr_init
            components['initiator_wick'] = 1 if init_lower_wick_atr >= 0.25 else 0
            
        else:  # SHORT (зеркально)
            # 1. Размер инициатора
            init_body = abs(init_close - init_open)
            init_body_atr = init_body / atr_init
            if init_body_atr >= 1.10:
                components['initiator_size'] = 2
            elif init_body_atr >= 0.80:
                components['initiator_size'] = 1
            else:
                components['initiator_size'] = 0
            
            # 2. Глубина подтверждения
            depth = ema200 - conf_close
            depth_atr = depth / atr_conf
            if depth_atr >= 0.40:
                components['confirm_depth'] = 2
            elif depth_atr >= 0.35:
                components['confirm_depth'] = 1
            elif depth_atr < 0.30:
                components['confirm_depth'] = -1
            else:
                components['confirm_depth'] = 0
            
            # 3. Положение close подтверждения
            if conf_close < min(ema5, ema9, ema13, ema21):
                components['close_position'] = 1
            elif conf_close > ema21:
                components['close_position'] = -1
            else:
                components['close_position'] = 0
            
            # 4. Наклон EMA200
            ema200_10bars_ago = indicators['ema200'].iloc[confirm_idx - 10]
            slope200 = ema200 - ema200_10bars_ago
            slope200_norm = slope200 / atr_conf
            if slope200_norm <= -0.20:
                components['slope200'] = 1
            elif slope200_norm >= 0.20:
                components['slope200'] = -1
            else:
                components['slope200'] = 0
            
            # 5. Веер EMA
            bearish_fan = ema5 < ema9 and ema9 < ema13 and ema13 < ema21
            fan_spread = (ema21 - ema5) / atr_conf
            if bearish_fan and fan_spread >= 0.10:
                components['ema_fan'] = 1
            elif ema5 > ema9 and ema9 > ema13 and ema13 > ema21:  # Бычий
                components['ema_fan'] = -1
            else:
                components['ema_fan'] = 0
            
            # 6. Запас до нижней ATR-полосы
            gap_to_outer = conf_close - atr_lower
            gap_atr = gap_to_outer / atr_conf
            if gap_atr >= 0.50:
                components['gap_to_atr'] = 1
            elif gap_atr < 0.30:
                components['gap_to_atr'] = -1
            else:
                components['gap_to_atr'] = 0
            
            # 7. Липучка
            touches = 0
            for i in range(initiator_idx - 5, initiator_idx):
                bar_low = indicators['low'].iloc[i]
                bar_high = indicators['high'].iloc[i]
                ema200_bar = indicators['ema200'].iloc[i]
                if bar_low <= ema200_bar <= bar_high:
                    touches += 1
            
            components['lipuchka'] = -1 if touches >= 3 else 0
            
            # 8. Цвет подтверждения
            confirm_red = conf_close < conf_open
            if confirm_red:
                components['confirm_color'] = 1
            elif not confirm_red and depth_atr < 0.30:
                components['confirm_color'] = -1
            else:
                components['confirm_color'] = 0
            
            # 9. Break-and-Base
            base_bars = 0
            for i in range(confirm_idx - 3, confirm_idx):
                bar_close = indicators['close'].iloc[i]
                bar_high = indicators['high'].iloc[i]
                bar_ema13 = indicators['ema13'].iloc[i]
                bar_ema21 = indicators['ema21'].iloc[i]
                bar_range = indicators['high'].iloc[i] - indicators['low'].iloc[i]
                bar_atr = indicators['atr'].iloc[i]
                
                if (bar_close < bar_ema13 and 
                    bar_high < bar_ema21 and 
                    bar_range < 0.5 * bar_atr):
                    base_bars += 1
            
            components['break_and_base'] = 1 if base_bars >= 2 else 0
            
            # 10. Retest-tag
            retest = False
            for i in range(confirm_idx - 5, confirm_idx):
                bar_high = indicators['high'].iloc[i]
                bar_close = indicators['close'].iloc[i]
                bar_ema13 = indicators['ema13'].iloc[i]
                bar_ema21 = indicators['ema21'].iloc[i]
                
                if ((bar_high >= bar_ema13 and bar_close < bar_ema13) or
                    (bar_high >= bar_ema21 and bar_close < bar_ema21)):
                    retest = True
                    break
            
            components['retest_tag'] = 1 if retest else 0
            
            # 11. Хвост инициатора (верхняя тень)
            init_upper_wick = init_high - max(init_open, init_close)
            init_upper_wick_atr = init_upper_wick / atr_init
            components['initiator_wick'] = 1 if init_upper_wick_atr >= 0.25 else 0
        
        # Итоговый score
        score_total = sum(components.values())
        
        return (score_total, components)
    
    def _determine_mode(self, score_total: float) -> str:
        """Определить режим входа на основе score"""
        if score_total >= self.score_standard_min:
            return 'STANDARD'
        elif score_total >= self.score_scalp_min:
            return 'SCALP'
        else:
            return 'SKIP'
    
    async def _calculate_sl_tp_levels(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: pd.DataFrame,
        direction: str,
        initiator_idx: int,
        confirm_idx: int,
        mode: str
    ) -> Optional[Dict]:
        """
        Рассчитать Stop Loss и Take Profit уровни
        
        НОВАЯ ЛОГИКА:
        - R рассчитывается от SL до Close подтверждающей (фиксированный)
        - TP рассчитываются от Close подтверждающей
        - Entry берётся через REST API (актуальная рыночная цена)
        
        Returns:
            Dict с entry, sl, tp1, tp2 или None
        """
        # Close подтверждающей свечи (техническая точка для TP)
        confirm_close = indicators['close'].iloc[confirm_idx]
        
        # ATR для буфера
        atr = indicators['atr'].iloc[initiator_idx]
        sl_buffer = atr * self.sl_buffer_atr
        
        if direction == 'long':
            # SL за экстремумом инициатора (low - буфер)
            sl = indicators['low'].iloc[initiator_idx] - sl_buffer
            
            # Risk от SL до Close подтверждающей (фиксированный)
            risk_r = confirm_close - sl
            if risk_r <= 0:
                return None
            
            # TP от Close подтверждающей
            tp1 = confirm_close + risk_r * self.tp1_rr
            tp2 = confirm_close + risk_r * self.tp2_rr if mode == 'STANDARD' else None
            
        else:  # SHORT
            # SL за экстремумом инициатора (high + буфер)
            sl = indicators['high'].iloc[initiator_idx] + sl_buffer
            
            # Risk от SL до Close подтверждающей (фиксированный)
            risk_r = sl - confirm_close
            if risk_r <= 0:
                return None
            
            # TP от Close подтверждающей
            tp1 = confirm_close - risk_r * self.tp1_rr
            tp2 = confirm_close - risk_r * self.tp2_rr if mode == 'STANDARD' else None
        
        # Получить актуальную рыночную цену через REST API
        entry = confirm_close  # Fallback если API недоступен
        if self.client:
            try:
                ticker = await self.client.get_symbol_ticker(symbol)
                entry = float(ticker['price'])
                logger.debug(f"{symbol} Entry Price: REST API={entry:.6f}, Confirm Close={confirm_close:.6f}")
            except Exception as e:
                logger.warning(f"{symbol} Action Price: Failed to get current price via REST API, using confirm_close: {e}")
        
        # КРИТИЧНО: Проверка стоп-лосса - должен быть < max_sl_percent от цены confirm_close
        sl_percent = abs(confirm_close - sl) / confirm_close * 100
        if sl_percent >= self.max_sl_percent:
            logger.warning(
                f"⚠️ {symbol} Action Price: SL слишком широкий ({sl_percent:.2f}% >= {self.max_sl_percent}%) - сигнал отклонен | "
                f"Confirm Close: {confirm_close:.6f}, SL: {sl:.6f}, Risk: {abs(confirm_close-sl):.6f}"
            )
            return None
        
        return {
            'entry': float(entry),
            'sl': float(sl),
            'tp1': float(tp1),
            'tp2': float(tp2) if tp2 is not None else None,
            'risk_r': float(risk_r)
        }
    
    def _build_signal_data(
        self,
        symbol: str,
        direction: str,
        mode: str,
        score_total: float,
        score_components: Dict[str, float],
        df: pd.DataFrame,
        indicators: pd.DataFrame,
        initiator_idx: int,
        confirm_idx: int,
        levels: Dict
    ) -> Dict:
        """
        Собрать все данные для JSONL лога согласно спецификации
        """
        # Signal ID - берем timestamp из колонки open_time, а не из индекса
        if 'open_time' in indicators.columns:
            timestamp_val = indicators['open_time'].iloc[confirm_idx]
        else:
            timestamp_val = indicators.index[confirm_idx]
        
        if isinstance(timestamp_val, pd.Timestamp):
            timestamp = timestamp_val
        else:
            timestamp = pd.to_datetime(timestamp_val)
        
        signal_id = hashlib.md5(
            f"{symbol}_{timestamp.isoformat()}_{direction}".encode()
        ).hexdigest()[:16]
        
        # Данные инициатора ([2])
        init_open = indicators['open'].iloc[initiator_idx]
        init_high = indicators['high'].iloc[initiator_idx]
        init_low = indicators['low'].iloc[initiator_idx]
        init_close = indicators['close'].iloc[initiator_idx]
        init_atr = indicators['atr'].iloc[initiator_idx]
        init_ema200 = indicators['ema200'].iloc[initiator_idx]
        
        # Данные подтверждения ([1])
        conf_open = indicators['open'].iloc[confirm_idx]
        conf_high = indicators['high'].iloc[confirm_idx]
        conf_low = indicators['low'].iloc[confirm_idx]
        conf_close = indicators['close'].iloc[confirm_idx]
        conf_atr = indicators['atr'].iloc[confirm_idx]
        conf_ema200 = indicators['ema200'].iloc[confirm_idx]
        
        # EMA на инициаторе
        init_ema5 = indicators['ema5'].iloc[initiator_idx]
        init_ema9 = indicators['ema9'].iloc[initiator_idx]
        init_ema13 = indicators['ema13'].iloc[initiator_idx]
        init_ema21 = indicators['ema21'].iloc[initiator_idx]
        
        # EMA на подтверждении
        conf_ema5 = indicators['ema5'].iloc[confirm_idx]
        conf_ema9 = indicators['ema9'].iloc[confirm_idx]
        conf_ema13 = indicators['ema13'].iloc[confirm_idx]
        conf_ema21 = indicators['ema21'].iloc[confirm_idx]
        
        # ATR полосы
        init_atr_upper = indicators['atr_upper'].iloc[initiator_idx]
        init_atr_lower = indicators['atr_lower'].iloc[initiator_idx]
        conf_atr_upper = indicators['atr_upper'].iloc[confirm_idx]
        conf_atr_lower = indicators['atr_lower'].iloc[confirm_idx]
        
        # Slope EMA200
        ema200_10bars_ago = indicators['ema200'].iloc[confirm_idx - 10]
        slope200_norm = (conf_ema200 - ema200_10bars_ago) / conf_atr
        
        # Веер EMA state
        if conf_ema5 > conf_ema9 and conf_ema9 > conf_ema13 and conf_ema13 > conf_ema21:
            ema_fan_state = 'bullish'
        elif conf_ema5 < conf_ema9 and conf_ema9 < conf_ema13 and conf_ema13 < conf_ema21:
            ema_fan_state = 'bearish'
        else:
            ema_fan_state = 'flat'
        
        ema_fan_spread_norm = abs(conf_ema5 - conf_ema21) / conf_atr
        
        # Свечные метрики
        init_body_size_atr = abs(init_close - init_open) / init_atr
        init_upper_wick_atr = (init_high - max(init_open, init_close)) / init_atr
        init_lower_wick_atr = (min(init_open, init_close) - init_low) / init_atr
        
        conf_body_size_atr = abs(conf_close - conf_open) / conf_atr
        conf_upper_wick_atr = (conf_high - max(conf_open, conf_close)) / conf_atr
        conf_lower_wick_atr = (min(conf_open, conf_close) - conf_low) / conf_atr
        
        if direction == 'long':
            init_body_cross_type = 'up'
            conf_depth_atr = (conf_close - conf_ema200) / conf_atr
            gap_to_outer_band_atr = (conf_atr_upper - conf_close) / conf_atr
        else:
            init_body_cross_type = 'down'
            conf_depth_atr = (conf_ema200 - conf_close) / conf_atr
            gap_to_outer_band_atr = (conf_close - conf_atr_lower) / conf_atr
        
        conf_color = 'green' if conf_close > conf_open else 'red'
        
        # Касание EMA200
        touch_ema200 = bool(conf_low <= conf_ema200 <= conf_high)
        
        # Положение close относительно веера
        if conf_close > max(conf_ema5, conf_ema9, conf_ema13, conf_ema21):
            close_vs_ema_fan = 'above_all'
        elif conf_close < min(conf_ema5, conf_ema9, conf_ema13, conf_ema21):
            close_vs_ema_fan = 'below_all'
        else:
            close_vs_ema_fan = 'inside'
        
        # Касания EMA200 за 5 баров
        touches_ema200_last5 = 0
        for i in range(initiator_idx - 5, initiator_idx):
            bar_low = indicators['low'].iloc[i]
            bar_high = indicators['high'].iloc[i]
            ema200_bar = indicators['ema200'].iloc[i]
            if bar_low <= ema200_bar <= bar_high:
                touches_ema200_last5 += 1
        
        # Trend tag
        if slope200_norm >= 0.20 and ema_fan_state == 'bullish':
            trend_tag = 'up'
        elif slope200_norm <= -0.20 and ema_fan_state == 'bearish':
            trend_tag = 'down'
        else:
            trend_tag = 'side'
        
        # Retest tag
        retest_tag = bool(score_components.get('retest_tag', 0) == 1)
        
        # Break and base tag
        break_and_base_tag = bool(score_components.get('break_and_base', 0) == 1)
        
        # Swing High/Low
        swing_high_price = float(indicators['swing_high'].iloc[confirm_idx])
        swing_low_price = float(indicators['swing_low'].iloc[confirm_idx])
        
        # Создать запись через SignalLogger
        timestamp_dt = timestamp.to_pydatetime() if hasattr(timestamp, 'to_pydatetime') else timestamp
        if timestamp_dt.tzinfo is None:
            timestamp_dt = timestamp_dt.replace(tzinfo=pytz.UTC)
        
        signal_data = self.signal_logger.create_signal_entry(
            # Метаданные
            signal_id=signal_id,
            timestamp_open=timestamp_dt,
            symbol=symbol,
            timeframe=self.timeframe,
            direction=direction,
            pattern='body_cross',
            mode=mode,
            score_total=score_total,
            score_components=score_components,
            
            # Цена/уровни
            entry_price=levels['entry'],
            sl_price=levels['sl'],
            tp1_price=levels['tp1'],
            tp2_price=levels['tp2'],
            risk_r=levels['risk_r'],
            
            # EMA/ATR инициатор
            initiator_ema5=float(init_ema5),
            initiator_ema9=float(init_ema9),
            initiator_ema13=float(init_ema13),
            initiator_ema21=float(init_ema21),
            initiator_ema200=float(init_ema200),
            initiator_atr=float(init_atr),
            initiator_atr_upper_band=float(init_atr_upper),
            initiator_atr_lower_band=float(init_atr_lower),
            
            # EMA/ATR подтверждение
            confirm_ema5=float(conf_ema5),
            confirm_ema9=float(conf_ema9),
            confirm_ema13=float(conf_ema13),
            confirm_ema21=float(conf_ema21),
            confirm_ema200=float(conf_ema200),
            confirm_atr=float(conf_atr),
            confirm_atr_upper_band=float(conf_atr_upper),
            confirm_atr_lower_band=float(conf_atr_lower),
            slope_ema200_norm=float(slope200_norm),
            ema_fan_state=ema_fan_state,
            ema_fan_spread_norm=float(ema_fan_spread_norm),
            
            # Свечные метрики - инициатор
            initiator_open=float(init_open),
            initiator_high=float(init_high),
            initiator_low=float(init_low),
            initiator_close=float(init_close),
            initiator_body_size_atr=float(init_body_size_atr),
            initiator_upper_wick_atr=float(init_upper_wick_atr),
            initiator_lower_wick_atr=float(init_lower_wick_atr),
            initiator_body_cross_type=init_body_cross_type,
            
            # Свечные метрики - подтверждение
            confirm_open=float(conf_open),
            confirm_high=float(conf_high),
            confirm_low=float(conf_low),
            confirm_close=float(conf_close),
            confirm_body_size_atr=float(conf_body_size_atr),
            confirm_upper_wick_atr=float(conf_upper_wick_atr),
            confirm_lower_wick_atr=float(conf_lower_wick_atr),
            confirm_depth_atr=float(conf_depth_atr),
            confirm_color=conf_color,
            touch_ema200=touch_ema200,
            close_vs_ema_fan=close_vs_ema_fan,
            gap_to_outer_band_atr=float(gap_to_outer_band_atr),
            
            # Контекст
            touches_ema200_last5=touches_ema200_last5,
            trend_tag=trend_tag,
            retest_tag=retest_tag,
            break_and_base_tag=break_and_base_tag,
            swing_high_price=swing_high_price,
            swing_high_index=None,  # Можно добавить если нужно
            swing_low_price=swing_low_price,
            swing_low_index=None,
            
            # Volume (если есть)
            initiator_volume=float(indicators['volume'].iloc[initiator_idx]) if 'volume' in indicators else None,
            confirm_volume=float(indicators['volume'].iloc[confirm_idx]) if 'volume' in indicators else None
        )
        
        return signal_data
