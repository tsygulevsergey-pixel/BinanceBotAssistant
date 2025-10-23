"""
Signal Engine M15 - Скальп-конвейер для 15-минутных сигналов

Параметры:
- Reaction: 0.6 ATR / 12 bars
- SL: за зоной + 0.25 ATR
- TP1: nearest M15 zone или 1R
- TP2: next H1 zone
- VWAP bias: обязателен (кроме Sweep-A)
- Clearance: ≥1.2 ATR до HTF "стены"
- Risk: 0.5% per trade
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from .signal_engine_base import BaseSignalEngine


class SignalEngine_M15(BaseSignalEngine):
    """
    M15 Signal Engine - скальп-сигналы на 15m
    
    Параметры более жесткие:
    - VWAP bias обязателен
    - Усиленное подтверждение в противоположных H1 зонах
    - Tight SL/TP для быстрых сделок
    """
    
    def __init__(self, registry, config: Dict):
        """
        Args:
            registry: ZoneRegistry instance
            config: M15 engine config
        """
        super().__init__(registry, config, tf_entry='15m')
        
        # M15-specific parameters
        self.min_reaction_atr = config.get('reaction', {}).get('r_atr', 0.6)
        self.reaction_bars = config.get('reaction', {}).get('bars', 12)
        self.sl_buffer_atr = config.get('sl_buffer_atr', 0.25)
        self.min_clearance_mult = config.get('min_clearance_to_htf_atr', 1.2)
        self.vwap_config = config.get('vwap_bias', {})
    
    def tick(self,
             symbol: str,
             df: pd.DataFrame,
             current_price: float,
             atr: float,
             vwap: pd.Series,
             as_of_ts: int) -> List[Dict]:
        """
        Generate M15 signals on bar close
        
        Args:
            symbol: Trading symbol
            df: OHLC DataFrame for 15m
            current_price: Current price
            atr: Current ATR for 15m
            vwap: VWAP series for 15m
            as_of_ts: Timestamp of bar close
        
        Returns:
            List of generated signals
        """
        signals = []
        
        # Get M15 zones from registry (filter by symbol!)
        all_m15_zones = self.registry.get_zones('15m')
        m15_zones = [z for z in all_m15_zones if z['symbol'] == symbol]
        
        if not m15_zones:
            return signals
        
        # Get H1 zones for enhanced confirmation check (filter by symbol!)
        all_h1_zones = self.registry.get_zones('1h')
        h1_zones = [z for z in all_h1_zones if z['symbol'] == symbol]
        
        # Get HTF bands for clearance check
        htf_bands = self.registry.get_nearest_htf_bands(current_price, symbol)
        
        # Get current VWAP value
        vwap_value = vwap.iloc[-1] if len(vwap) > 0 else current_price
        
        # Check each M15 zone for setups
        zones_checked = 0
        zones_locked = 0
        flip_detected = 0
        flip_filtered = 0
        sweep_detected = 0
        sweep_filtered = 0
        
        for zone in m15_zones:
            zones_checked += 1
            
            # Check signal lock
            if self._is_zone_locked(zone['zone_id'], as_of_ts):
                zones_locked += 1
                continue
            
            # Try Flip-Retest setup
            flip_setup = self._detect_flip_retest(
                zone, df, atr,
                self.min_reaction_atr,
                self.reaction_bars
            )
            
            if flip_setup:
                flip_detected += 1
                # Apply M15 filters
                signal = self._process_setup(
                    symbol, flip_setup, zone, df,
                    current_price, atr, vwap_value,
                    h1_zones, htf_bands, as_of_ts
                )
                
                if signal:
                    signals.append(signal)
                    self._lock_zone(zone['zone_id'], as_of_ts)
                    continue
                else:
                    flip_filtered += 1
            
            # Try Sweep-Return setup
            sweep_setup = self._detect_sweep_return(
                zone, df, atr,
                sweep_max_bars=2
            )
            
            if sweep_setup:
                sweep_detected += 1
                signal = self._process_setup(
                    symbol, sweep_setup, zone, df,
                    current_price, atr, vwap_value,
                    h1_zones, htf_bands, as_of_ts
                )
                
                if signal:
                    signals.append(signal)
                    self._lock_zone(zone['zone_id'], as_of_ts)
                else:
                    sweep_filtered += 1
        
        # Debug logging
        if zones_checked > 0 and len(signals) == 0:
            from src.v3_sr.logger import get_v3_sr_logger
            logger = get_v3_sr_logger()
            logger.info(f"🔧 M15 {symbol}: checked={zones_checked}, locked={zones_locked}, "
                       f"flip_det={flip_detected}, flip_filt={flip_filtered}, "
                       f"sweep_det={sweep_detected}, sweep_filt={sweep_filtered}")
        
        return signals
    
    def _process_setup(self,
                      symbol: str,
                      setup: Dict,
                      zone: Dict,
                      df: pd.DataFrame,
                      current_price: float,
                      atr: float,
                      vwap_value: float,
                      h1_zones: List[Dict],
                      htf_bands: Dict,
                      as_of_ts: int) -> Optional[Dict]:
        """
        Process detected setup with M15 filters
        
        Args:
            symbol: Trading symbol
            setup: Setup dict from detection
            zone: Zone dict
            df: OHLC DataFrame
            current_price: Current price
            atr: ATR for 15m
            vwap_value: Current VWAP
            h1_zones: H1 zones for enhanced confirmation
            htf_bands: HTF bands
            as_of_ts: Timestamp
        
        Returns:
            Signal dict if passed filters, None otherwise
        """
        direction = setup['direction']
        reasons = []
        confidence = 70  # Base
        vwap_bias = 'N/A'  # Default value
        
        # [1] VWAP Bias Check (REQUIRED for M15, except Sweep-A)
        is_sweep_a = (setup['setup_type'] == 'SweepReturn' and 
                     setup.get('sweep_details', {}).get('wick_body_ratio', 0) >= 1.5)
        
        if not is_sweep_a or not self.vwap_config.get('countertrend_sweep_A', {}).get('enabled', True):
            vwap_ok, vwap_bias = self._vwap_bias_ok(
                current_price, vwap_value, direction, self.vwap_config
            )
            
            if not vwap_ok:
                return None  # BLOCK: VWAP bias required
            
            reasons.append(f'vwap_{vwap_bias.lower()}')
            confidence += 10
        
        # [2] Check if M15 zone inside opposite H1 zone (enhanced confirmation required)
        in_opposite_h1_zone = self._is_in_opposite_h1_zone(zone, direction, h1_zones)
        
        if in_opposite_h1_zone:
            # Enhanced confirmation required
            enhanced_ok = self._check_enhanced_confirmation(setup, df, atr)
            
            if not enhanced_ok:
                return None  # BLOCK: enhanced confirmation failed
            
            reasons.append('enhanced_confirm')
            confidence += 5
        else:
            # Bonus if aligned with H1 zone
            if self._is_in_aligned_h1_zone(zone, direction, h1_zones):
                reasons.append('h1_aligned')
                confidence += 15
        
        # [3] HTF Clearance Check
        entry_price = zone['high'] if direction == 'LONG' else zone['low']
        
        clearance_ok, htf_context = self._htf_clearance_ok(
            entry_price, direction, htf_bands, atr, self.min_clearance_mult
        )
        
        if not clearance_ok:
            return None  # BLOCK: too close to HTF wall
        
        reasons.append('htf_clear')
        
        # [4] Calculate SL/TP
        levels = self._calc_sl_tp_m15(zone, entry_price, direction, atr)
        
        # [5] Create signal
        context = {
            'vwap_bias': vwap_bias if not is_sweep_a else 'N/A',
            'htf_summary': htf_context.get('htf_summary', []),
            'distance_to_htf_edge_atr': htf_context.get('distance_to_htf_edge_atr'),
            'in_opposite_h1': in_opposite_h1_zone
        }
        
        # CRITICAL FIX: Pass current_price for actual market entry
        signal = self._create_signal(symbol, setup, levels, context, as_of_ts, current_price=current_price)
        signal['confidence'] = min(100, confidence)
        signal['reasons'] = reasons
        
        return signal
    
    def _is_in_opposite_h1_zone(self,
                                m15_zone: Dict,
                                direction: str,
                                h1_zones: List[Dict]) -> bool:
        """
        Check if M15 zone is inside opposite H1 zone
        
        Args:
            m15_zone: M15 zone dict
            direction: Signal direction
            h1_zones: H1 zones list
        
        Returns:
            True if inside opposite zone
        """
        for h1_zone in h1_zones:
            # Check overlap
            overlap = self._zones_overlap(m15_zone, h1_zone)
            
            if overlap > 0.5:  # M15 zone >50% inside H1
                # Check if opposite type
                if direction == 'LONG' and h1_zone['kind'] == 'R':
                    return True  # LONG signal in H1 Resistance
                elif direction == 'SHORT' and h1_zone['kind'] == 'S':
                    return True  # SHORT signal in H1 Support
        
        return False
    
    def _is_in_aligned_h1_zone(self,
                              m15_zone: Dict,
                              direction: str,
                              h1_zones: List[Dict]) -> bool:
        """
        Check if M15 zone is inside aligned H1 zone
        
        Args:
            m15_zone: M15 zone dict
            direction: Signal direction
            h1_zones: H1 zones list
        
        Returns:
            True if inside aligned zone
        """
        for h1_zone in h1_zones:
            overlap = self._zones_overlap(m15_zone, h1_zone)
            
            if overlap > 0.5:
                # Check if same type
                if direction == 'LONG' and h1_zone['kind'] == 'S':
                    return True
                elif direction == 'SHORT' and h1_zone['kind'] == 'R':
                    return True
        
        return False
    
    def _zones_overlap(self, zone1: Dict, zone2: Dict) -> float:
        """
        Calculate overlap ratio between two zones
        
        Args:
            zone1: First zone
            zone2: Second zone
        
        Returns:
            Overlap ratio (0-1) relative to zone1
        """
        # Find intersection
        overlap_low = max(zone1['low'], zone2['low'])
        overlap_high = min(zone1['high'], zone2['high'])
        
        if overlap_high <= overlap_low:
            return 0.0
        
        overlap_size = overlap_high - overlap_low
        zone1_size = zone1['high'] - zone1['low']
        
        if zone1_size <= 0:
            return 0.0
        
        return overlap_size / zone1_size
    
    def _check_enhanced_confirmation(self,
                                    setup: Dict,
                                    df: pd.DataFrame,
                                    atr: float) -> bool:
        """
        Check enhanced confirmation for M15 in opposite H1 zone
        
        Requirements:
        - Flip: "2 close + retest" OR "1 close + retest + ≥0.5 ATR reaction"
        - Sweep: "≤2 bars return" AND "wick/body ≥1.8" AND "VWAP hold"
        
        Args:
            setup: Setup dict
            df: OHLC DataFrame
            atr: ATR
        
        Returns:
            True if enhanced confirmation met
        """
        setup_type = setup['setup_type']
        
        if setup_type == 'FlipRetest':
            # Check confirmation type
            confirmation = setup.get('confirmation', 'base')
            
            if confirmation == 'base':
                # 2 closes - already met
                return True
            elif confirmation == 'alternative':
                # Need to verify reaction strength ≥0.5 ATR (instead of 0.4)
                # This is stricter than base alternative
                # For now, accept if alternative was already triggered
                # TODO: Can add stricter check here
                return True
        
        elif setup_type == 'SweepReturn':
            # Check stricter criteria
            sweep_details = setup.get('sweep_details', {})
            wick_body_ratio = sweep_details.get('wick_body_ratio', 0)
            return_bars = sweep_details.get('return_bars', 999)
            
            # Require wick/body ≥1.8 (stricter than 1.5)
            if wick_body_ratio < 1.8:
                return False
            
            # Require return ≤2 bars
            if return_bars > 2:
                return False
            
            # VWAP hold check would go here
            # For now, accept
            return True
        
        return False
    
    def _calc_sl_tp_m15(self,
                       zone: Dict,
                       entry_price: float,
                       direction: str,
                       atr: float) -> Dict:
        """
        Calculate SL/TP for M15 signals
        
        SL: behind zone + 0.25 ATR
        TP1: nearest M15 zone or 1R
        TP2: next H1 zone
        
        Args:
            zone: Zone dict
            entry_price: Entry price
            direction: Signal direction
            atr: ATR for 15m
        
        Returns:
            {'sl': float, 'tp1': float, 'tp2': float}
        """
        levels = {}
        
        # SL: behind zone + buffer
        if direction == 'LONG':
            levels['sl'] = zone['low'] - (self.sl_buffer_atr * atr)
        else:
            levels['sl'] = zone['high'] + (self.sl_buffer_atr * atr)
        
        # Calculate R (risk)
        risk = abs(entry_price - levels['sl'])
        
        # TP1: 1R default (will snap to nearest M15 zone if closer)
        if direction == 'LONG':
            tp1_default = entry_price + risk
            levels['tp1'] = tp1_default  # TODO: snap to nearest M15 zone
        else:
            tp1_default = entry_price - risk
            levels['tp1'] = tp1_default
        
        # TP2: Next H1 zone - FILTER BY SYMBOL!
        h1_zones = self.registry.get_zones('1h')
        
        # CRITICAL FIX: Filter H1 zones by symbol!
        symbol = zone.get('symbol', 'BTCUSDT')
        h1_zones = [z for z in h1_zones if z['symbol'] == symbol]
        
        if direction == 'LONG':
            # Find nearest H1 Resistance above entry
            candidates = [z for z in h1_zones if z['kind'] == 'R' and z['low'] > entry_price]
            if candidates:
                nearest = min(candidates, key=lambda z: z['low'] - entry_price)
                tp2_candidate = nearest['low']
            else:
                tp2_candidate = entry_price + (2 * risk)  # 2R fallback
            
            # CRITICAL FIX: Ensure TP2 >= TP1
            levels['tp2'] = max(levels['tp1'], tp2_candidate)
        else:
            # Find nearest H1 Support below entry
            candidates = [z for z in h1_zones if z['kind'] == 'S' and z['high'] < entry_price]
            if candidates:
                nearest = max(candidates, key=lambda z: entry_price - z['high'])
                tp2_candidate = nearest['high']
            else:
                tp2_candidate = entry_price - (2 * risk)
            
            # CRITICAL FIX: Ensure TP2 <= TP1 for SHORT
            levels['tp2'] = min(levels['tp1'], tp2_candidate)
        
        return levels
    
    def _is_zone_locked(self, zone_id: str, current_ts: int) -> bool:
        """Check if zone is locked"""
        expiry_ts = self._signal_locks.get(zone_id, 0)
        return current_ts < expiry_ts
    
    def _lock_zone(self, zone_id: str, current_ts: int):
        """Lock zone for signal_valid_bars duration"""
        valid_bars = self.config.get('timeouts', {}).get('signal_valid_bars', 12)
        expiry_ts = current_ts + (valid_bars * 60)  # 15m = 60 sec per bar
        self._signal_locks[zone_id] = expiry_ts
