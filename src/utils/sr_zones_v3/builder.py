"""
S/R Zones V3 Builder - Main orchestrator
Builds multi-timeframe zones using professional methodology

Pipeline:
1. Find fractal swings (по каждому TF)
2. Cluster swings → zones (DBSCAN)
3. Validate reactions
4. Calculate scores
5. Detect flips (R⇄S)
6. Merge multi-TF zones
7. Filter by strength & proximity
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime

from .config import get_config, V3_DEFAULT_CONFIG
from .clustering import ZoneClusterer
from .validation import ReactionValidator
from .scoring import ZoneScorer
from .flip import FlipDetector


class SRZonesV3Builder:
    """Professional S/R zones builder following institutional methodology"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: Custom config (overrides defaults from V3_DEFAULT_CONFIG)
        """
        self.config = config or V3_DEFAULT_CONFIG
        
        # Initialize components
        self.clusterer = ZoneClusterer(
            epsilon_atr_mult=self.config['clustering']['epsilon_atr_mult'],
            min_samples=self.config['clustering']['min_samples']
        )
        
        self.scorer = ZoneScorer(
            w1_touches=self.config['scoring']['w1_touches'],
            w2_reactions=self.config['scoring']['w2_reactions'],
            w3_freshness=self.config['scoring']['w3_freshness'],
            w4_confluence=self.config['scoring']['w4_confluence'],
            w5_noise=self.config['scoring']['w5_noise']
        )
        
        self.flip_detector = FlipDetector(
            body_break_atr=self.config['flip']['body_break_atr'],
            confirmation_bars=self.config['flip']['confirmation_bars'],
            retest_reaction_atr=self.config['flip']['retest_reaction_atr'],
            weight_multiplier=self.config['flip']['weight_multiplier']
        )
    
    def build_zones(self,
                   symbol: str,
                   df_1d: pd.DataFrame,
                   df_4h: pd.DataFrame,
                   df_1h: pd.DataFrame,
                   df_15m: pd.DataFrame,
                   current_price: float,
                   ema200_15m: Optional[pd.Series] = None) -> Dict[str, List[Dict]]:
        """
        Построить зоны для всех таймфреймов (top-down для HTF confluence)
        
        Args:
            symbol: Символ (для логов)
            df_1d, df_4h, df_1h, df_15m: DataFrames с OHLC для каждого TF
            current_price: Текущая цена
            ema200_15m: EMA200 на 15m для confluence (optional)
        
        Returns:
            Словарь зон по таймфреймам:
            {
                '15m': [{zone_dict}, ...],
                '1h': [{zone_dict}, ...],
                '4h': [{zone_dict}, ...],
                '1d': [{zone_dict}, ...],
            }
        """
        zones_by_tf = {}
        
        # Build zones TOP-DOWN (1d → 4h → 1h → 15m) чтобы передавать HTF zones
        timeframes = [
            ('1d', df_1d, None),
            ('4h', df_4h, None),
            ('1h', df_1h, None),
            ('15m', df_15m, ema200_15m),
        ]
        
        for tf, df, ema200 in timeframes:
            if df is None or len(df) < 50:
                zones_by_tf[tf] = []
                continue
            
            # Собрать HTF zones для confluence (только старшие TF)
            htf_zones = {}
            if tf == '4h' and '1d' in zones_by_tf:
                htf_zones['1d'] = zones_by_tf['1d']
            elif tf == '1h' and ('4h' in zones_by_tf or '1d' in zones_by_tf):
                if '1d' in zones_by_tf:
                    htf_zones['1d'] = zones_by_tf['1d']
                if '4h' in zones_by_tf:
                    htf_zones['4h'] = zones_by_tf['4h']
            elif tf == '15m':
                if '1d' in zones_by_tf:
                    htf_zones['1d'] = zones_by_tf['1d']
                if '4h' in zones_by_tf:
                    htf_zones['4h'] = zones_by_tf['4h']
                if '1h' in zones_by_tf:
                    htf_zones['1h'] = zones_by_tf['1h']
            
            zones = self._build_zones_for_tf(
                tf, df, current_price, ema200=ema200, htf_zones=htf_zones
            )
            
            zones_by_tf[tf] = zones
        
        return zones_by_tf
    
    def _build_zones_for_tf(self,
                           tf: str,
                           df: pd.DataFrame,
                           current_price: float,
                           ema200: Optional[pd.Series] = None,
                           htf_zones: Optional[Dict] = None) -> List[Dict]:
        """
        Построить зоны для одного таймфрейма
        
        Pipeline:
        1. Find swings
        2. Cluster → zones
        3. Validate reactions
        4. Score zones (с HTF confluence и VWAP)
        5. Detect flips
        
        Args:
            tf: Timeframe ('15m', '1h', '4h', '1d')
            df: OHLC DataFrame
            current_price: Текущая цена
            ema200: EMA200 для confluence (optional)
            htf_zones: Dict с зонами старших TF для HTF alignment confluence (optional)
        """
        # ATR для этого TF
        atr_series = self._calculate_atr(df, period=14)
        current_atr = atr_series.iloc[-1] if len(atr_series) > 0 else 0
        
        if current_atr <= 0:
            return []
        
        # 1. Find fractal swings
        k = get_config('fractal_k', tf, default=3)
        swings = self._find_fractal_swings(df, k=k)
        
        if not swings['highs'] and not swings['lows']:
            return []
        
        # 2. Cluster swings
        zones_supply = self._cluster_to_zones(
            swings['highs'], tf, current_atr, current_price, kind='R'
        )
        zones_demand = self._cluster_to_zones(
            swings['lows'], tf, current_atr, current_price, kind='S'
        )
        
        all_zones = zones_supply + zones_demand
        
        # 3. Calculate VWAP для confluence
        vwap = self._calculate_vwap(df)
        
        # 4. Validate reactions & calculate scores
        current_time = df.index[-1].to_pydatetime() if isinstance(df.index[-1], pd.Timestamp) else datetime.now()
        tau_days = get_config('freshness.tau_days', tf, default=10)
        
        # ✅ FIX: Use enumerate to properly update zones in list
        for i, zone in enumerate(all_zones):
            # Generate unique zone ID
            zone_mid = zone['mid']
            zone_kind = zone['kind']
            zone_id = f"{tf}_{zone_kind}_{int(zone_mid * 100000)}"  # e.g., "15m_R_123456"
            zone['id'] = zone_id
            zone['tf'] = tf
            
            # Create validator for this TF
            bars_window = get_config('reaction.bars_window', tf, default=8)
            validator = ReactionValidator(
                atr_mult=self.config['reaction']['atr_mult'],
                bars_window=bars_window
            )
            
            # Find touches
            touches = validator.find_zone_touches(df, zone, atr_series)
            zone['touches'] = len([t for t in touches if t['valid']])
            zone['all_touches'] = len(touches)
            
            if touches:
                zone['last_touch_ts'] = touches[-1]['timestamp']
                zone['last_reaction_atr'] = validator.calculate_avg_reaction(touches)
            else:
                zone['last_touch_ts'] = None
                zone['last_reaction_atr'] = 0.0
            
            # Calculate score (с новыми confluence факторами и HTF multiplier)
            score = self.scorer.calculate_score(
                zone, touches, current_time, tau_days, df, ema200,
                htf_zones=htf_zones,              # ✅ HTF зоны для confluence (+0.5)
                vwap=vwap,                        # ✅ VWAP для confluence (+0.3)
                swing_highs=swings.get('highs'),  # Swing highs для confluence (+0.4)
                swing_lows=swings.get('lows'),    # Swing lows для confluence (+0.4)
                zone_timeframe=tf                 # Для HTF multiplier (×0.95-1.2)
            )
            zone['strength'] = score
            zone['class'] = self.scorer.classify_strength(score)
            
            # Check flip
            flip_result = self.flip_detector.check_flip(
                zone, df, atr_series, lookback_bars=20
            )
            
            # ✅ FIX: Update zone in list if flipped
            if flip_result['flipped']:
                all_zones[i] = self.flip_detector.apply_flip(zone, flip_result)
            else:
                zone['state'] = 'normal'
                zone['flip_side'] = None
        
        return all_zones
    
    def _find_fractal_swings(self, df: pd.DataFrame, k: int = 2) -> Dict[str, List[float]]:
        """
        Найти fractal swing highs/lows
        
        Args:
            df: DataFrame с OHLC
            k: Количество баров вокруг для проверки
        
        Returns:
            {'highs': [...], 'lows': [...]}
        """
        highs = []
        lows = []
        
        for i in range(k, len(df) - k):
            # Swing High
            is_high = True
            for j in range(i - k, i + k + 1):
                if j == i:
                    continue
                if df['high'].iloc[i] <= df['high'].iloc[j]:
                    is_high = False
                    break
            
            if is_high:
                highs.append(df['high'].iloc[i])
            
            # Swing Low
            is_low = True
            for j in range(i - k, i + k + 1):
                if j == i:
                    continue
                if df['low'].iloc[i] >= df['low'].iloc[j]:
                    is_low = False
                    break
            
            if is_low:
                lows.append(df['low'].iloc[i])
        
        return {'highs': highs, 'lows': lows}
    
    def _cluster_to_zones(self,
                         swing_prices: List[float],
                         tf: str,
                         atr: float,
                         current_price: float,
                         kind: str) -> List[Dict]:
        """
        Кластеризовать swing точки в зоны
        
        Returns:
            Список зон с полями 'tf', 'kind', 'low', 'high', 'mid', ...
        """
        if not swing_prices:
            return []
        
        # Cluster
        clusters = self.clusterer.cluster_swings(swing_prices, atr)
        
        # Get width parameters for TF
        width_cfg = get_config('zone_width', tf)
        if not width_cfg:
            width_cfg = {'min': 0.5, 'max': 1.0}
        
        min_width_pct = self.config['zone_width']['min_pct']
        
        # Create zones
        zones = self.clusterer.create_zones_from_clusters(
            clusters, atr,
            width_min=width_cfg['min'],
            width_max=width_cfg['max'],
            min_width_pct=min_width_pct,
            current_price=current_price
        )
        
        # Add TF and kind
        for zone in zones:
            zone['tf'] = tf
            zone['kind'] = kind
        
        return zones
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Рассчитать ATR"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr.fillna(0)
    
    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """
        Рассчитать VWAP (Volume Weighted Average Price)
        
        Args:
            df: DataFrame с OHLC и volume
        
        Returns:
            VWAP series
        """
        # Проверить наличие volume column
        if 'volume' not in df.columns:
            # Если нет volume, вернуть close price как fallback
            return df['close'].copy()
        
        # Типичная цена (HL2 или HLC3)
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        
        # VWAP = cumsum(typical_price × volume) / cumsum(volume)
        pv = typical_price * df['volume']
        cumulative_pv = pv.cumsum()
        cumulative_volume = df['volume'].cumsum()
        
        # Избежать деления на 0
        vwap = cumulative_pv / cumulative_volume.replace(0, 1)
        
        return vwap.fillna(df['close'])
    
    def _merge_multi_tf(self, zones: List[Dict]) -> List[Dict]:
        """
        Объединить пересекающиеся зоны из разных TF
        
        Правило: если младшая зона пересекает старшую >40% → merge
        Старшая доминирует: берем её границы, добавляем confluence bonus
        """
        if not zones:
            return []
        
        # Сортировать по TF (старший первым)
        tf_priority = {'1d': 0, '4h': 1, '1h': 2, '15m': 3}
        zones_sorted = sorted(zones, key=lambda z: tf_priority.get(z['tf'], 999))
        
        merged = []
        skip_indices = set()
        
        overlap_threshold = self.config['merge']['overlap_threshold']
        
        for i, zone_senior in enumerate(zones_sorted):
            if i in skip_indices:
                continue
            
            # Искать младшие зоны для merge
            merged_zone = zone_senior.copy()
            merged_count = 0
            
            for j in range(i + 1, len(zones_sorted)):
                if j in skip_indices:
                    continue
                
                zone_junior = zones_sorted[j]
                
                # Проверить одинаковый тип (R/S)
                if zone_junior['kind'] != zone_senior['kind']:
                    continue
                
                # Проверить пересечение
                overlap = self._calculate_overlap(zone_senior, zone_junior)
                
                if overlap >= overlap_threshold:
                    # Merge: берем границы старшей, boost score
                    merged_count += 1
                    skip_indices.add(j)
                    
                    # Boost strength
                    if 'strength' in merged_zone and 'strength' in zone_junior:
                        # Confluence bonus
                        merged_zone['strength'] = min(100, 
                            merged_zone['strength'] + 5  # +5 за каждую младшую
                        )
                    
                    # Add to confluence
                    if 'confluence' not in merged_zone:
                        merged_zone['confluence'] = []
                    merged_zone['confluence'].append(f"{zone_junior['tf']} overlap")
            
            merged.append(merged_zone)
        
        return merged
    
    def _calculate_overlap(self, zone1: Dict, zone2: Dict) -> float:
        """
        Рассчитать процент пересечения двух зон
        
        Returns:
            0.0-1.0 (доля пересечения относительно меньшей зоны)
        """
        # Границы пересечения
        overlap_low = max(zone1['low'], zone2['low'])
        overlap_high = min(zone1['high'], zone2['high'])
        
        if overlap_low >= overlap_high:
            return 0.0  # Нет пересечения
        
        overlap_size = overlap_high - overlap_low
        
        # Размер меньшей зоны
        size1 = zone1['high'] - zone1['low']
        size2 = zone2['high'] - zone2['low']
        smaller_size = min(size1, size2)
        
        if smaller_size <= 0:
            return 0.0
        
        return overlap_size / smaller_size
    
    def _filter_top_zones(self,
                         zones: List[Dict],
                         current_price: float) -> List[Dict]:
        """
        Фильтровать топ зоны:
        - В окне K×ATR от цены
        - Топ 3-5 per side по score
        """
        if not zones:
            return []
        
        # Разделить на Supply (R) и Demand (S)
        supply_zones = [z for z in zones if z['kind'] == 'R']
        demand_zones = [z for z in zones if z['kind'] == 'S']
        
        # Фильтровать по proximity и score
        top_supply = self._filter_side(supply_zones, current_price, side='above')
        top_demand = self._filter_side(demand_zones, current_price, side='below')
        
        return top_supply + top_demand
    
    def _filter_side(self,
                    zones: List[Dict],
                    current_price: float,
                    side: str) -> List[Dict]:
        """
        Фильтровать зоны одной стороны (supply или demand)
        
        Args:
            side: 'above' (resistance) или 'below' (support)
        """
        if not zones:
            return []
        
        # Фильтр по proximity (например, в пределах 10 ATR)
        # TODO: можно использовать zones_distance_k_atr из config
        
        # Сортировать по score (сильнейшие первыми)
        sorted_zones = sorted(zones, key=lambda z: z.get('strength', 0), reverse=True)
        
        # Взять топ N
        top_n = 5  # Можно сделать configurable
        return sorted_zones[:top_n]
