"""
Построение зон поддержки/сопротивления (S/R) для Action Price
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import hashlib

from .utils import (
    calculate_mtr, calculate_zone_width, calculate_buffer,
    merge_overlapping_zones, filter_top_zones, is_zone_broken
)


class SRZoneBuilder:
    """Построитель зон поддержки и сопротивления"""
    
    def __init__(self, config: dict):
        """
        Args:
            config: Конфигурация из config.yaml['action_price']['zones']
        """
        self.config = config
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
        # Рассчитать mTR для 1D
        mtr_1d = calculate_mtr(df_1d, period=20)
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
        
        Args:
            zones: Зоны с 1D
            df_4h: DataFrame с 4H свечами
            current_price: Текущая цена
            
        Returns:
            Уточнённые зоны
        """
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
