"""
Anchored VWAP с sticky (липкой) логикой якорей для Action Price
"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta

from .utils import calculate_mtr


class AnchoredVWAP:
    """Anchored VWAP с sticky якорями"""
    
    def __init__(self, config: dict):
        """
        Args:
            config: Конфигурация из config.yaml['action_price']['avwap']
        """
        self.config = config
        
        # Fractal параметры
        self.fractal_k_1h = config.get('fractal_k_1h', 3)
        self.fractal_k_4h = config.get('fractal_k_4h', 2)
        
        # Импульс
        self.impulse_mult = config.get('impulse_mult', 1.5)
        self.impulse_bars_1h = config.get('impulse_bars_1h', 12)
        self.impulse_bars_4h = config.get('impulse_bars_4h', 10)
        
        # Sticky логика
        self.lock_bars_1h = config.get('lock_bars_1h', 8)
        self.lock_bars_4h = config.get('lock_bars_4h', 4)
        self.ttl_bars_1h = config.get('ttl_bars_1h', 60)
        self.ttl_bars_4h = config.get('ttl_bars_4h', 30)
        
        # Переякоривание
        self.structure_break_closes = config.get('structure_break_closes', 3)
        self.structure_break_closes_4h = config.get('structure_break_closes_4h', 2)
        self.structure_distance_mult = config.get('structure_distance_mult', 0.25)
        
        # Конфлюэнс
        self.confluence_tolerance_mult = config.get('confluence_tolerance_mult', 0.5)
        
        # V2: Гистерезис (2 из 3 условий)
        v2_config = config.get('v2', {})
        self.v2_hysteresis_impulse_mult = v2_config.get('hysteresis_impulse_mult', 1.5)
        self.v2_hysteresis_min_bars_1h = v2_config.get('hysteresis_min_bars_1h', 30)
        self.v2_hysteresis_distance_mult = v2_config.get('hysteresis_distance_mult', 2.0)
        self.v2_conditions_required = v2_config.get('hysteresis_conditions_required', 2)
        self.v2_anti_dither_days = v2_config.get('anti_dither_min_days', 1)
        
        # Кэш якорей по символам
        self.anchors = {}  # {symbol: {tf: {anchor_data}}}
        
        # V2: История переякорений для анти-дребезга
        self.reanchor_history = {}  # {symbol: {tf: [timestamps]}}
    
    def find_fractal_swings(self, df: pd.DataFrame, k: int) -> Dict[str, list]:
        """Найти fractal swing точки"""
        highs = []
        lows = []
        
        for i in range(k, len(df) - k):
            # High fractal
            is_high = all(df['high'].iloc[i] > df['high'].iloc[j] 
                         for j in range(i - k, i + k + 1) if j != i)
            if is_high:
                highs.append(i)
            
            # Low fractal
            is_low = all(df['low'].iloc[i] < df['low'].iloc[j] 
                        for j in range(i - k, i + k + 1) if j != i)
            if is_low:
                lows.append(i)
        
        return {'highs': highs, 'lows': lows}
    
    def calculate_impulse(self, df: pd.DataFrame, pivot_idx: int, 
                         lookforward_bars: int, direction: str) -> float:
        """
        Рассчитать импульс от pivot точки
        
        Args:
            df: DataFrame
            pivot_idx: Индекс pivot свечи
            lookforward_bars: Сколько баров смотреть вперёд
            direction: 'up' или 'down'
            
        Returns:
            Величина импульса
        """
        if pivot_idx + lookforward_bars >= len(df):
            return 0.0
        
        forward_slice = df.iloc[pivot_idx:pivot_idx + lookforward_bars + 1]
        
        if direction == 'up':
            pivot_price = forward_slice['low'].iloc[0]
            max_price = forward_slice['high'].max()
            return max_price - pivot_price
        else:  # down
            pivot_price = forward_slice['high'].iloc[0]
            min_price = forward_slice['low'].min()
            return pivot_price - min_price
    
    def validate_impulse_confirmation(self, df: pd.DataFrame, pivot_idx: int,
                                     pivot_price: float, direction: str,
                                     mtr: float, lookforward: int) -> bool:
        """
        Проверить подтверждение импульса (2 закрытия или ретест)
        
        Args:
            df: DataFrame
            pivot_idx: Индекс pivot
            pivot_price: Цена pivot
            direction: Направление 'up'/'down'
            mtr: median True Range
            lookforward: Баров для проверки
            
        Returns:
            True если подтверждено
        """
        if pivot_idx + lookforward >= len(df):
            return False
        
        forward = df.iloc[pivot_idx:pivot_idx + lookforward + 1]
        threshold = 0.25 * mtr
        
        # Вариант 1: 2 последовательных закрытия в сторону выхода
        consecutive_closes = 0
        for close in forward['close']:
            if direction == 'up' and close > pivot_price + threshold:
                consecutive_closes += 1
                if consecutive_closes >= 2:
                    return True
            elif direction == 'down' and close < pivot_price - threshold:
                consecutive_closes += 1
                if consecutive_closes >= 2:
                    return True
            else:
                consecutive_closes = 0
        
        # Вариант 2: Ретест с откатом не глубже 50% и новый уход
        impulse = self.calculate_impulse(df, pivot_idx, lookforward, direction)
        if impulse > 0:
            for i in range(1, len(forward)):
                if direction == 'up':
                    pullback = pivot_price + impulse - forward['low'].iloc[i]
                    if pullback <= 0.5 * impulse and forward['close'].iloc[i] > pivot_price + threshold:
                        return True
                else:
                    pullback = forward['high'].iloc[i] - (pivot_price - impulse)
                    if pullback <= 0.5 * impulse and forward['close'].iloc[i] < pivot_price - threshold:
                        return True
        
        return False
    
    def find_valid_swing(self, df: pd.DataFrame, timeframe: str) -> Optional[Dict]:
        """
        Найти валидный swing для якоря
        
        Args:
            df: DataFrame
            timeframe: '1h' или '4h'
            
        Returns:
            Данные swing или None
        """
        k = self.fractal_k_1h if timeframe == '1h' else self.fractal_k_4h
        impulse_bars = self.impulse_bars_1h if timeframe == '1h' else self.impulse_bars_4h
        
        mtr = calculate_mtr(df, period=20)
        if mtr == 0:
            return None
        
        swings = self.find_fractal_swings(df, k)
        min_impulse = self.impulse_mult * mtr
        
        # Проверяем свинги от новых к старым
        all_swings = []
        
        # Bullish swings (low fractals)
        for idx in reversed(swings['lows']):
            impulse = self.calculate_impulse(df, idx, impulse_bars, 'up')
            if impulse >= min_impulse:
                confirmed = self.validate_impulse_confirmation(
                    df, idx, df['low'].iloc[idx], 'up', mtr, impulse_bars
                )
                if confirmed:
                    all_swings.append({
                        'index': idx,
                        'price': df['low'].iloc[idx],
                        'timestamp': df.index[idx],
                        'direction': 'up',
                        'impulse': impulse,
                        'impulse_ratio': impulse / mtr
                    })
        
        # Bearish swings (high fractals)
        for idx in reversed(swings['highs']):
            impulse = self.calculate_impulse(df, idx, impulse_bars, 'down')
            if impulse >= min_impulse:
                confirmed = self.validate_impulse_confirmation(
                    df, idx, df['high'].iloc[idx], 'down', mtr, impulse_bars
                )
                if confirmed:
                    all_swings.append({
                        'index': idx,
                        'price': df['high'].iloc[idx],
                        'timestamp': df.index[idx],
                        'direction': 'down',
                        'impulse': impulse,
                        'impulse_ratio': impulse / mtr
                    })
        
        # Возвращаем самый свежий
        if all_swings:
            return max(all_swings, key=lambda x: x['index'])
        
        return None
    
    def check_structure_break(self, df: pd.DataFrame, anchor_price: float,
                              timeframe: str) -> bool:
        """
        Проверить слом структуры против текущего якоря
        
        Args:
            df: DataFrame
            anchor_price: Цена текущего якоря (AVWAP)
            timeframe: '1h' или '4h'
            
        Returns:
            True если структура сломана
        """
        k_closes = self.structure_break_closes if timeframe == '1h' else self.structure_break_closes_4h
        
        if len(df) < k_closes:
            return False
        
        recent = df.iloc[-k_closes:]
        mtr = calculate_mtr(df, period=20)
        threshold = self.structure_distance_mult * mtr
        
        # Проверяем все закрытия по другую сторону AVWAP
        distances = []
        all_above = True
        all_below = True
        
        for close in recent['close']:
            if close <= anchor_price:
                all_above = False
            if close >= anchor_price:
                all_below = False
            distances.append(abs(close - anchor_price))
        
        # Структура сломана если все по одну сторону и средняя дистанция >= threshold
        if (all_above or all_below) and np.mean(distances) >= threshold:
            return True
        
        return False
    
    def check_hysteresis_v2(self, symbol: str, df: pd.DataFrame, timeframe: str,
                           anchor: Dict, parent_config: Optional[dict] = None) -> bool:
        """
        V2: Проверка гистерезиса "2 из 3 условий" для переякорения
        
        Условия:
        (a) Импульс нового свинга >= 1.5×MTR
        (b) Прошло >= 30 баров H1 с момента якоря (масштабируется по TF)
        (c) Цена ушла >= K×ATR от текущего AVWAP
        
        Возвращает True если выполнены минимум 2 из 3 условий
        """
        if not parent_config or parent_config.get('version') != 'v2':
            return False  # V1 - обычная логика
        
        # Получаем параметры
        mtr = calculate_mtr(df, period=20)
        if mtr == 0:
            return False
        
        current_idx = len(df) - 1
        anchor_idx = anchor['index']
        bars_since = current_idx - anchor_idx
        
        # Масштабируем bars для разных TF
        min_bars = self.v2_hysteresis_min_bars_1h
        if timeframe == '4h':
            min_bars = min_bars // 4  # ~7-8 баров
        elif timeframe == '1d':
            min_bars = min_bars // 24  # ~1-2 бара
        
        # Проверяем 3 условия
        conditions_met = 0
        
        # (a) Новый свинг с достаточным импульсом
        new_swing = self.find_valid_swing(df, timeframe)
        if new_swing and new_swing['impulse'] >= self.v2_hysteresis_impulse_mult * mtr:
            conditions_met += 1
        
        # (b) Прошло достаточно времени
        if bars_since >= min_bars:
            conditions_met += 1
        
        # (c) Цена далеко от якоря
        avwap_value = self.calculate_avwap_from_anchor(df, anchor)
        current_price = df['close'].iloc[-1]
        distance = abs(current_price - avwap_value)
        threshold = self.v2_hysteresis_distance_mult * mtr
        
        if distance >= threshold:
            conditions_met += 1
        
        return conditions_met >= self.v2_conditions_required
    
    def check_anti_dither_v2(self, symbol: str, timeframe: str, 
                            new_anchor_time: datetime, parent_config: Optional[dict] = None) -> bool:
        """
        V2: Анти-дребезг - минимум 1 день между переякорениями
        
        Returns:
            True если можно переякорить (прошло >= 1 день)
        """
        if not parent_config or parent_config.get('version') != 'v2':
            return True  # V1 - без ограничений
        
        if symbol not in self.reanchor_history:
            self.reanchor_history[symbol] = {}
        
        if timeframe not in self.reanchor_history[symbol]:
            self.reanchor_history[symbol][timeframe] = []
            return True
        
        # Получаем последнее переякорение
        history = self.reanchor_history[symbol][timeframe]
        if not history:
            return True
        
        last_reanchor = history[-1]
        time_diff = new_anchor_time - last_reanchor
        min_days = timedelta(days=self.v2_anti_dither_days)
        
        return time_diff >= min_days
    
    def should_reanchor(self, symbol: str, df: pd.DataFrame, timeframe: str) -> bool:
        """
        Проверить нужно ли переякорить
        
        Args:
            symbol: Символ
            df: DataFrame
            timeframe: '1h' или '4h'
            
        Returns:
            True если нужно переякорить
        """
        if symbol not in self.anchors or timeframe not in self.anchors[symbol]:
            return True  # Якоря нет - создать новый
        
        anchor = self.anchors[symbol][timeframe]
        anchor_idx = anchor['index']
        current_idx = len(df) - 1
        bars_since_anchor = current_idx - anchor_idx
        
        lock_bars = self.lock_bars_1h if timeframe == '1h' else self.lock_bars_4h
        ttl_bars = self.ttl_bars_1h if timeframe == '1h' else self.ttl_bars_4h
        
        # Гистерезис - запрет переякоривания в lock period
        if bars_since_anchor < lock_bars:
            # Исключение: слом структуры
            avwap_value = self.calculate_avwap_from_anchor(df, anchor)
            if self.check_structure_break(df, avwap_value, timeframe):
                return True
            return False
        
        # TTL истёк и есть новый валидный свинг
        if bars_since_anchor > ttl_bars:
            new_swing = self.find_valid_swing(df, timeframe)
            mtr = calculate_mtr(df, period=20)
            if new_swing and new_swing['impulse'] >= 1.0 * mtr:
                return True
        
        # Слом структуры
        avwap_value = self.calculate_avwap_from_anchor(df, anchor)
        if self.check_structure_break(df, avwap_value, timeframe):
            return True
        
        return False
    
    def calculate_avwap_from_anchor(self, df: pd.DataFrame, anchor: Dict) -> float:
        """
        Рассчитать AVWAP от якоря до текущей свечи
        
        Args:
            df: DataFrame
            anchor: Данные якоря
            
        Returns:
            Текущее значение AVWAP
        """
        anchor_idx = anchor['index']
        
        if anchor_idx >= len(df):
            return anchor['price']
        
        # Slice от якоря до конца
        avwap_slice = df.iloc[anchor_idx:]
        
        # VWAP = sum(price × volume) / sum(volume)
        typical_price = (avwap_slice['high'] + avwap_slice['low'] + avwap_slice['close']) / 3
        pv = typical_price * avwap_slice['volume']
        
        if avwap_slice['volume'].sum() == 0:
            return anchor['price']
        
        avwap = pv.sum() / avwap_slice['volume'].sum()
        return float(avwap)
    
    def get_avwap(self, symbol: str, df: pd.DataFrame, timeframe: str,
                  force_recalc: bool = False, parent_config: Optional[dict] = None) -> Optional[float]:
        """
        Получить AVWAP для символа и таймфрейма
        
        Args:
            symbol: Символ
            df: DataFrame
            timeframe: '1h' или '4h' или '1d'
            force_recalc: Принудительный пересчёт
            parent_config: Конфиг для определения версии (V1/V2)
            
        Returns:
            Значение AVWAP или None
        """
        if symbol not in self.anchors:
            self.anchors[symbol] = {}
        
        # V2: проверка гистерезиса и анти-дребезга
        should_reanchor = False
        
        if force_recalc:
            should_reanchor = True
        elif parent_config and parent_config.get('version') == 'v2':
            # V2: улучшенная логика переякорения
            if timeframe in self.anchors[symbol]:
                anchor = self.anchors[symbol][timeframe]
                # Проверка 2 из 3 условий
                if self.check_hysteresis_v2(symbol, df, timeframe, anchor, parent_config):
                    # Нашли кандидата - проверяем анти-дребезг
                    new_swing = self.find_valid_swing(df, timeframe)
                    if new_swing:
                        new_time = new_swing['timestamp']
                        if self.check_anti_dither_v2(symbol, timeframe, new_time, parent_config):
                            should_reanchor = True
            else:
                should_reanchor = True  # Нет якоря - создать
        else:
            # V1: обычная логика
            should_reanchor = self.should_reanchor(symbol, df, timeframe)
        
        # Переякорить если нужно
        if should_reanchor:
            new_swing = self.find_valid_swing(df, timeframe)
            if new_swing:
                self.anchors[symbol][timeframe] = new_swing
                # V2: записать в историю
                if parent_config and parent_config.get('version') == 'v2':
                    if symbol not in self.reanchor_history:
                        self.reanchor_history[symbol] = {}
                    if timeframe not in self.reanchor_history[symbol]:
                        self.reanchor_history[symbol][timeframe] = []
                    self.reanchor_history[symbol][timeframe].append(new_swing['timestamp'])
            elif timeframe not in self.anchors[symbol]:
                return None  # Нет якоря и не нашли новый
        
        # Рассчитываем AVWAP от текущего якоря
        if timeframe in self.anchors[symbol]:
            anchor = self.anchors[symbol][timeframe]
            return self.calculate_avwap_from_anchor(df, anchor)
        
        return None
    
    def get_dual_avwap(self, symbol: str, df_primary: pd.DataFrame, 
                       df_secondary: pd.DataFrame, execution_tf: str,
                       parent_config: Optional[dict] = None) -> Dict:
        """
        Получить Primary и Secondary AVWAP для сигналов
        
        Args:
            symbol: Символ
            df_primary: DataFrame для primary якоря
            df_secondary: DataFrame для secondary якоря
            execution_tf: Таймфрейм исполнения ('15m' или '1h')
            parent_config: Конфиг для определения версии (V1/V2)
            
        Returns:
            Dict с 'primary' и 'secondary' AVWAP
        """
        # Определяем таймфреймы якорей
        if execution_tf == '15m':
            primary_tf = self.config.get('anchor_15m_primary', '1h')
            secondary_tf = self.config.get('anchor_15m_secondary', '4h')
        else:  # 1h
            primary_tf = self.config.get('anchor_1h_primary', '4h')
            secondary_tf = self.config.get('anchor_1h_secondary', '1d')
        
        primary_avwap = self.get_avwap(symbol, df_primary, primary_tf, 
                                        parent_config=parent_config)
        secondary_avwap = self.get_avwap(symbol, df_secondary, secondary_tf,
                                          parent_config=parent_config)
        
        return {
            'primary': primary_avwap,
            'secondary': secondary_avwap,
            'primary_tf': primary_tf,
            'secondary_tf': secondary_tf
        }
    
    def check_confluence(self, price: float, avwap_value: Optional[float],
                        mtr_1h: float) -> bool:
        """
        Проверить конфлюэнс цены с AVWAP
        
        Args:
            price: Проверяемая цена
            avwap_value: Значение AVWAP
            mtr_1h: mTR для 1H (для tolerance)
            
        Returns:
            True если есть конфлюэнс
        """
        if avwap_value is None:
            return False
        
        tolerance = self.confluence_tolerance_mult * mtr_1h
        return abs(price - avwap_value) <= tolerance
