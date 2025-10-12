"""
Построение зон поддержки/сопротивления (S/R) для Action Price
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import hashlib
import math

from .utils import (
    calculate_mtr, calculate_zone_width, calculate_buffer,
    merge_overlapping_zones, filter_top_zones, is_zone_broken
)


class SRZoneBuilder:
    """Построитель зон поддержки и сопротивления"""
    
    def __init__(self, config: dict, parent_config: Optional[dict] = None):
        """
        Args:
            config: Конфигурация из config.yaml['action_price']['zones']
            parent_config: Полная конфигурация action_price для доступа к version
        """
        self.config = config
        self.parent_config = parent_config if parent_config is not None else {}
        
        # Определяем версию логики
        self.version = self.parent_config.get('version', 'v1')
        
        # Общие параметры
        self.lookback_days = config.get('lookback_days', 90)
        self.fractal_k_1d = config.get('fractal_k_1d', 2)
        self.fractal_k_4h = config.get('fractal_k_4h', 2)
        self.impulse_bars_check = config.get('impulse_bars_check', 3)
        self.impulse_atr_mult = config.get('impulse_atr_mult', 2.0)
        self.zone_width_mult = config.get('zone_width_mult', 0.5)
        self.zone_width_min_pct = config.get('zone_width_min_pct', 0.15)
        self.buffer_mult = config.get('buffer_mult', 0.25)
        self.merge_distance_mult = config.get('merge_distance_mult', 0.75)
        self.max_width_mult = config.get('max_width_mult', 1.25)
        self.top_zones_count = config.get('top_zones_count', 6)
        self.broken_closes = config.get('broken_closes', 3)
        
        # V2 параметры
        self.v2_config = config.get('v2', {})
        self.mtr_period_1d = self.v2_config.get('mtr_period_1d', 50)
        self.mtr_period_4h = self.v2_config.get('mtr_period_4h', 50)
        self.mtr_period_1h = self.v2_config.get('mtr_period_1h', 50)
        self.mtr_period_15m = self.v2_config.get('mtr_period_15m', 30)
        
        self.touch_shadow_ratio = self.v2_config.get('touch_shadow_in_zone_ratio', 0.33)
        self.touch_gap_bars = self.v2_config.get('touch_gap_bars_4h', 5)
        
        self.touch_weight_cap = self.v2_config.get('touch_weight_cap', 2.0)
        self.touch_penalty_threshold = self.v2_config.get('touch_penalty_threshold', 4)
        self.touch_penalty_mult = self.v2_config.get('touch_penalty_mult', 0.25)
        self.recency_decay_days = self.v2_config.get('recency_decay_days', 30)
        self.zone_score_weight = self.v2_config.get('zone_score_weight', 4.0)
        
        self.zones_distance_k = self.v2_config.get('zones_distance_k_atr', 3.0)
        self.zones_top_per_side = self.v2_config.get('zones_top_per_side', 3)
        
        self.zones_cache = {}  # Кэш зон по символам
    
    def find_fractal_swings(self, df: pd.DataFrame, k: int = 2) -> Dict[str, List[int]]:
        """
        Найти fractal swing экстремумы
        
        Args:
            df: DataFrame с OHLC
            k: Количество баров вокруг для проверки
            
        Returns:
            Dict с 'highs' и 'lows' индексами
        """
        highs = []
        lows = []
        
        for i in range(k, len(df) - k):
            # High fractal: high[i] > все соседние high
            is_high_fractal = True
            for j in range(i - k, i + k + 1):
                if j == i:
                    continue
                if df['high'].iloc[i] <= df['high'].iloc[j]:
                    is_high_fractal = False
                    break
            
            if is_high_fractal:
                highs.append(i)
            
            # Low fractal: low[i] < все соседние low
            is_low_fractal = True
            for j in range(i - k, i + k + 1):
                if j == i:
                    continue
                if df['low'].iloc[i] >= df['low'].iloc[j]:
                    is_low_fractal = False
                    break
            
            if is_low_fractal:
                lows.append(i)
        
        return {'highs': highs, 'lows': lows}
    
    def identify_consolidation_bases(self, df: pd.DataFrame, 
                                     swings: Dict[str, List[int]],
                                     mtr: float) -> List[Dict]:
        """
        Выделить базы консолидации перед импульсами
        
        Args:
            df: DataFrame 1D
            swings: Fractal swings
            mtr: median True Range для 1D
            
        Returns:
            Список баз с импульсами
        """
        bases = []
        
        # Проверяем каждый swing low для demand зон
        for swing_idx in swings['lows']:
            if swing_idx + self.impulse_bars_check >= len(df):
                continue
            
            # Проверяем импульс ВВЕРХ после swing low
            impulse_bars = df.iloc[swing_idx:swing_idx + self.impulse_bars_check + 1]
            total_move = impulse_bars['high'].max() - impulse_bars['low'].min()
            
            # Импульс должен быть >= impulse_atr_mult × mTR
            if total_move >= self.impulse_atr_mult * mtr:
                bases.append({
                    'type': 'demand',
                    'index': swing_idx,
                    'low': df['low'].iloc[swing_idx],
                    'high': df['high'].iloc[swing_idx],
                    'impulse_strength': total_move / mtr,
                    'timestamp': df.index[swing_idx]
                })
        
        # Проверяем каждый swing high для supply зон
        for swing_idx in swings['highs']:
            if swing_idx + self.impulse_bars_check >= len(df):
                continue
            
            # Проверяем импульс ВНИЗ после swing high
            impulse_bars = df.iloc[swing_idx:swing_idx + self.impulse_bars_check + 1]
            total_move = impulse_bars['high'].max() - impulse_bars['low'].min()
            
            # Импульс должен быть >= impulse_atr_mult × mTR
            if total_move >= self.impulse_atr_mult * mtr:
                bases.append({
                    'type': 'supply',
                    'index': swing_idx,
                    'low': df['low'].iloc[swing_idx],
                    'high': df['high'].iloc[swing_idx],
                    'impulse_strength': total_move / mtr,
                    'timestamp': df.index[swing_idx]
                })
        
        return bases
    
    def expand_zone_boundaries(self, base: Dict, mtr: float, current_price: float) -> Dict:
        """
        Расширить границы зоны с буфером
        
        Args:
            base: Базовая зона
            mtr: median True Range
            current_price: Текущая цена для расчёта %
            
        Returns:
            Зона с расширенными границами
        """
        zone_width = calculate_zone_width(mtr, current_price, 
                                         self.zone_width_mult, 
                                         self.zone_width_min_pct)
        buffer = calculate_buffer(mtr, current_price, 
                                 self.buffer_mult, 
                                 self.zone_width_min_pct / 2)
        
        if base['type'] == 'demand':
            zone_low = base['low'] - buffer
            zone_high = base['high'] + zone_width
        else:  # supply
            zone_low = base['low'] - zone_width
            zone_high = base['high'] + buffer
        
        # Ограничиваем максимальную ширину
        max_width = self.max_width_mult * zone_width
        if (zone_high - zone_low) > max_width:
            center = (zone_low + zone_high) / 2
            zone_low = center - max_width / 2
            zone_high = center + max_width / 2
        
        return {
            **base,
            'low': zone_low,
            'high': zone_high,
            'width': zone_high - zone_low,
            'center': (zone_low + zone_high) / 2
        }
    
    def build_zones_1d(self, df_1d: pd.DataFrame, current_price: float) -> List[Dict]:
        """
        Построить базовые зоны на 1D таймфрейме
        
        Args:
            df_1d: DataFrame с дневными свечами
            current_price: Текущая цена
            
        Returns:
            Список зон S/R
        """
        # Рассчитать mTR для 1D (используем правильный период для v2)
        period = self.mtr_period_1d if self.version == 'v2' else 20
        mtr_1d = calculate_mtr(df_1d, period=period)
        if mtr_1d == 0:
            return []
        
        # Найти fractal swings
        swings = self.find_fractal_swings(df_1d, k=self.fractal_k_1d)
        
        # Выделить базы консолидаций
        bases = self.identify_consolidation_bases(df_1d, swings, mtr_1d)
        
        # Расширить границы зон
        zones = []
        for base in bases:
            zone = self.expand_zone_boundaries(base, mtr_1d, current_price)
            zone['touches'] = 1  # Начальное касание
            zone['score'] = zone['impulse_strength']  # Базовый score
            zones.append(zone)
        
        # Слить пересекающиеся зоны
        merge_distance = self.merge_distance_mult * mtr_1d
        zones = merge_overlapping_zones(zones, merge_distance)
        
        return zones
    
    def refine_zones_4h(self, zones: List[Dict], df_4h: pd.DataFrame, 
                        current_price: float) -> List[Dict]:
        """
        Уточнить зоны на 4H: подсчёт касаний и смарт-подстройка границ
        
        Автоматически выбирает v1 или v2 логику на основе self.version
        
        Args:
            zones: Зоны с 1D
            df_4h: DataFrame с 4H свечами
            current_price: Текущая цена
            
        Returns:
            Уточнённые зоны
        """
        # Выбор версии логики
        if self.version == 'v2':
            return self.refine_zones_4h_v2(zones, df_4h, current_price)
        
        # V1 логика (оригинальная)
        mtr_4h = calculate_mtr(df_4h, period=20)
        if mtr_4h == 0:
            return zones
        
        refined_zones = []
        
        for zone in zones:
            # Подсчёт касаний зоны на 4H
            touches_recent = 0
            touches_old = 0
            cutoff_days = 60
            
            for i, row in df_4h.iterrows():
                # Проверка касания: хвосты или тело входят в зону
                touches_zone = (
                    (row['low'] <= zone['high'] and row['high'] >= zone['low']) or
                    (row['close'] >= zone['low'] and row['close'] <= zone['high'])
                )
                
                if touches_zone:
                    # Определяем recent vs old
                    age_days = (df_4h.index[-1] - i).days if hasattr(i, 'days') else 0
                    if age_days <= cutoff_days:
                        touches_recent += 1
                    else:
                        touches_old += 1
            
            # Смарт-подстройка границ (находим min/max касаний)
            touching_lows = []
            touching_highs = []
            
            for i, row in df_4h.iterrows():
                if row['low'] <= zone['high'] and row['high'] >= zone['low']:
                    touching_lows.append(row['low'])
                    touching_highs.append(row['high'])
            
            if touching_lows and touching_highs:
                # Расширяем чтобы захватить максимум реакций
                adjusted_low = min(touching_lows)
                adjusted_high = max(touching_highs)
                
                # Но не более max_width_mult от базовой ширины
                base_width = calculate_zone_width(mtr_4h, current_price, 
                                                 self.zone_width_mult, 
                                                 self.zone_width_min_pct)
                max_width = self.max_width_mult * base_width
                
                if (adjusted_high - adjusted_low) <= max_width:
                    zone['low'] = adjusted_low
                    zone['high'] = adjusted_high
            
            # Скоринг зоны
            if zone['timestamp'] in df_4h.index:
                loc_result = df_4h.index.get_loc(zone['timestamp'])
                if isinstance(loc_result, (int, np.integer)):
                    loc_idx = int(loc_result)
                elif hasattr(loc_result, '__getitem__'):
                    loc_idx = int(loc_result[0])
                else:
                    loc_idx = 0
                age_bars = len(df_4h) - loc_idx
            else:
                age_bars = 100
            age_penalty = age_bars / 100.0
            
            zone['touches_recent'] = touches_recent
            zone['touches_old'] = touches_old
            zone['score'] = (
                2.0 * touches_recent + 
                1.0 * touches_old + 
                1.0 * zone.get('impulse_strength', 1.0) - 
                age_penalty
            )
            
            refined_zones.append(zone)
        
        # Фильтруем топ-N ближайших к цене
        top_zones = filter_top_zones(refined_zones, current_price, self.top_zones_count)
        
        # Добавляем уникальные ID
        for zone in top_zones:
            zone_str = f"{zone['type']}_{zone['low']:.2f}_{zone['high']:.2f}"
            zone['id'] = hashlib.md5(zone_str.encode()).hexdigest()[:16]
        
        return top_zones
    
    def get_zones(self, symbol: str, df_1d: pd.DataFrame, df_4h: pd.DataFrame,
                  current_price: float, force_recalc: bool = False) -> List[Dict]:
        """
        Получить зоны S/R для символа
        
        Args:
            symbol: Символ
            df_1d: Дневные свечи
            df_4h: 4-часовые свечи
            current_price: Текущая цена
            force_recalc: Принудительный пересчёт
            
        Returns:
            Список зон S/R
        """
        # Проверка кэша
        if not force_recalc and symbol in self.zones_cache:
            cached_zones = self.zones_cache[symbol]
            
            # Проверяем сломанные зоны
            valid_zones = []
            for zone in cached_zones:
                if not is_zone_broken(df_4h, zone['low'], zone['high'], 
                                     zone['type'], self.broken_closes):
                    valid_zones.append(zone)
            
            if valid_zones:
                return valid_zones
        
        # Полный пересчёт
        zones_1d = self.build_zones_1d(df_1d, current_price)
        if not zones_1d:
            return []
        
        refined_zones = self.refine_zones_4h(zones_1d, df_4h, current_price)
        
        # Сохранить в кэш
        self.zones_cache[symbol] = refined_zones
        
        return refined_zones
    
    def update_zones_4h(self, symbol: str, df_4h: pd.DataFrame, 
                        current_price: float) -> List[Dict]:
        """
        Обновление зон на закрытии 4H (лёгкое обновление)
        
        Args:
            symbol: Символ
            df_4h: 4H свечи
            current_price: Текущая цена
            
        Returns:
            Обновлённые зоны
        """
        if symbol not in self.zones_cache:
            return []
        
        zones = self.zones_cache[symbol]
        
        # Обновляем только счётчики касаний и score
        refined = self.refine_zones_4h(zones, df_4h, current_price)
        self.zones_cache[symbol] = refined
        
        return refined
    
    # ============================================================================
    # V2 МЕТОДЫ (Улучшенная логика)
    # ============================================================================
    
    def check_touch_v2(self, candle: pd.Series, zone: Dict) -> bool:
        """
        V2: Проверка касания зоны с улучшенной логикой
        
        Засчитывается если:
        1. Тело закрывается ВНЕ зоны
        2. Тень заходит в зону >= 33% ширины зоны
        
        Args:
            candle: Свеча (Series с open, high, low, close)
            zone: Зона S/R
            
        Returns:
            True если касание валидное
        """
        zone_low = zone['low']
        zone_high = zone['high']
        zone_width = zone_high - zone_low
        
        # Проверка 1: тело закрывается вне зоны
        body_min = min(float(candle['open']), float(candle['close']))
        body_max = max(float(candle['open']), float(candle['close']))
        
        if zone['type'] == 'demand':
            # Для demand: тело должно закрыться выше зоны
            if body_min <= zone_high:
                return False
        else:  # supply
            # Для supply: тело должно закрыться ниже зоны
            if body_max >= zone_low:
                return False
        
        # Проверка 2: тень заходит в зону >= 33% ширины зоны
        shadow_low = float(candle['low'])
        shadow_high = float(candle['high'])
        
        # Рассчитываем пересечение тени с зоной
        intersection_low = max(shadow_low, zone_low)
        intersection_high = min(shadow_high, zone_high)
        
        if intersection_high <= intersection_low:
            return False  # Нет пересечения
        
        shadow_in_zone = intersection_high - intersection_low
        min_shadow_required = self.touch_shadow_ratio * zone_width
        
        return shadow_in_zone >= min_shadow_required
    
    def calculate_zone_score_v2(self, zone: Dict, touches: List[Dict], 
                                current_time: datetime) -> float:
        """
        V2: Расчёт силы зоны с затуханием и пенализацией
        
        Формула:
        touch_weight = min(log2(1 + touches), 2.0)
        penalty = max(0, touches - 4) * 0.25
        recency = exp(-Δt_days / 30)
        zone_score = 4.0 * recency * max(0, tw - penalty)
        
        Args:
            zone: Зона S/R
            touches: Список касаний [{timestamp, ...}, ...]
            current_time: Текущее время
            
        Returns:
            Скор зоны (0-4.0 для итогового скора 0-10)
        """
        if not touches:
            return 0.0
        
        # Сортируем по времени
        touches_sorted = sorted(touches, key=lambda x: x['timestamp'])
        last_touch = touches_sorted[-1]['timestamp']
        
        # Recency: свежесть последнего касания
        if isinstance(last_touch, pd.Timestamp):
            last_touch = last_touch.to_pydatetime()
        if isinstance(current_time, pd.Timestamp):
            current_time = current_time.to_pydatetime()
        
        delta_days = (current_time - last_touch).days
        recency = math.exp(-delta_days / self.recency_decay_days)
        
        # Touch weight: логарифм от количества касаний
        num_touches = len(touches)
        touch_weight = min(math.log2(1 + num_touches), self.touch_weight_cap)
        
        # Penalty: пенализация за >4 касаний
        penalty = max(0, num_touches - self.touch_penalty_threshold) * self.touch_penalty_mult
        
        # Итоговый скор
        zone_score = self.zone_score_weight * recency * max(0, touch_weight - penalty)
        
        return round(zone_score, 2)
    
    def filter_zones_v2(self, zones: List[Dict], current_price: float, 
                       atr_1d: float) -> List[Dict]:
        """
        V2: Отбор зон в окне K×ATR_1D от цены
        
        Оставляет топ-3 demand + топ-3 supply
        
        Args:
            zones: Список зон
            current_price: Текущая цена
            atr_1d: ATR 1D для окна
            
        Returns:
            Отфильтрованные зоны
        """
        window = self.zones_distance_k * atr_1d
        
        # Фильтруем по расстоянию
        zones_in_window = []
        for zone in zones:
            zone_center = (zone['low'] + zone['high']) / 2
            distance = abs(zone_center - current_price)
            
            if distance <= window:
                zone['distance_to_price'] = distance
                zones_in_window.append(zone)
        
        # Разделяем на demand и supply
        demand_zones = [z for z in zones_in_window if z['type'] == 'demand']
        supply_zones = [z for z in zones_in_window if z['type'] == 'supply']
        
        # Сортируем по скору (убывание)
        demand_zones.sort(key=lambda x: x.get('score', 0), reverse=True)
        supply_zones.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        # Берём топ-N с каждой стороны
        top_demand = demand_zones[:self.zones_top_per_side]
        top_supply = supply_zones[:self.zones_top_per_side]
        
        return top_demand + top_supply
    
    def refine_zones_4h_v2(self, zones: List[Dict], df_4h: pd.DataFrame, 
                          current_price: float) -> List[Dict]:
        """
        V2: Уточнение зон на 4H с улучшенной логикой касаний
        
        Args:
            zones: Зоны с 1D
            df_4h: DataFrame с 4H свечами
            current_price: Текущая цена
            
        Returns:
            Уточнённые зоны с v2 скором
        """
        mtr_4h = calculate_mtr(df_4h, period=self.mtr_period_4h)
        if mtr_4h == 0:
            return zones
        
        refined_zones = []
        # Получаем current_time как datetime
        if len(df_4h) > 0:
            last_idx = df_4h.index[-1]
            current_time = last_idx.to_pydatetime() if isinstance(last_idx, pd.Timestamp) else last_idx
        else:
            current_time = datetime.now()
        
        for zone in zones:
            touches = []
            last_touch_idx = -999  # Для анти-дребезга
            
            for i in range(len(df_4h)):
                candle = df_4h.iloc[i]
                
                # Проверка касания v2
                if self.check_touch_v2(candle, zone):
                    # Анти-дребезг: минимум gap_bars между касаниями
                    if i - last_touch_idx >= self.touch_gap_bars:
                        touches.append({
                            'timestamp': df_4h.index[i],
                            'index': i,
                            'low': float(candle['low']),
                            'high': float(candle['high'])
                        })
                        last_touch_idx = i
            
            # Рассчитываем v2 скор
            zone_score = self.calculate_zone_score_v2(zone, touches, current_time)
            
            zone['touches'] = len(touches)
            zone['touches_recent'] = len([t for t in touches 
                                         if (current_time - t['timestamp']).days <= 60])
            zone['score'] = zone_score
            zone['touches_list'] = touches  # Для дебага
            
            refined_zones.append(zone)
        
        # V2 фильтрация: топ-3 per side в окне K×ATR
        atr_1d = calculate_mtr(df_4h, period=self.mtr_period_1d) * 6  # Примерно ATR_1D
        filtered_zones = self.filter_zones_v2(refined_zones, current_price, atr_1d)
        
        # Добавляем уникальные ID
        for zone in filtered_zones:
            zone_str = f"{zone['type']}_{zone['low']:.2f}_{zone['high']:.2f}"
            zone['id'] = hashlib.md5(zone_str.encode()).hexdigest()[:16]
        
        return filtered_zones
