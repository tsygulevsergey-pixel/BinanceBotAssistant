"""
Signal Engine H1 - Среднесрочный конвейер для 1-часовых сигналов

Параметры:
- Reaction: 0.7 ATR / 8 bars
- SL: за зоной + 0.3 ATR  
- TP1: nearest H1 zone или 1R
- TP2: next HTF zone (H4/D)
- VWAP bias: опционален (allow if HTF overlap)
- Clearance: ≥1.0 ATR до HTF "стены"
- Risk: 1.0% per trade
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from .signal_engine_base import BaseSignalEngine


class SignalEngine_H1(BaseSignalEngine):
    """
    H1 Signal Engine - среднесрочные сигналы на 1h
    
    Параметры более мягкие чем M15:
    - VWAP bias опционален
    - Нет усиленного подтверждения
    - Wider SL/TP для swing-торговли
    """
    
    def __init__(self, registry, config: Dict):
        """
        Args:
            registry: ZoneRegistry instance
            config: H1 engine config
        """
        super().__init__(registry, config, tf_entry='1h')
        
        # H1-specific parameters
        self.min_reaction_atr = config.get('reaction', {}).get('r_atr', 0.7)
        self.reaction_bars = config.get('reaction', {}).get('bars', 8)
        self.sl_buffer_atr = config.get('sl_buffer_atr', 0.30)
        self.min_clearance_mult = config.get('min_clearance_to_htf_atr', 1.0)
        self.vwap_config = config.get('vwap_bias', {})
    
    def tick(self,
             symbol: str,
             df: pd.DataFrame,
             current_price: float,
             atr: float,
             vwap: pd.Series,
             as_of_ts: int) -> List[Dict]:
        """
        Generate H1 signals on bar close
        
        Args:
            symbol: Trading symbol
            df: OHLC DataFrame for 1h
            current_price: Current price
            atr: Current ATR for 1h
            vwap: VWAP series for 1h
            as_of_ts: Timestamp of bar close
        
        Returns:
            List of generated signals
        """
        signals = []
        
        # Get H1 zones from registry
        h1_zones = self.registry.get_zones('1h')
        
        if not h1_zones:
            return signals
        
        # Get HTF bands for clearance check
        htf_bands = self.registry.get_nearest_htf_bands(current_price, symbol)
        
        # Get current VWAP value
        vwap_value = vwap.iloc[-1] if len(vwap) > 0 else current_price
        
        # Check each H1 zone for setups
        for zone in h1_zones:
            # Check signal lock
            if self._is_zone_locked(zone['zone_id'], as_of_ts):
                continue
            
            # Try Flip-Retest setup
            flip_setup = self._detect_flip_retest(
                zone, df, atr,
                self.min_reaction_atr,
                self.reaction_bars
            )
            
            if flip_setup:
                # Apply H1 filters
                signal = self._process_setup(
                    symbol, flip_setup, zone, df,
                    current_price, atr, vwap_value,
                    htf_bands, as_of_ts
                )
                
                if signal:
                    signals.append(signal)
                    self._lock_zone(zone['zone_id'], as_of_ts)
                    continue
            
            # Try Sweep-Return setup
            sweep_setup = self._detect_sweep_return(
                zone, df, atr,
                sweep_max_bars=2
            )
            
            if sweep_setup:
                signal = self._process_setup(
                    symbol, sweep_setup, zone, df,
                    current_price, atr, vwap_value,
                    htf_bands, as_of_ts
                )
                
                if signal:
                    signals.append(signal)
                    self._lock_zone(zone['zone_id'], as_of_ts)
        
        return signals
    
    def _process_setup(self,
                      symbol: str,
                      setup: Dict,
                      zone: Dict,
                      df: pd.DataFrame,
                      current_price: float,
                      atr: float,
                      vwap_value: float,
                      htf_bands: Dict,
                      as_of_ts: int) -> Optional[Dict]:
        """
        Process detected setup with H1 filters
        
        Args:
            symbol: Trading symbol
            setup: Setup dict from detection
            zone: Zone dict
            df: OHLC DataFrame
            current_price: Current price
            atr: ATR for 1h
            vwap_value: Current VWAP
            htf_bands: HTF bands
            as_of_ts: Timestamp
        
        Returns:
            Signal dict if passed filters, None otherwise
        """
        direction = setup['direction']
        reasons = []
        confidence = 75  # Base (higher than M15)
        
        # [1] VWAP Bias Check (OPTIONAL for H1, except with HTF overlap)
        vwap_required = self.vwap_config.get('required', False)
        allow_if_htf = self.vwap_config.get('allow_if_htf_overlap', True)
        
        # Check if zone has HTF overlap
        has_htf_overlap = len(zone.get('meta', {}).get('htf_overlap', [])) > 0
        
        # VWAP check required if: vwap_required=True AND NOT (allow_if_htf AND has_htf_overlap)
        should_check_vwap = vwap_required and not (allow_if_htf and has_htf_overlap)
        
        vwap_bias = 'NEUTRAL'
        if should_check_vwap:
            vwap_ok, vwap_bias = self._vwap_bias_ok(
                current_price, vwap_value, direction, self.vwap_config
            )
            
            if not vwap_ok:
                return None  # BLOCK: VWAP bias required
            
            reasons.append(f'vwap_{vwap_bias.lower()}')
            confidence += 10
        else:
            # Check anyway for context
            _, vwap_bias = self._vwap_bias_ok(
                current_price, vwap_value, direction, {'required': False}
            )
            
            if has_htf_overlap:
                reasons.append('htf_overlap_exception')
                confidence += 15
        
        # [2] HTF Clearance Check
        entry_price = zone['high'] if direction == 'LONG' else zone['low']
        
        clearance_ok, htf_context = self._htf_clearance_ok(
            entry_price, direction, htf_bands, atr, self.min_clearance_mult
        )
        
        if not clearance_ok:
            # For H1, can lower confidence instead of hard block
            confidence -= 20
            reasons.append('htf_near')
        else:
            reasons.append('htf_clear')
        
        # Still block if confidence too low
        if confidence < 50:
            return None
        
        # [3] Calculate SL/TP
        levels = self._calc_sl_tp_h1(zone, entry_price, direction, atr)
        
        # [4] Create signal
        context = {
            'vwap_bias': vwap_bias,
            'htf_summary': htf_context.get('htf_summary', []),
            'distance_to_htf_edge_atr': htf_context.get('distance_to_htf_edge_atr'),
            'htf_overlap': zone.get('meta', {}).get('htf_overlap', [])
        }
        
        signal = self._create_signal(symbol, setup, levels, context, as_of_ts)
        signal['confidence'] = min(100, confidence)
        signal['reasons'] = reasons
        
        return signal
    
    def _calc_sl_tp_h1(self,
                      zone: Dict,
                      entry_price: float,
                      direction: str,
                      atr: float) -> Dict:
        """
        Calculate SL/TP for H1 signals
        
        SL: behind zone + 0.3 ATR
        TP1: nearest H1 zone or 1R
        TP2: next HTF zone (H4/D)
        
        Args:
            zone: Zone dict
            entry_price: Entry price
            direction: Signal direction
            atr: ATR for 1h
        
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
        
        # TP1: 1R default (will snap to nearest H1 zone if closer)
        if direction == 'LONG':
            tp1_default = entry_price + risk
            levels['tp1'] = tp1_default  # TODO: snap to nearest H1 zone
        else:
            tp1_default = entry_price - risk
            levels['tp1'] = tp1_default
        
        # TP2: Next HTF zone (H4 or 1D)
        htf_zones_4h = self.registry.get_zones('4h')
        htf_zones_1d = self.registry.get_zones('1d')
        all_htf = htf_zones_4h + htf_zones_1d
        
        if direction == 'LONG':
            # Find nearest HTF Resistance above entry
            candidates = [z for z in all_htf if z['kind'] == 'R' and z['low'] > entry_price]
            if candidates:
                nearest = min(candidates, key=lambda z: z['low'] - entry_price)
                levels['tp2'] = nearest['low']
            else:
                levels['tp2'] = entry_price + (2 * risk)  # 2R fallback
        else:
            # Find nearest HTF Support below entry
            candidates = [z for z in all_htf if z['kind'] == 'S' and z['high'] < entry_price]
            if candidates:
                nearest = max(candidates, key=lambda z: entry_price - z['high'])
                levels['tp2'] = nearest['high']
            else:
                levels['tp2'] = entry_price - (2 * risk)
        
        return levels
    
    def _is_zone_locked(self, zone_id: str, current_ts: int) -> bool:
        """Check if zone is locked"""
        expiry_ts = self._signal_locks.get(zone_id, 0)
        return current_ts < expiry_ts
    
    def _lock_zone(self, zone_id: str, current_ts: int):
        """Lock zone for signal_valid_bars duration"""
        valid_bars = self.config.get('timeouts', {}).get('signal_valid_bars', 8)
        expiry_ts = current_ts + (valid_bars * 3600)  # 1h = 3600 sec per bar
        self._signal_locks[zone_id] = expiry_ts
