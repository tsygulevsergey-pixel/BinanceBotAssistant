"""
Zone Selector - Professional multi-stage zone filtering
Replaces simple Top-N with sophisticated selection logic
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional
from scipy.stats import gaussian_kde
from scipy.signal import find_peaks
from .config import V3_DEFAULT_CONFIG


class ZoneSelector:
    """
    Multi-stage zone selector with professional filtering
    
    Stages:
    1. Hard cap per TF (15m≤15, 1H≤15, 4H≤12, 1D≤10)
    2. Class-quota (key/strong first, then normal to fill)
    3. Per-range cap (≤2 zones per 1×ATR bucket)
    4. Min-spacing (0.4-0.7×ATR by TF)
    5. KDE prominence check (final filter if over limit)
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: Custom config (defaults to V3_DEFAULT_CONFIG)
        """
        self.config = config or V3_DEFAULT_CONFIG
        
        # Hard caps per TF
        self.hard_caps = self.config['selector']['hard_caps']
        
        # Per-range cap (zones per ATR bucket)
        self.per_range_cap = self.config['selector']['per_range_cap']
        self.atr_bucket_size = self.config['selector']['atr_bucket_size']
        
        # Min spacing multipliers
        self.min_spacing_mult = self.config['selector']['min_spacing_mult']
        
        # KDE prominence config (updated path)
        kde_config = self.config['selector'].get('kde_prominence', {})
        self.kde_prominence_threshold = kde_config.get('threshold', 0.25)
    
    def select_zones(self,
                    zones: List[Dict],
                    tf: str,
                    atr: float) -> List[Dict]:
        """
        Apply multi-stage selection to zones for one timeframe
        
        Args:
            zones: List of zones for this TF (after lifecycle)
            tf: Timeframe ('15m', '1h', '4h', '1d')
            atr: Current ATR for this timeframe
        
        Returns:
            Selected zones (filtered and sorted)
        """
        if not zones:
            return []
        
        # Stage 1: Class-quota selection (key/strong → normal)
        selected = self._apply_class_quota(zones, tf)
        
        # Stage 2: Per-range cap (≤2 zones per ATR bucket)
        selected = self._apply_per_range_cap(selected, atr)
        
        # Stage 3: Min-spacing enforcement
        selected = self._apply_min_spacing(selected, tf, atr)
        
        # Stage 4: Hard cap (final limit check)
        hard_cap = self.hard_caps.get(tf, 15)
        if len(selected) > hard_cap:
            # If over limit, apply KDE prominence as tiebreaker
            selected = self._apply_kde_prominence_filter(selected, hard_cap)
        
        return selected
    
    def _apply_class_quota(self, zones: List[Dict], tf: str) -> List[Dict]:
        """
        Stage 1: Select zones by class priority
        
        Priority: key > strong > normal > candidate
        Take all key/strong, then fill with normal to hard cap
        
        Args:
            zones: All zones for this TF
            tf: Timeframe
        
        Returns:
            Zones selected by class quota
        """
        hard_cap = self.hard_caps.get(tf, 15)
        
        # Sort by lifecycle_state priority and score
        state_priority = {'key': 0, 'active': 1, 'candidate': 2}
        
        zones_sorted = sorted(
            zones,
            key=lambda z: (
                state_priority.get(z.get('lifecycle_state', 'candidate'), 3),
                -z.get('strength', 0)  # Higher score first
            )
        )
        
        # Take top N by class quota
        selected = []
        
        # First: all key zones
        key_zones = [z for z in zones_sorted if z.get('lifecycle_state') == 'key']
        selected.extend(key_zones[:hard_cap])
        
        if len(selected) >= hard_cap:
            return selected[:hard_cap]
        
        # Second: active zones (formerly "strong")
        active_zones = [z for z in zones_sorted if z.get('lifecycle_state') == 'active']
        remaining = hard_cap - len(selected)
        selected.extend(active_zones[:remaining])
        
        if len(selected) >= hard_cap:
            return selected[:hard_cap]
        
        # Third: candidate zones (fill to limit)
        candidate_zones = [z for z in zones_sorted if z.get('lifecycle_state') == 'candidate']
        remaining = hard_cap - len(selected)
        selected.extend(candidate_zones[:remaining])
        
        return selected[:hard_cap]
    
    def _apply_per_range_cap(self, zones: List[Dict], atr: float) -> List[Dict]:
        """
        Stage 2: Limit zones per price range bucket
        
        Divide price space into buckets of atr_bucket_size × ATR
        Keep max per_range_cap zones per bucket (highest score)
        
        Args:
            zones: Zones from class quota
            atr: Current ATR
        
        Returns:
            Zones after per-range filtering
        """
        if not zones:
            return []
        
        # Guard against zero/negative ATR
        if atr <= 0:
            # Fallback: return all zones (skip per-range cap)
            return zones
        
        bucket_width = self.atr_bucket_size * atr
        
        # Group zones by price bucket
        buckets: Dict[int, List[Dict]] = {}
        
        for zone in zones:
            zone_mid = zone.get('mid', zone.get('low', 0))
            bucket_id = int(zone_mid / bucket_width)
            
            if bucket_id not in buckets:
                buckets[bucket_id] = []
            
            buckets[bucket_id].append(zone)
        
        # Select top zones per bucket
        selected = []
        
        for bucket_zones in buckets.values():
            # Sort by score (highest first)
            bucket_sorted = sorted(
                bucket_zones,
                key=lambda z: z.get('strength', 0),
                reverse=True
            )
            
            # Take top per_range_cap zones
            selected.extend(bucket_sorted[:self.per_range_cap])
        
        # Re-sort by score
        selected = sorted(selected, key=lambda z: z.get('strength', 0), reverse=True)
        
        return selected
    
    def _apply_min_spacing(self,
                          zones: List[Dict],
                          tf: str,
                          atr: float) -> List[Dict]:
        """
        Stage 3: Enforce minimum spacing between zones
        
        Zones must be separated by min_spacing × ATR
        Keep higher-scored zones, drop nearby lower-scored ones
        
        Args:
            zones: Zones from per-range filter
            tf: Timeframe
            atr: Current ATR
        
        Returns:
            Zones after spacing filter
        """
        if not zones:
            return []
        
        # Guard against zero/negative ATR
        if atr <= 0:
            # Fallback: return all zones (skip spacing)
            return zones
        
        min_spacing_mult = self.min_spacing_mult.get(tf, 0.5)
        min_distance = min_spacing_mult * atr
        
        # Sort by score (highest first)
        zones_sorted = sorted(
            zones,
            key=lambda z: z.get('strength', 0),
            reverse=True
        )
        
        selected = []
        
        for zone in zones_sorted:
            zone_mid = zone.get('mid', zone.get('low', 0))
            
            # Check spacing with already selected zones
            too_close = False
            
            for selected_zone in selected:
                selected_mid = selected_zone.get('mid', selected_zone.get('low', 0))
                distance = abs(zone_mid - selected_mid)
                
                if distance < min_distance:
                    too_close = True
                    break
            
            if not too_close:
                selected.append(zone)
        
        return selected
    
    def _apply_kde_prominence_filter(self,
                                    zones: List[Dict],
                                    limit: int) -> List[Dict]:
        """
        Stage 4 (optional): Prominence tiebreaker
        
        If zones exceed hard cap:
        1. Calculate prominence for all zones
        2. Filter out zones below prominence threshold
        3. Sort by prominence (highest first)
        4. Take top limit zones
        
        Args:
            zones: Zones exceeding hard cap
            limit: Hard cap limit
        
        Returns:
            Top zones by prominence
        """
        if len(zones) <= limit:
            return zones
        
        # Calculate prominence for each zone
        zones_with_prominence = []
        
        for zone in zones:
            prominence = self._calculate_zone_prominence(zone)
            zone['_prominence'] = prominence
            
            # CRITICAL: Filter by threshold
            if prominence >= self.kde_prominence_threshold:
                zones_with_prominence.append(zone)
        
        # If filtering by threshold leaves fewer than limit, return all passing
        if len(zones_with_prominence) <= limit:
            # Remove temporary prominence field
            for zone in zones_with_prominence:
                zone.pop('_prominence', None)
            return zones_with_prominence
        
        # Sort by prominence (highest first), then by strength
        zones_sorted = sorted(
            zones_with_prominence,
            key=lambda z: (z.get('_prominence', 0), z.get('strength', 0)),
            reverse=True
        )
        
        # Take top limit zones
        selected = zones_sorted[:limit]
        
        # Remove temporary prominence field
        for zone in selected:
            zone.pop('_prominence', None)
        
        return selected
    
    def _calculate_zone_prominence(self, zone: Dict) -> float:
        """
        Calculate prominence score for a zone (with True KDE)
        
        Uses KDE if sufficient cluster points available, otherwise falls back to heuristic
        
        Args:
            zone: Zone dict (must have 'cluster_prices' for KDE method)
        
        Returns:
            Prominence score (0.0-1.0)
        """
        # Try KDE prominence if enabled and data available
        kde_config = self.config['selector']['kde_prominence']
        
        if kde_config.get('enabled', True):
            cluster_prices = zone.get('cluster_prices', [])
            min_points = kde_config.get('min_points', 6)
            min_unique = kde_config.get('min_unique_prices', 3)
            
            # Check if enough data for KDE
            unique_prices = len(set(cluster_prices)) if cluster_prices else 0
            
            if len(cluster_prices) >= min_points and unique_prices >= min_unique:
                # Use True KDE prominence
                tf = zone.get('tf', '15m')
                atr = zone.get('width_atr', 1.0) * 1.0  # Approximate ATR from zone width
                
                kde_result = self._calculate_kde_prominence_real(
                    zone, cluster_prices, tf, atr
                )
                
                if kde_result and kde_result.get('prominence') is not None:
                    return kde_result['prominence']
        
        # Fallback to heuristic prominence
        return self._calculate_heuristic_prominence(zone)
    
    def _calculate_heuristic_prominence(self, zone: Dict) -> float:
        """
        Heuristic prominence (fallback for zones with insufficient data)
        
        Combines multiple quality metrics:
        - Touches (validated reactions)
        - Reaction strength (ATR-normalized)
        - Zone strength score
        - Lifecycle state
        
        Args:
            zone: Zone dict
        
        Returns:
            Prominence score (0.0-1.0)
        """
        # Component 1: Touches (0-1 scale, capped at 5 touches)
        touches = zone.get('touches', 0)
        touches_score = min(1.0, touches / 5.0)
        
        # Component 2: Reaction strength (0-1 scale, capped at 2 ATR)
        reactions = zone.get('last_reaction_atr', 0)
        reaction_score = min(1.0, reactions / 2.0)
        
        # Component 3: Zone strength (0-1 scale from 0-100)
        strength = zone.get('strength', 0)
        strength_score = strength / 100.0
        
        # Component 4: Lifecycle state bonus
        lifecycle_state = zone.get('lifecycle_state', 'candidate')
        state_bonus = {'key': 0.2, 'active': 0.1, 'candidate': 0.0}.get(lifecycle_state, 0.0)
        
        # Combined prominence (weighted average + state bonus)
        prominence = (
            touches_score * 0.35 +
            reaction_score * 0.30 +
            strength_score * 0.35 +
            state_bonus
        )
        
        # Ensure in 0-1 range
        return min(1.0, max(0.0, prominence))
    
    def _calculate_kde_prominence_real(self,
                                      zone: Dict,
                                      cluster_prices: List[float],
                                      tf: str,
                                      atr: float) -> Optional[Dict]:
        """
        Calculate TRUE KDE prominence using Gaussian kernel density estimation
        
        According to professional specification:
        1. Preprocess points (remove outliers via z-score)
        2. Calculate bandwidth: h = clamp(k_bw * ATR, h_min, h_max)
        3. Create price grid
        4. Calculate KDE with Gaussian kernel
        5. Normalize density to [0,1]
        6. Find peak inside zone
        7. Calculate prominence = peak - base (local minima)
        
        Args:
            zone: Zone dict with boundaries
            cluster_prices: List of prices that formed this zone
            tf: Timeframe ('15m', '1h', '4h', '1d')
            atr: Current ATR for this timeframe
        
        Returns:
            Dict with prominence and metadata, or None if failed
        """
        try:
            kde_config = self.config['selector']['kde_prominence']
            
            # [1] Preprocess: remove outliers via z-score
            prices_arr = np.array(cluster_prices)
            mean_p = np.mean(prices_arr)
            std_p = np.std(prices_arr)
            
            if std_p > 0:
                z_scores = np.abs((prices_arr - mean_p) / std_p)
                prices_clean = prices_arr[z_scores <= 3.0]
            else:
                prices_clean = prices_arr
            
            if len(prices_clean) < 3:
                return None  # Too few points after filtering
            
            # [2] Calculate bandwidth
            # h = clamp(k_bw * ATR, h_min, h_max)
            k_bw = kde_config['bandwidth_atr'].get(tf, 0.20)
            h_min_ticks = kde_config.get('h_min_ticks', 3)
            h_max_atr = kde_config.get('h_max_atr', 3.0)
            
            # Assume tick_size ≈ 0.01 for crypto (BTCUSDT, ETHUSDT etc)
            tick_size = 0.01
            h_min = h_min_ticks * tick_size
            h_max = h_max_atr * atr
            
            h = max(h_min, min(k_bw * atr, h_max))
            
            # [3] Create price grid
            # grid_low = zone.low - 1.0*h, grid_high = zone.high + 1.0*h
            grid_low = zone['low'] - 1.0 * h
            grid_high = zone['high'] + 1.0 * h
            
            grid_step_div = kde_config.get('grid_step_div', 8)
            step = max(tick_size, h / grid_step_div)
            
            # Create grid
            n_points_grid = int((grid_high - grid_low) / step) + 1
            if n_points_grid > 10000:  # Safety: prevent huge grids
                step = (grid_high - grid_low) / 1000
                n_points_grid = 1000
            
            grid = np.linspace(grid_low, grid_high, n_points_grid)
            
            # [4] Calculate KDE with Gaussian kernel
            # Use bandwidth h directly (Scott's rule disabled)
            bw_method = h / np.std(prices_clean) if np.std(prices_clean) > 0 else 0.1
            
            kde = gaussian_kde(prices_clean, bw_method=bw_method)
            density = kde(grid)
            
            # [5] Normalize to [0, 1]
            if density.max() > 0:
                f_norm = density / density.max()
            else:
                return None
            
            # [6] Find peak inside zone [zone.low, zone.high]
            zone_mask = (grid >= zone['low']) & (grid <= zone['high'])
            
            if not np.any(zone_mask):
                return None  # No grid points inside zone
            
            f_in_zone = f_norm[zone_mask]
            grid_in_zone = grid[zone_mask]
            
            if len(f_in_zone) == 0:
                return None
            
            peak_idx_local = np.argmax(f_in_zone)
            peak_price = grid_in_zone[peak_idx_local]
            peak_value = f_in_zone[peak_idx_local]
            
            # [7] Calculate prominence (peak - base)
            # Base = max(left_min, right_min)
            # Find local minima on either side of peak
            
            peak_idx_global = np.where(zone_mask)[0][peak_idx_local]
            
            # Search left for minimum
            base_left = peak_value
            for i in range(peak_idx_global - 1, -1, -1):
                if f_norm[i] < base_left:
                    base_left = f_norm[i]
                elif f_norm[i] > f_norm[i+1]:  # Stop at local minimum
                    break
            
            # Search right for minimum
            base_right = peak_value
            for i in range(peak_idx_global + 1, len(f_norm)):
                if f_norm[i] < base_right:
                    base_right = f_norm[i]
                elif f_norm[i] > f_norm[i-1]:  # Stop at local minimum
                    break
            
            base = max(base_left, base_right)
            prominence = peak_value - base
            
            # Ensure in [0, 1] range
            prominence = max(0.0, min(1.0, prominence))
            
            return {
                'prominence': prominence,
                'peak_price': float(peak_price),
                'peak_value': float(peak_value),
                'base_value': float(base),
                'h': float(h),
                'step': float(step),
                'n_points': len(prices_clean),
                'method': 'kde',
                'fallback_used': False,
            }
            
        except Exception as e:
            # Fallback to heuristic on any error
            return None
