"""
Zone Quality Filters - Advanced filtering between clustering and validation

Filters applied to clusters AFTER DBSCAN and BEFORE reaction validation:
1. Width Guards - Limit zone width by ATR/percentage/range constraints
2. Outlier Removal - Remove outlier prices using z-score > 3.0
3. KDE Prominence - Require significant density peak (prominence ≥ 0.25)

This ensures only high-quality zones proceed to validation step.
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from scipy.stats import gaussian_kde
from scipy.signal import find_peaks
import pandas as pd


# Width parameters by timeframe
WIDTH_PARAMS = {
    '15m': {
        'k_atr_max': 0.9,
        'k_pct_max': 0.008,  # 0.8%
        'k_range_max': 0.25,
        'k_split_gap_atr': 0.6
    },
    '1h': {
        'k_atr_max': 1.2,
        'k_pct_max': 0.012,  # 1.2%
        'k_range_max': 0.30,
        'k_split_gap_atr': 0.6
    },
    '4h': {
        'k_atr_max': 1.6,
        'k_pct_max': 0.018,  # 1.8%
        'k_range_max': 0.35,
        'k_split_gap_atr': 0.6
    },
    '1d': {
        'k_atr_max': 2.0,
        'k_pct_max': 0.025,  # 2.5%
        'k_range_max': 0.40,
        'k_split_gap_atr': 0.6
    }
}


class ZoneQualityFilter:
    """
    Advanced cluster quality filtering system
    
    Removes noise clusters and ensures zones meet professional standards.
    """
    
    def __init__(self, 
                 tf: str,
                 atr: float,
                 df: pd.DataFrame,
                 z_score_threshold: float = 3.0,
                 kde_prominence_threshold: float = 0.25):
        """
        Args:
            tf: Timeframe ('15m', '1h', '4h', '1d')
            atr: Current ATR for this timeframe
            df: OHLC DataFrame for rolling range calculation
            z_score_threshold: Z-score threshold for outlier removal (default: 3.0)
            kde_prominence_threshold: Minimum KDE peak prominence (default: 0.25)
        """
        self.tf = tf
        self.atr = atr
        self.df = df
        self.z_score_threshold = z_score_threshold
        self.kde_prominence_threshold = kde_prominence_threshold
        
        # Get width parameters for this TF
        self.width_params = WIDTH_PARAMS.get(tf, WIDTH_PARAMS['1h'])
        
        # Calculate rolling range
        self.rolling_range = self._calculate_rolling_range()
    
    def apply_all_filters(self, clusters: List[Dict]) -> List[Dict]:
        """
        Apply all quality filters to clusters
        
        Pipeline:
        1. Remove outliers (z-score > 3.0)
        2. Width guards (shrink/split if too wide)
        3. KDE prominence check (drop if prominence < 0.25)
        
        Args:
            clusters: List of clusters from DBSCAN
        
        Returns:
            Filtered clusters (some may be split, some dropped)
        """
        if not clusters:
            return []
        
        filtered_clusters = []
        
        for cluster in clusters:
            # Step 1: Remove outliers
            cluster_cleaned = self._remove_outliers(cluster)
            if cluster_cleaned is None:
                continue  # Not enough points after outlier removal
            
            # Step 2: Width guards (may split into multiple)
            clusters_after_width = self._apply_width_guards(cluster_cleaned)
            
            # Step 3: KDE prominence check
            for cluster_candidate in clusters_after_width:
                if self._check_kde_prominence(cluster_candidate):
                    filtered_clusters.append(cluster_candidate)
        
        return filtered_clusters
    
    def _remove_outliers(self, cluster: Dict) -> Optional[Dict]:
        """
        Remove outlier prices using z-score > threshold
        
        Args:
            cluster: Cluster with 'prices' list
        
        Returns:
            Updated cluster or None if too few points remain
        """
        prices = np.array(cluster['prices'])
        
        if len(prices) < 3:
            return cluster  # Too few points to calculate z-score
        
        # Calculate z-scores
        mean = np.mean(prices)
        std = np.std(prices)
        
        if std == 0:
            return cluster  # All prices identical, no outliers
        
        z_scores = np.abs((prices - mean) / std)
        
        # Keep only points with z-score <= threshold
        mask = z_scores <= self.z_score_threshold
        filtered_prices = prices[mask].tolist()
        
        if len(filtered_prices) < 2:
            return None  # Too few points after filtering
        
        # Recalculate boundaries
        return {
            'prices': filtered_prices,
            'mid': float(np.median(filtered_prices)),
            'min': float(np.min(filtered_prices)),
            'max': float(np.max(filtered_prices)),
            'count': len(filtered_prices)
        }
    
    def _apply_width_guards(self, cluster: Dict) -> List[Dict]:
        """
        Apply width constraints and split if necessary
        
        Process:
        1. Check if width exceeds max(k_atr × ATR, k_pct × price, k_range × range)
        2. If yes → shrink to Q15-Q85
        3. If still too wide → split by KDE local minimum
        
        Args:
            cluster: Cluster dict
        
        Returns:
            List of clusters (may be split into 2+)
        """
        prices = np.array(cluster['prices'])
        width = cluster['max'] - cluster['min']
        mid = cluster['mid']
        
        # Calculate max allowed width
        max_width = min(
            self.width_params['k_atr_max'] * self.atr,
            self.width_params['k_pct_max'] * mid,
            self.width_params['k_range_max'] * self.rolling_range
        )
        
        # Check if width is acceptable
        if width <= max_width:
            return [cluster]  # OK, no shrinking needed
        
        # Step 1: Shrink to Q15-Q85
        q15 = np.percentile(prices, 15)
        q85 = np.percentile(prices, 85)
        prices_shrunk = prices[(prices >= q15) & (prices <= q85)]
        
        if len(prices_shrunk) < 2:
            return [cluster]  # Keep original if shrinking leaves too few points
        
        width_shrunk = q85 - q15
        
        # Check if shrunk width is acceptable
        if width_shrunk <= max_width:
            return [{
                'prices': prices_shrunk.tolist(),
                'mid': float(np.median(prices_shrunk)),
                'min': float(np.min(prices_shrunk)),
                'max': float(np.max(prices_shrunk)),
                'count': len(prices_shrunk)
            }]
        
        # Step 2: Still too wide → split by KDE local minimum
        split_clusters = self._split_by_kde_minimum(prices_shrunk, max_width)
        
        return split_clusters
    
    def _split_by_kde_minimum(self, prices: np.ndarray, max_width: float) -> List[Dict]:
        """
        Split cluster by finding KDE local minimum between peaks
        
        Criteria:
        - Find 2+ peaks in KDE
        - Gap between peak centers ≥ k_split_gap_atr × ATR
        - Split at local minimum between peaks
        
        Args:
            prices: Array of prices
            max_width: Maximum allowed width
        
        Returns:
            List of split clusters (or original if split not possible)
        """
        if len(prices) < 6:
            # Too few points to split reliably
            return [self._create_cluster_from_prices(prices)]
        
        try:
            # Build KDE
            kde = gaussian_kde(prices, bw_method='scott')
            
            # Sample KDE on grid
            price_min, price_max = prices.min(), prices.max()
            price_range = price_max - price_min
            grid = np.linspace(price_min - 0.1 * price_range, 
                             price_max + 0.1 * price_range, 
                             200)
            density = kde(grid)
            
            # Find peaks
            peaks, properties = find_peaks(density, prominence=0.1 * density.max())
            
            if len(peaks) < 2:
                # Only 1 peak, cannot split
                return [self._create_cluster_from_prices(prices)]
            
            # Check gap between first 2 peaks
            peak1_idx, peak2_idx = peaks[0], peaks[1]
            peak1_price = grid[peak1_idx]
            peak2_price = grid[peak2_idx]
            gap = abs(peak2_price - peak1_price)
            
            min_gap = self.width_params['k_split_gap_atr'] * self.atr
            
            if gap < min_gap:
                # Peaks too close, don't split
                return [self._create_cluster_from_prices(prices)]
            
            # Find local minimum between peaks
            start_idx = min(peak1_idx, peak2_idx)
            end_idx = max(peak1_idx, peak2_idx)
            valley_idx = start_idx + np.argmin(density[start_idx:end_idx])
            split_price = grid[valley_idx]
            
            # Split prices at valley
            prices_below = prices[prices <= split_price]
            prices_above = prices[prices > split_price]
            
            clusters = []
            if len(prices_below) >= 2:
                clusters.append(self._create_cluster_from_prices(prices_below))
            if len(prices_above) >= 2:
                clusters.append(self._create_cluster_from_prices(prices_above))
            
            if len(clusters) == 0:
                # Split failed, keep original
                return [self._create_cluster_from_prices(prices)]
            
            return clusters
            
        except Exception:
            # KDE failed, keep original
            return [self._create_cluster_from_prices(prices)]
    
    def _check_kde_prominence(self, cluster: Dict) -> bool:
        """
        Check if cluster has significant KDE peak (prominence ≥ threshold)
        
        Args:
            cluster: Cluster dict
        
        Returns:
            True if prominence sufficient, False otherwise
        """
        prices = np.array(cluster['prices'])
        
        if len(prices) < 3:
            return True  # Too few points to check, assume OK
        
        try:
            # Build KDE
            kde = gaussian_kde(prices, bw_method='scott')
            
            # Sample KDE
            price_min, price_max = prices.min(), prices.max()
            price_range = price_max - price_min
            
            if price_range == 0:
                return True  # All prices identical, OK
            
            grid = np.linspace(price_min - 0.1 * price_range,
                             price_max + 0.1 * price_range,
                             100)
            density = kde(grid)
            
            # Find peaks with prominence
            peaks, properties = find_peaks(density, prominence=0)
            
            if len(peaks) == 0:
                return False  # No peaks found
            
            # Get max prominence
            prominences = properties['prominences']
            max_prominence = prominences.max()
            max_density = density.max()
            
            # Normalized prominence
            prominence_ratio = max_prominence / max_density if max_density > 0 else 0
            
            return prominence_ratio >= self.kde_prominence_threshold
            
        except Exception:
            # KDE failed, assume OK (don't drop cluster on technical error)
            return True
    
    def _calculate_rolling_range(self, period: int = 20) -> float:
        """
        Calculate rolling high-low range for this timeframe
        
        Args:
            period: Rolling window size
        
        Returns:
            Current rolling range value
        """
        if self.df is None or len(self.df) < period:
            # Fallback to ATR if no data
            return self.atr * 2.0
        
        rolling_high = self.df['high'].rolling(window=period).max()
        rolling_low = self.df['low'].rolling(window=period).min()
        rolling_range = (rolling_high - rolling_low).iloc[-1]
        
        # Fallback if NaN
        if pd.isna(rolling_range) or rolling_range <= 0:
            return self.atr * 2.0
        
        return rolling_range
    
    def _create_cluster_from_prices(self, prices: np.ndarray) -> Dict:
        """
        Create cluster dict from price array
        
        Args:
            prices: Array of prices
        
        Returns:
            Cluster dict
        """
        return {
            'prices': prices.tolist(),
            'mid': float(np.median(prices)),
            'min': float(np.min(prices)),
            'max': float(np.max(prices)),
            'count': len(prices)
        }
