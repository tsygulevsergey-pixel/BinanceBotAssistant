"""
Price Action паттерны для Action Price Strategy
"""
import pandas as pd
from typing import Optional, Dict, List
from .utils import get_eps


class PriceActionPatterns:
    """Детектор Price Action паттернов"""
    
    def __init__(self, config: dict):
        """
        Args:
            config: Конфигурация из config.yaml['action_price']['patterns']
        """
        self.config = config
        self.enabled = config.get('enabled', [])
        self.eps_mult = config.get('eps_mult', 0.0001)
        
        # Pin-Bar параметры
        pb_cfg = config.get('pin_bar', {})
        self.pb_wick_body_ratio = pb_cfg.get('wick_body_ratio', 2.0)
        self.pb_wick_range_ratio = pb_cfg.get('wick_range_ratio', 0.6)
        self.pb_opposite_wick_max = pb_cfg.get('opposite_wick_max', 0.25)
        self.pb_close_position = pb_cfg.get('close_position', 0.6)
        
        # Engulfing параметры
        eng_cfg = config.get('engulfing', {})
        self.eng_body_ratio = eng_cfg.get('body_ratio', 0.8)
        
        # Fakey параметры
        fakey_cfg = config.get('fakey', {})
        self.fakey_sequence_bars = fakey_cfg.get('sequence_bars', 3)
    
    def detect_pin_bar(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Детектировать Pin-Bar паттерн
        
        Returns:
            Dict с деталями паттерна или None
        """
        if 'pin_bar' not in self.enabled or len(df) < 1:
            return None
        
        c0 = df.iloc[-1]  # Последняя свеча
        eps = get_eps(c0['close'], self.eps_mult)
        
        open_price = c0['open']
        close_price = c0['close']
        high_price = c0['high']
        low_price = c0['low']
        
        # Бычий Pin-Bar (hammer)
        lower_wick = min(open_price, close_price) - low_price
        upper_wick_bull = high_price - max(open_price, close_price)
        body_bull = abs(close_price - open_price)
        range_total = high_price - low_price
        
        if range_total > eps:
            is_bullish_pin = (
                lower_wick >= self.pb_wick_body_ratio * body_bull and
                lower_wick >= self.pb_wick_range_ratio * range_total and
                upper_wick_bull <= self.pb_opposite_wick_max * range_total and
                close_price >= (low_price + self.pb_close_position * range_total)
            )
            
            if is_bullish_pin:
                return {
                    'type': 'pin_bar',
                    'direction': 'LONG',
                    'entry_trigger': high_price,  # Пробой носа pin bar
                    'stop_reference': low_price,  # За хвостом
                    'candle_data': {
                        'open': open_price,
                        'close': close_price,
                        'high': high_price,
                        'low': low_price
                    }
                }
        
        # Медвежий Pin-Bar (shooting star)
        upper_wick_bear = high_price - max(open_price, close_price)
        lower_wick_bear = min(open_price, close_price) - low_price
        body_bear = abs(close_price - open_price)
        
        if range_total > eps:
            is_bearish_pin = (
                upper_wick_bear >= self.pb_wick_body_ratio * body_bear and
                upper_wick_bear >= self.pb_wick_range_ratio * range_total and
                lower_wick_bear <= self.pb_opposite_wick_max * range_total and
                close_price <= (high_price - self.pb_close_position * range_total)
            )
            
            if is_bearish_pin:
                return {
                    'type': 'pin_bar',
                    'direction': 'SHORT',
                    'entry_trigger': low_price,  # Пробой носа вниз
                    'stop_reference': high_price,  # За хвостом
                    'candle_data': {
                        'open': open_price,
                        'close': close_price,
                        'high': high_price,
                        'low': low_price
                    }
                }
        
        return None
    
    def detect_engulfing(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Детектировать Engulfing (Поглощение) паттерн
        
        Returns:
            Dict с деталями паттерна или None
        """
        if 'engulfing' not in self.enabled or len(df) < 2:
            return None
        
        c0 = df.iloc[-1]  # Текущая свеча
        c1 = df.iloc[-2]  # Предыдущая свеча
        eps = get_eps(c0['close'], self.eps_mult)
        
        # Медвежий Engulfing
        bearish_engulfing = (
            c0['high'] >= (c1['high'] - eps) and
            c0['low'] <= (c1['low'] + eps) and
            c0['close'] < c0['open'] and
            abs(c0['close'] - c0['open']) >= self.eng_body_ratio * abs(c1['close'] - c1['open'])
        )
        
        if bearish_engulfing:
            return {
                'type': 'engulfing',
                'direction': 'SHORT',
                'entry_trigger': c0['low'],  # Пробой низа поглощающей свечи
                'stop_reference': c0['high'],  # За противоположным экстремумом
                'candle_data': {
                    'open': c0['open'],
                    'close': c0['close'],
                    'high': c0['high'],
                    'low': c0['low']
                }
            }
        
        # Бычий Engulfing
        bullish_engulfing = (
            c0['high'] >= (c1['high'] - eps) and
            c0['low'] <= (c1['low'] + eps) and
            c0['close'] > c0['open'] and
            abs(c0['close'] - c0['open']) >= self.eng_body_ratio * abs(c1['close'] - c1['open'])
        )
        
        if bullish_engulfing:
            return {
                'type': 'engulfing',
                'direction': 'LONG',
                'entry_trigger': c0['high'],  # Пробой верха поглощающей свечи
                'stop_reference': c0['low'],  # За противоположным экстремумом
                'candle_data': {
                    'open': c0['open'],
                    'close': c0['close'],
                    'high': c0['high'],
                    'low': c0['low']
                }
            }
        
        return None
    
    def detect_inside_bar(self, df: pd.DataFrame, trend_direction: str) -> Optional[Dict]:
        """
        Детектировать Inside-Bar паттерн
        
        Args:
            df: DataFrame
            trend_direction: Направление тренда для пробоя ('LONG' или 'SHORT')
        
        Returns:
            Dict с деталями паттерна или None
        """
        if 'inside_bar' not in self.enabled or len(df) < 2:
            return None
        
        c0 = df.iloc[-1]  # Inside bar
        c1 = df.iloc[-2]  # Mother bar
        eps = get_eps(c0['close'], self.eps_mult)
        
        # Проверка inside bar: C0 полностью внутри C1
        is_inside = (
            c0['high'] <= (c1['high'] + eps) and
            c0['low'] >= (c1['low'] - eps)
        )
        
        if not is_inside:
            return None
        
        # Пробой mother bar в сторону тренда
        if trend_direction == 'LONG':
            return {
                'type': 'inside_bar',
                'direction': 'LONG',
                'entry_trigger': c1['high'],  # Пробой верха mother bar
                'stop_reference': c1['low'],  # За противоположной стороной mother
                'candle_data': {
                    'inside': {'open': c0['open'], 'close': c0['close'], 'high': c0['high'], 'low': c0['low']},
                    'mother': {'open': c1['open'], 'close': c1['close'], 'high': c1['high'], 'low': c1['low']}
                }
            }
        elif trend_direction == 'SHORT':
            return {
                'type': 'inside_bar',
                'direction': 'SHORT',
                'entry_trigger': c1['low'],  # Пробой низа mother bar
                'stop_reference': c1['high'],  # За противоположной стороной mother
                'candle_data': {
                    'inside': {'open': c0['open'], 'close': c0['close'], 'high': c0['high'], 'low': c0['low']},
                    'mother': {'open': c1['open'], 'close': c1['close'], 'high': c1['high'], 'low': c1['low']}
                }
            }
        
        return None
    
    def detect_fakey(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Детектировать Fakey (ложный пробой inside-bar) паттерн
        
        Returns:
            Dict с деталями паттерна или None
        """
        if 'fakey' not in self.enabled or len(df) < 3:
            return None
        
        c0 = df.iloc[-1]  # Свеча ложного пробоя
        c1 = df.iloc[-2]  # Inside bar
        c2 = df.iloc[-3]  # Mother bar
        eps = get_eps(c0['close'], self.eps_mult)
        
        # Проверка: C1 - inside bar от C2
        c1_is_inside = (
            c1['high'] <= (c2['high'] + eps) and
            c1['low'] >= (c2['low'] - eps)
        )
        
        if not c1_is_inside:
            return None
        
        # Проверка ложного пробоя вверх (bearish fakey)
        false_breakout_up = (
            c0['high'] > c2['high'] and  # Пробой верха mother
            c0['close'] < c2['high']  # Но закрытие внутри диапазона
        )
        
        if false_breakout_up:
            return {
                'type': 'fakey',
                'direction': 'SHORT',  # Вход против пробоя
                'entry_trigger': c0['low'],  # Стоп ордер за телом C0
                'stop_reference': c0['high'],  # За экстремумом ложного пробоя
                'candle_data': {
                    'fakey': {'open': c0['open'], 'close': c0['close'], 'high': c0['high'], 'low': c0['low']},
                    'inside': {'open': c1['open'], 'close': c1['close'], 'high': c1['high'], 'low': c1['low']},
                    'mother': {'open': c2['open'], 'close': c2['close'], 'high': c2['high'], 'low': c2['low']}
                }
            }
        
        # Проверка ложного пробоя вниз (bullish fakey)
        false_breakout_down = (
            c0['low'] < c2['low'] and  # Пробой низа mother
            c0['close'] > c2['low']  # Но закрытие внутри диапазона
        )
        
        if false_breakout_down:
            return {
                'type': 'fakey',
                'direction': 'LONG',  # Вход против пробоя
                'entry_trigger': c0['high'],  # Стоп ордер за телом C0
                'stop_reference': c0['low'],  # За экстремумом ложного пробоя
                'candle_data': {
                    'fakey': {'open': c0['open'], 'close': c0['close'], 'high': c0['high'], 'low': c0['low']},
                    'inside': {'open': c1['open'], 'close': c1['close'], 'high': c1['high'], 'low': c1['low']},
                    'mother': {'open': c2['open'], 'close': c2['close'], 'high': c2['high'], 'low': c2['low']}
                }
            }
        
        return None
    
    def detect_ppr(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Детектировать ППР (Пробой Предыдущего Разворота) - двухсвечный разворот
        
        Returns:
            Dict с деталями паттерна или None
        """
        if 'ppr' not in self.enabled or len(df) < 2:
            return None
        
        c0 = df.iloc[-1]  # Текущая свеча
        c1 = df.iloc[-2]  # Предыдущая свеча
        eps = get_eps(c0['close'], self.eps_mult)
        
        # Рассчитываем силу пробоя
        c1_range = c1['high'] - c1['low']
        
        # Медвежий ППР: закрытие C0 ниже низа C1 + фильтр силы
        bearish_ppr = (
            c0['close'] < (c1['low'] - eps) and
            c0['close'] < c0['open'] and  # Медвежья свеча
            abs(c0['close'] - c0['open']) >= 0.3 * c1_range  # Тело C0 >= 30% от range C1
        )
        
        if bearish_ppr:
            return {
                'type': 'ppr',
                'direction': 'SHORT',
                'entry_trigger': c0['close'],  # Вход по рынку или стоп за закрытием
                'stop_reference': c0['high'],  # За экстремумом C0
                'candle_data': {
                    'current': {'open': c0['open'], 'close': c0['close'], 'high': c0['high'], 'low': c0['low']},
                    'previous': {'open': c1['open'], 'close': c1['close'], 'high': c1['high'], 'low': c1['low']}
                }
            }
        
        # Бычий ППР: закрытие C0 выше верха C1 + фильтр силы
        bullish_ppr = (
            c0['close'] > (c1['high'] + eps) and
            c0['close'] > c0['open'] and  # Бычья свеча
            abs(c0['close'] - c0['open']) >= 0.3 * c1_range  # Тело C0 >= 30% от range C1
        )
        
        if bullish_ppr:
            return {
                'type': 'ppr',
                'direction': 'LONG',
                'entry_trigger': c0['close'],  # Вход по рынку или стоп за закрытием
                'stop_reference': c0['low'],  # За экстремумом C0
                'candle_data': {
                    'current': {'open': c0['open'], 'close': c0['close'], 'high': c0['high'], 'low': c0['low']},
                    'previous': {'open': c1['open'], 'close': c1['close'], 'high': c1['high'], 'low': c1['low']}
                }
            }
        
        return None
    
    def detect_all_patterns(self, df: pd.DataFrame, trend_direction: Optional[str] = None) -> List[Dict]:
        """
        Детектировать все включённые паттерны
        
        Args:
            df: DataFrame со свечами
            trend_direction: Направление тренда для inside-bar (опционально)
            
        Returns:
            Список найденных паттернов
        """
        patterns = []
        
        # Pin-Bar
        pin = self.detect_pin_bar(df)
        if pin:
            patterns.append(pin)
        
        # Engulfing
        eng = self.detect_engulfing(df)
        if eng:
            patterns.append(eng)
        
        # Inside-Bar (только если известно направление тренда)
        if trend_direction:
            inside = self.detect_inside_bar(df, trend_direction)
            if inside:
                patterns.append(inside)
        
        # Fakey
        fakey = self.detect_fakey(df)
        if fakey:
            patterns.append(fakey)
        
        # ППР
        ppr = self.detect_ppr(df)
        if ppr:
            patterns.append(ppr)
        
        return patterns
