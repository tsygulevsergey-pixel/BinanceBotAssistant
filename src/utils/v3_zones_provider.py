"""
V3 Zones Provider - Shared access to V3 S/R zones
Allows multiple strategies to use V3 zones without duplication
"""

from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime

from src.utils.sr_zones_v3.builder import SRZonesV3Builder
from src.utils.config import config


class V3ZonesProvider:
    """
    Shared provider for V3 S/R zones
    
    Manages zone building and caching for multiple strategies.
    Prevents duplicate zone calculations across strategies.
    """
    
    def __init__(self):
        """Initialize V3 Zones Provider"""
        # Get V3 zone config
        zone_config = config.get('sr_zones_v3', {})
        self.zone_builder = SRZonesV3Builder(zone_config)
        
        # Cache: {symbol: {'zones': zones_dict, 'timestamp': datetime, 'bar_time': timestamp}}
        self.cache = {}
        
        # Cache TTL (rebuild if data changed)
        self.cache_ttl_seconds = 900  # 15 minutes max
    
    def get_zones(self,
                  symbol: str,
                  df_1d: Optional[pd.DataFrame],
                  df_4h: Optional[pd.DataFrame],
                  df_1h: Optional[pd.DataFrame],
                  df_15m: Optional[pd.DataFrame],
                  current_price: float,
                  ema200_15m: Optional[pd.Series] = None,
                  force_rebuild: bool = False) -> Dict[str, List[Dict]]:
        """
        Get V3 zones for symbol (cached or fresh)
        
        Args:
            symbol: Trading symbol
            df_1d, df_4h, df_1h, df_15m: DataFrames for each timeframe
            current_price: Current price
            ema200_15m: EMA200 on 15m (optional)
            force_rebuild: Force rebuild even if cached
        
        Returns:
            Dict of zones by timeframe: {'15m': [...], '1h': [...], '4h': [...], '1d': [...]}
        """
        # Check cache freshness
        if not force_rebuild and symbol in self.cache:
            cached_entry = self.cache[symbol]
            
            # Check if 15m bar changed (most recent data)
            if df_15m is not None and len(df_15m) > 0:
                current_bar_time = df_15m.index[-1]
                cached_bar_time = cached_entry.get('bar_time')
                
                if cached_bar_time == current_bar_time:
                    # Cache is fresh
                    return cached_entry['zones']
        
        # Build fresh zones
        zones = self.zone_builder.build_zones(
            symbol=symbol,
            df_1d=df_1d,
            df_4h=df_4h,
            df_1h=df_1h,
            df_15m=df_15m,
            current_price=current_price,
            ema200_15m=ema200_15m
        )
        
        # Update cache
        bar_time = df_15m.index[-1] if df_15m is not None and len(df_15m) > 0 else None
        
        self.cache[symbol] = {
            'zones': zones,
            'timestamp': datetime.now(),
            'bar_time': bar_time
        }
        
        return zones
    
    def find_nearest_zone(self,
                         zones_by_tf: Dict[str, List[Dict]],
                         price: float,
                         direction: str,
                         timeframe: Optional[str] = None,
                         max_distance_atr: float = 5.0) -> Optional[Dict]:
        """
        Find nearest V3 zone to price
        
        Args:
            zones_by_tf: Dict of zones by timeframe
            price: Current price level
            direction: 'above' (resistance) or 'below' (support)
            timeframe: Specific timeframe to search (None = search all TFs)
            max_distance_atr: Maximum distance in ATR multiples
        
        Returns:
            Nearest zone dict or None
        """
        # Collect zones to search
        search_zones = []
        
        if timeframe and timeframe in zones_by_tf:
            # Search only specific TF
            search_zones = zones_by_tf[timeframe]
        else:
            # Search all TFs (prioritize higher TFs)
            tf_priority = ['1d', '4h', '1h', '15m']
            for tf in tf_priority:
                if tf in zones_by_tf:
                    search_zones.extend(zones_by_tf[tf])
        
        if not search_zones:
            return None
        
        # Filter by direction
        if direction == 'above':
            # Looking for resistance above price (ENTIRE zone must be above)
            candidates = [z for z in search_zones 
                         if z['kind'] == 'R' and z['low'] > price]
            # Sort by distance (closest first)
            candidates.sort(key=lambda z: abs(z['low'] - price))
        
        elif direction == 'below':
            # Looking for support below price (ENTIRE zone must be below)
            candidates = [z for z in search_zones 
                         if z['kind'] == 'S' and z['high'] < price]
            # Sort by distance (closest first)
            candidates.sort(key=lambda z: abs(z['high'] - price))
        
        else:
            # Any direction - find absolute closest
            candidates = search_zones
            candidates.sort(key=lambda z: abs(z['mid'] - price))
        
        # Return closest if within max distance
        if candidates:
            nearest = candidates[0]
            # Optional: check distance limit (if ATR available)
            return nearest
        
        return None
    
    def get_zone_at_level(self,
                         zones_by_tf: Dict[str, List[Dict]],
                         level: float,
                         tolerance_pct: float = 0.5) -> Optional[Dict]:
        """
        Find V3 zone that contains a specific price level
        
        Args:
            zones_by_tf: Dict of zones by timeframe
            level: Price level to check
            tolerance_pct: Tolerance as % of zone width
        
        Returns:
            Zone dict if level is within a zone, else None
        """
        # Search all zones
        all_zones = []
        for tf in ['1d', '4h', '1h', '15m']:
            if tf in zones_by_tf:
                all_zones.extend(zones_by_tf[tf])
        
        # Find zone containing level
        for zone in all_zones:
            zone_width = zone['high'] - zone['low']
            tolerance = zone_width * (tolerance_pct / 100.0)
            
            # Check if level is within zone (with tolerance)
            if (zone['low'] - tolerance) <= level <= (zone['high'] + tolerance):
                return zone
        
        return None
    
    def clear_cache(self, symbol: Optional[str] = None):
        """
        Clear zone cache
        
        Args:
            symbol: Symbol to clear (None = clear all)
        """
        if symbol:
            if symbol in self.cache:
                del self.cache[symbol]
        else:
            self.cache.clear()


# Global singleton instance
_v3_zones_provider = None


def get_v3_zones_provider() -> V3ZonesProvider:
    """
    Get global V3 zones provider instance (singleton)
    
    Returns:
        V3ZonesProvider instance
    """
    global _v3_zones_provider
    
    if _v3_zones_provider is None:
        _v3_zones_provider = V3ZonesProvider()
    
    return _v3_zones_provider
