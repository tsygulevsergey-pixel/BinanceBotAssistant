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
        
        # KDE prominence for final filter
        self.kde_prominence_threshold = self.config['selector']['kde_prominence_threshold']
    
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
        Calculate prominence score for a zone
        
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
