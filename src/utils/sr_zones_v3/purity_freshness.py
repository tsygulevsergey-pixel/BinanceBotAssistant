"""
Purity & Freshness Gate - Post-validation zone filtering

Applied AFTER reaction validation and BEFORE scoring:
1. Purity Check - Ensures zones are respected (low bars inside)
2. Freshness Check - Ensures zones are recently tested

Zones that fail purity can be shrunk, split, or dropped.
Zones that fail freshness are deprioritized or dropped.
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from scipy.stats import gaussian_kde
from scipy.signal import find_peaks


# Freshness thresholds by timeframe (max bars since last touch)
FRESHNESS_THRESHOLDS = {
    '15m': 200,
    '1h': 200,
    '4h': 150,
    '1d': 90
}


class PurityFreshnessGate:
    """
    Advanced post-validation filtering for zone quality
    
    Ensures zones are pure (respected boundaries) and fresh (recently tested).
    """
    
    def __init__(self,
                 tf: str,
                 purity_threshold: float = 0.65,
                 min_class_for_stale: str = 'normal'):
        """
        Args:
            tf: Timeframe ('15m', '1h', '4h', '1d')
            purity_threshold: Minimum purity ratio (default: 0.65 = 35% bars inside max)
            min_class_for_stale: Minimum class to keep stale zones (default: 'normal')
        """
        self.tf = tf
        self.purity_threshold = purity_threshold
        self.min_class_for_stale = min_class_for_stale
        
        # Get freshness threshold for this TF
        self.freshness_threshold = FRESHNESS_THRESHOLDS.get(tf, 200)
    
    def filter_zones(self,
                    zones: List[Dict],
                    df: pd.DataFrame,
                    atr: float) -> List[Dict]:
        """
        Apply purity and freshness filters to zones
        
        Pipeline:
        1. Purity check (shrink/split/drop if too many bars inside)
        2. Freshness check (deprioritize/drop if too old)
        
        Args:
            zones: List of zones with validation data
            df: OHLC DataFrame for purity calculation
            atr: Current ATR for split operations
        
        Returns:
            Filtered zones (some may be modified, dropped, or split)
        """
        if not zones:
            return []
        
        # Step 1: Apply purity filter (may create new zones via split)
        zones_purity_filtered = []
        for zone in zones:
            filtered = self._apply_purity_check(zone, df, atr)
            zones_purity_filtered.extend(filtered)  # May return 0, 1, or 2+ zones
        
        # Step 2: Apply freshness filter
        zones_fresh = self._apply_freshness_check(zones_purity_filtered, df)
        
        return zones_fresh
    
    def _apply_purity_check(self,
                           zone: Dict,
                           df: pd.DataFrame,
                           atr: float) -> List[Dict]:
        """
        Check zone purity and attempt to fix if below threshold
        
        Process:
        1. Calculate purity = 1 - (bars_inside / total_bars)
        2. If purity < 0.65:
           a. Shrink to Q15-Q85 and recalculate
           b. If still low, try to split by KDE
           c. If still low, drop zone
        
        Args:
            zone: Zone dict with low/high boundaries
            df: OHLC DataFrame
            atr: Current ATR
        
        Returns:
            List of zones (0 if dropped, 1 if kept/shrunk, 2+ if split)
        """
        # Calculate initial purity
        purity, bars_inside, total_bars = self._calculate_purity(zone, df)
        
        if purity >= self.purity_threshold:
            # Zone is pure enough
            zone['purity'] = purity
            zone['bars_inside'] = bars_inside
            return [zone]
        
        # Purity too low, attempt to fix
        
        # Attempt 1: Shrink to Q15-Q85
        zone_shrunk = self._shrink_zone_by_quantiles(zone, df)
        if zone_shrunk:
            purity_shrunk, bars_inside_shrunk, _ = self._calculate_purity(zone_shrunk, df)
            if purity_shrunk >= self.purity_threshold:
                zone_shrunk['purity'] = purity_shrunk
                zone_shrunk['bars_inside'] = bars_inside_shrunk
                return [zone_shrunk]
        
        # Attempt 2: Split by KDE
        zones_split = self._split_zone_by_kde(zone, df, atr)
        if zones_split:
            # Check purity of split zones
            valid_splits = []
            for split_zone in zones_split:
                purity_split, bars_inside_split, _ = self._calculate_purity(split_zone, df)
                if purity_split >= self.purity_threshold:
                    split_zone['purity'] = purity_split
                    split_zone['bars_inside'] = bars_inside_split
                    valid_splits.append(split_zone)
            
            if valid_splits:
                return valid_splits
        
        # All attempts failed, drop zone
        return []
    
    def _calculate_purity(self, zone: Dict, df: pd.DataFrame) -> Tuple[float, int, int]:
        """
        Calculate zone purity based on bars closing inside zone
        
        Args:
            zone: Zone with low/high boundaries
            df: OHLC DataFrame
        
        Returns:
            (purity, bars_inside, total_bars)
        """
        if len(df) == 0:
            return 1.0, 0, 0
        
        zone_low = zone['low']
        zone_high = zone['high']
        
        # Count bars closing inside zone
        closes_inside = df['close'].apply(
            lambda c: zone_low <= c <= zone_high
        )
        
        bars_inside = closes_inside.sum()
        total_bars = len(df)
        
        # Purity = 1 - (inside_ratio)
        purity = 1.0 - (bars_inside / total_bars) if total_bars > 0 else 1.0
        
        return purity, bars_inside, total_bars
    
    def _shrink_zone_by_quantiles(self,
                                  zone: Dict,
                                  df: pd.DataFrame) -> Optional[Dict]:
        """
        Shrink zone to Q15-Q85 of prices that touched it
        
        Args:
            zone: Original zone
            df: OHLC DataFrame
        
        Returns:
            Shrunk zone or None if failed
        """
        zone_low = zone['low']
        zone_high = zone['high']
        
        # Find prices that touched this zone (high/low within or crossing boundaries)
        touching_prices = []
        
        for idx in range(len(df)):
            bar_high = df['high'].iloc[idx]
            bar_low = df['low'].iloc[idx]
            
            # Check if bar touched zone
            if bar_low <= zone_high and bar_high >= zone_low:
                # Collect prices within zone
                if zone_low <= bar_high <= zone_high:
                    touching_prices.append(bar_high)
                if zone_low <= bar_low <= zone_high:
                    touching_prices.append(bar_low)
        
        if len(touching_prices) < 3:
            return None  # Not enough data to shrink
        
        # Calculate Q15-Q85
        q15 = np.percentile(touching_prices, 15)
        q85 = np.percentile(touching_prices, 85)
        
        # Create shrunk zone
        shrunk_zone = zone.copy()
        shrunk_zone['low'] = q15
        shrunk_zone['high'] = q85
        shrunk_zone['mid'] = (q15 + q85) / 2
        
        return shrunk_zone
    
    def _split_zone_by_kde(self,
                          zone: Dict,
                          df: pd.DataFrame,
                          atr: float) -> List[Dict]:
        """
        Split zone by finding KDE local minimum between peaks
        
        Similar to width guard split logic but operates on touch prices.
        
        Args:
            zone: Zone to split
            df: OHLC DataFrame
            atr: Current ATR
        
        Returns:
            List of split zones (or empty if split failed)
        """
        zone_low = zone['low']
        zone_high = zone['high']
        
        # Collect touching prices
        touching_prices = []
        
        for idx in range(len(df)):
            bar_high = df['high'].iloc[idx]
            bar_low = df['low'].iloc[idx]
            
            if bar_low <= zone_high and bar_high >= zone_low:
                if zone_low <= bar_high <= zone_high:
                    touching_prices.append(bar_high)
                if zone_low <= bar_low <= zone_high:
                    touching_prices.append(bar_low)
        
        if len(touching_prices) < 6:
            return []  # Too few points to split
        
        try:
            prices_array = np.array(touching_prices)
            
            # Build KDE
            kde = gaussian_kde(prices_array, bw_method='scott')
            
            # Sample KDE
            price_min, price_max = prices_array.min(), prices_array.max()
            price_range = price_max - price_min
            grid = np.linspace(price_min - 0.1 * price_range,
                             price_max + 0.1 * price_range,
                             200)
            density = kde(grid)
            
            # Find peaks
            peaks, properties = find_peaks(density, prominence=0.1 * density.max())
            
            if len(peaks) < 2:
                return []  # Only 1 peak, cannot split
            
            # Find valley between first 2 peaks
            peak1_idx, peak2_idx = peaks[0], peaks[1]
            start_idx = min(peak1_idx, peak2_idx)
            end_idx = max(peak1_idx, peak2_idx)
            valley_idx = start_idx + np.argmin(density[start_idx:end_idx])
            split_price = grid[valley_idx]
            
            # Check gap between peaks
            peak1_price = grid[peak1_idx]
            peak2_price = grid[peak2_idx]
            gap = abs(peak2_price - peak1_price)
            
            if gap < 0.6 * atr:
                return []  # Peaks too close
            
            # Split zones
            prices_below = prices_array[prices_array <= split_price]
            prices_above = prices_array[prices_array > split_price]
            
            zones = []
            
            if len(prices_below) >= 2:
                zone_below = zone.copy()
                zone_below['low'] = float(prices_below.min())
                zone_below['high'] = float(prices_below.max())
                zone_below['mid'] = float(np.median(prices_below))
                zones.append(zone_below)
            
            if len(prices_above) >= 2:
                zone_above = zone.copy()
                zone_above['low'] = float(prices_above.min())
                zone_above['high'] = float(prices_above.max())
                zone_above['mid'] = float(np.median(prices_above))
                zones.append(zone_above)
            
            return zones
            
        except Exception:
            return []  # Split failed
    
    def _apply_freshness_check(self,
                              zones: List[Dict],
                              df: pd.DataFrame) -> List[Dict]:
        """
        Check zone freshness and deprioritize or drop stale zones
        
        Process:
        1. Calculate bars since last touch
        2. If > threshold:
           - If class < normal → drop
           - Otherwise → deprioritize (mark for score penalty)
        
        Args:
            zones: List of zones with 'last_touch_ts'
            df: OHLC DataFrame for age calculation
        
        Returns:
            Filtered zones (stale weak zones removed, others marked)
        """
        if not zones or len(df) == 0:
            return zones
        
        current_time = df.index[-1]
        filtered_zones = []
        
        for zone in zones:
            last_touch_ts = zone.get('last_touch_ts')
            
            if last_touch_ts is None:
                # No touches recorded, consider stale
                zone_class = zone.get('class', 'weak')
                if self._class_rank(zone_class) < self._class_rank(self.min_class_for_stale):
                    continue  # Drop weak/untouched zones
                else:
                    zone['stale'] = True
                    filtered_zones.append(zone)
                continue
            
            # Calculate age in bars
            if isinstance(last_touch_ts, pd.Timestamp):
                # Convert current_time to Timestamp if needed
                current_ts = current_time if isinstance(current_time, pd.Timestamp) else pd.Timestamp(current_time)
                bars_since = self._calculate_bars_since(last_touch_ts, current_ts, df)
            else:
                # Fallback: assume stale if no valid timestamp
                zone['stale'] = True
                filtered_zones.append(zone)
                continue
            
            # Check freshness
            if bars_since > self.freshness_threshold:
                # Zone is stale
                zone_class = zone.get('class', 'weak')
                
                if self._class_rank(zone_class) < self._class_rank(self.min_class_for_stale):
                    # Drop stale weak zones
                    continue
                else:
                    # Keep but mark as stale (for score penalty)
                    zone['stale'] = True
                    zone['bars_since_touch'] = bars_since
            else:
                # Zone is fresh
                zone['stale'] = False
                zone['bars_since_touch'] = bars_since
            
            filtered_zones.append(zone)
        
        return filtered_zones
    
    def _calculate_bars_since(self,
                             last_touch_ts: pd.Timestamp,
                             current_time: pd.Timestamp,
                             df: pd.DataFrame) -> int:
        """
        Calculate number of bars since last touch
        
        Args:
            last_touch_ts: Timestamp of last touch
            current_time: Current timestamp
            df: DataFrame with timestamp index
        
        Returns:
            Number of bars since last touch
        """
        try:
            # Find index of last touch
            if last_touch_ts in df.index:
                last_idx = df.index.get_loc(last_touch_ts)
            else:
                # Find nearest timestamp
                last_idx = df.index.get_indexer([last_touch_ts], method='nearest')[0]
            
            # Current index
            current_idx = len(df) - 1
            
            # Ensure last_idx is int
            if isinstance(last_idx, int):
                bars_since = current_idx - last_idx
            else:
                bars_since = current_idx - int(last_idx)
            
            return max(0, bars_since)
            
        except Exception:
            # Fallback: assume very old
            return 999
    
    def _class_rank(self, zone_class: str) -> int:
        """
        Convert zone class to numeric rank
        
        Args:
            zone_class: 'key', 'strong', 'normal', 'weak'
        
        Returns:
            Numeric rank (higher = better)
        """
        ranks = {
            'key': 4,
            'strong': 3,
            'normal': 2,
            'weak': 1
        }
        return ranks.get(zone_class, 0)
