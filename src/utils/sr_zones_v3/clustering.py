"""
DBSCAN Clustering for S/R Zone Consolidation
Groups nearby swing points into zones
"""

import numpy as np
from typing import List, Dict
from sklearn.cluster import DBSCAN


class ZoneClusterer:
    """DBSCAN-based clustering to merge nearby price levels into zones"""
    
    def __init__(self, epsilon_atr_mult: float = 0.6, min_samples: int = 2):
        """
        Args:
            epsilon_atr_mult: ε = epsilon_atr_mult * ATR_TF
            min_samples: Minimum points to form a cluster
        """
        self.epsilon_atr_mult = epsilon_atr_mult
        self.min_samples = min_samples
    
    def cluster_swings(self, swing_prices: List[float], atr: float) -> List[Dict]:
        """
        Кластеризовать swing точки в зоны
        
        Args:
            swing_prices: Список цен swing highs/lows
            atr: ATR для таймфрейма
        
        Returns:
            Список кластеров (зон): [{'prices': [...], 'mid': float, 'count': int}, ...]
        """
        if not swing_prices or len(swing_prices) < self.min_samples:
            return []
        
        # Конвертировать в numpy массив (1D)
        X = np.array(swing_prices).reshape(-1, 1)
        
        # DBSCAN с динамическим ε
        eps = self.epsilon_atr_mult * atr
        dbscan = DBSCAN(
            eps=eps, 
            min_samples=self.min_samples,
            n_jobs=-1,        # Use all CPU cores for parallelization
            algorithm='auto'  # Automatically select optimal algorithm
        )
        labels = dbscan.fit_predict(X)
        
        # Собрать кластеры
        clusters = []
        unique_labels = set(labels)
        
        for label in unique_labels:
            if label == -1:  # Noise
                continue
            
            # Точки в кластере
            cluster_mask = labels == label
            cluster_prices = X[cluster_mask].flatten().tolist()
            
            clusters.append({
                'prices': cluster_prices,
                'mid': float(np.median(cluster_prices)),
                'min': float(np.min(cluster_prices)),
                'max': float(np.max(cluster_prices)),
                'count': len(cluster_prices),
            })
        
        return clusters
    
    def create_zones_from_clusters(self, 
                                   clusters: List[Dict], 
                                   atr: float,
                                   width_min: float,
                                   width_max: float,
                                   min_width_pct: float,
                                   current_price: float) -> List[Dict]:
        """
        Создать зоны с границами из кластеров
        
        Args:
            clusters: Результат cluster_swings
            atr: ATR для расчета ширины
            width_min: Минимальная ширина в ATR
            width_max: Максимальная ширина в ATR
            min_width_pct: Минимальная ширина в % от цены
            current_price: Текущая цена для расчета минимума
        
        Returns:
            Список зон с границами [{'low': float, 'high': float, 'mid': float}, ...]
        """
        zones = []
        
        for cluster in clusters:
            mid = cluster['mid']
            
            # Базовая ширина = clamp(c_low*ATR, min_w, c_high*ATR)
            natural_width = cluster['max'] - cluster['min']
            width_from_atr_min = width_min * atr
            width_from_atr_max = width_max * atr
            min_width_from_price = current_price * min_width_pct
            
            # Clamp
            width = max(
                min_width_from_price,
                min(natural_width, width_from_atr_max)
            )
            width = max(width, width_from_atr_min)
            
            # Границы
            half_width = width / 2
            zone = {
                'low': mid - half_width,
                'high': mid + half_width,
                'mid': mid,
                'width_atr': width / atr if atr > 0 else 0,
                'cluster_count': cluster['count'],
            }
            
            zones.append(zone)
        
        return zones
