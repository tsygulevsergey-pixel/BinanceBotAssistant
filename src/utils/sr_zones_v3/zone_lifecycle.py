"""
Zone Lifecycle Management - Candidate → Active → Key transitions
Управление жизненным циклом зон с гистерезисом и auto-pruning
"""

import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .config import V3_DEFAULT_CONFIG


class ZoneLifecycleManager:
    """
    Управление жизненным циклом зон V3 S/R
    
    Lifecycle states:
    - candidate: Новая зона, требует подтверждения
    - active: Подтвержденная зона (≥2 touches, purity, freshness OK)
    - key: Ключевая зона (score ≥80, HTF overlap или ≥3 reactions)
    
    Features:
    - Гистерезис для предотвращения мигания
    - Auto-pruning старых зон без касаний
    - Recreate cooldown tracking
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: Custom config (defaults to V3_DEFAULT_CONFIG)
        """
        self.config = config or V3_DEFAULT_CONFIG
        
        # Lifecycle thresholds
        self.active_min_touches = self.config['lifecycle']['active']['min_touches']
        self.active_min_purity = self.config['lifecycle']['active']['min_purity']
        self.active_require_fresh = self.config['lifecycle']['active']['require_fresh']
        
        self.key_min_score = self.config['lifecycle']['key']['min_score']
        self.key_require_htf_or_reactions = self.config['lifecycle']['key']['require_htf_or_reactions']
        self.key_min_reactions = self.config['lifecycle']['key']['min_reactions_alt']
        
        # Hysteresis
        self.demote_score = self.config['lifecycle']['hysteresis']['demote_to_normal_score']
        self.demote_purity = self.config['lifecycle']['hysteresis']['demote_to_normal_purity']
        
        # Pruning
        self.drop_no_touch_days = self.config['pruning']['drop_if_no_touch_days']
        self.recreate_cooldown_bars = self.config['pruning']['recreate_cooldown_bars']
        self.strength_decay_per_day = self.config['pruning']['strength_decay_per_day']
        
        # Tracking dropped zones for recreate cooldown
        self.dropped_zones_history: List[Dict] = []
    
    def apply_lifecycle(self,
                       zones: List[Dict],
                       current_time: Optional[datetime] = None) -> List[Dict]:
        """
        Применить lifecycle управление ко всем зонам
        
        Process (CRITICAL ORDER):
        1. Auto-pruning (drop старые зоны без касаний)
        2. Strength decay для зон без касаний (BEFORE state determination)
        3. Определить lifecycle state на основе FINAL metrics after decay
        4. Применить гистерезис (anti-flapping demote logic)
        
        Args:
            zones: Список зон после merge
            current_time: Current datetime (для расчётов age)
        
        Returns:
            Filtered и updated zones list
        """
        if not zones:
            return []
        
        current_time = current_time or datetime.now()
        updated_zones = []
        
        for zone in zones:
            # 1. Check pruning FIRST (drop старые зоны)
            if self._should_prune(zone, current_time):
                # Add to dropped history for recreate cooldown
                self._track_dropped_zone(zone)
                continue  # Drop zone
            
            # 2. Apply strength decay BEFORE determining state
            # (state must be based on FINAL metrics after decay)
            zone = self._apply_strength_decay(zone, current_time)
            
            # 3. Determine lifecycle state (AFTER decay, with final metrics)
            lifecycle_state = self._determine_lifecycle_state(zone)
            zone['lifecycle_state'] = lifecycle_state
            
            # 4. Apply hysteresis demote logic
            zone = self._apply_hysteresis(zone, lifecycle_state)
            
            updated_zones.append(zone)
        
        return updated_zones
    
    def _determine_lifecycle_state(self, zone: Dict) -> str:
        """
        Определить lifecycle state зоны
        
        Args:
            zone: Zone dict
        
        Returns:
            'candidate', 'active', or 'key'
        """
        # Get zone metadata
        touches = zone.get('touches', 0)
        purity = zone.get('purity', 1.0)
        stale = zone.get('stale', False)
        score = zone.get('strength', 0)
        
        # Check Key requirements (highest state)
        if score >= self.key_min_score:
            # Require HTF overlap OR ≥3 reactions
            if self.key_require_htf_or_reactions:
                has_htf = self._has_htf_overlap(zone)
                has_reactions = touches >= self.key_min_reactions
                
                if has_htf or has_reactions:
                    return 'key'
            else:
                return 'key'
        
        # Check Active requirements
        if touches >= self.active_min_touches:
            if purity >= self.active_min_purity:
                if self.active_require_fresh and not stale:
                    return 'active'
                elif not self.active_require_fresh:
                    return 'active'
        
        # Default: candidate
        return 'candidate'
    
    def _has_htf_overlap(self, zone: Dict) -> bool:
        """
        Check if zone has HTF (higher timeframe) overlap
        
        Args:
            zone: Zone dict
        
        Returns:
            True if zone has HTF confluence
        """
        # Check confluence field for HTF overlap markers
        confluence = zone.get('confluence', [])
        
        if not confluence:
            return False
        
        # Look for TF overlap markers (e.g., "4h overlap", "1d overlap")
        htf_markers = ['1d overlap', '4h overlap', '1h overlap']
        
        for marker in htf_markers:
            if marker in confluence:
                return True
        
        return False
    
    def _should_prune(self, zone: Dict, current_time: datetime) -> bool:
        """
        Check if zone should be pruned (dropped)
        
        Pruning criteria:
        - No touches for longer than drop_if_no_touch_days for this TF
        
        Args:
            zone: Zone dict
            current_time: Current datetime
        
        Returns:
            True if zone should be dropped
        """
        tf = zone.get('tf', '1h')
        last_touch_ts = zone.get('last_touch_ts')
        
        # Get pruning threshold for this TF
        max_days = self.drop_no_touch_days.get(tf, 7)
        
        if last_touch_ts is None:
            # No touches recorded - check zone creation time if available
            # For now, keep zones without touch data (may be fresh)
            return False
        
        # Calculate days since last touch
        if isinstance(last_touch_ts, pd.Timestamp):
            last_touch_ts = last_touch_ts.to_pydatetime()
        
        if isinstance(last_touch_ts, datetime):
            days_since_touch = (current_time - last_touch_ts).total_seconds() / 86400
            
            if days_since_touch > max_days:
                return True  # Prune
        
        return False
    
    def _apply_strength_decay(self, zone: Dict, current_time: datetime) -> Dict:
        """
        Apply exponential strength decay for zones without recent touches
        
        Decay formula: strength *= (1 - decay_rate)^days_since_touch
        
        Args:
            zone: Zone dict
            current_time: Current datetime
        
        Returns:
            Updated zone with decayed strength
        """
        last_touch_ts = zone.get('last_touch_ts')
        
        if last_touch_ts is None:
            # No touch data, skip decay
            return zone
        
        # Convert to datetime
        if isinstance(last_touch_ts, pd.Timestamp):
            last_touch_ts = last_touch_ts.to_pydatetime()
        
        if not isinstance(last_touch_ts, datetime):
            return zone
        
        # Calculate days since last touch
        days_since = (current_time - last_touch_ts).total_seconds() / 86400
        
        if days_since <= 1:
            # Recent touch, no decay
            return zone
        
        # Apply exponential decay
        current_strength = zone.get('strength', 0)
        decay_factor = (1 - self.strength_decay_per_day) ** days_since
        decayed_strength = current_strength * decay_factor
        
        zone['strength'] = max(0, decayed_strength)  # Floor at 0
        zone['strength_decayed'] = True
        
        return zone
    
    def _apply_hysteresis(self, zone: Dict, lifecycle_state: str) -> Dict:
        """
        Apply hysteresis logic to prevent zone state flapping
        
        Hysteresis rules:
        - Demote to normal if score < 50 OR purity < 0.60
        
        Args:
            zone: Zone dict
            lifecycle_state: Current determined state
        
        Returns:
            Updated zone with hysteresis applied
        """
        score = zone.get('strength', 0)
        purity = zone.get('purity', 1.0)
        
        # Demote conditions
        should_demote = (
            score < self.demote_score or
            purity < self.demote_purity
        )
        
        if should_demote and lifecycle_state in ['active', 'key']:
            # Force demote to candidate
            zone['lifecycle_state'] = 'candidate'
            zone['demoted_by_hysteresis'] = True
        
        return zone
    
    def _track_dropped_zone(self, zone: Dict):
        """
        Track dropped zone for recreate cooldown
        
        Args:
            zone: Zone that was dropped
        """
        self.dropped_zones_history.append({
            'tf': zone.get('tf'),
            'kind': zone.get('kind'),
            'mid': zone.get('mid'),
            'dropped_at': datetime.now(),
        })
        
        # Keep history limited (last 100 zones)
        if len(self.dropped_zones_history) > 100:
            self.dropped_zones_history = self.dropped_zones_history[-100:]
    
    def should_block_recreate(self,
                            zone: Dict,
                            current_bar_count: int) -> bool:
        """
        Check if zone recreation should be blocked due to cooldown
        
        Args:
            zone: New zone candidate
            current_bar_count: Current bar number/timestamp
        
        Returns:
            True if zone should be blocked from creation
        """
        tf = zone.get('tf', '1h')
        zone_mid = zone.get('mid')
        zone_kind = zone.get('kind')
        
        cooldown_bars = self.recreate_cooldown_bars.get(tf, 24)
        
        # Check if similar zone was recently dropped
        for dropped in self.dropped_zones_history:
            if dropped['tf'] != tf or dropped['kind'] != zone_kind:
                continue
            
            # Check price proximity (within 1% of mid)
            if abs(dropped['mid'] - zone_mid) / zone_mid > 0.01:
                continue
            
            # Check cooldown period
            # Note: This is simplified - proper implementation would need bar counting
            dropped_at = dropped['dropped_at']
            time_since = (datetime.now() - dropped_at).total_seconds() / 60
            
            # Approximate bar time based on TF
            tf_minutes = {'15m': 15, '1h': 60, '4h': 240, '1d': 1440}
            minutes_per_bar = tf_minutes.get(tf, 60)
            bars_since = int(time_since / minutes_per_bar)
            
            if bars_since < cooldown_bars:
                return True  # Block recreate
        
        return False  # Allow creation
