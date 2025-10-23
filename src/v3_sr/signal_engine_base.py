"""
Base Signal Engine - Общая логика для M15 и H1 движков

Содержит методы детекции setups:
- Flip-Retest
- Sweep-Return
- VWAP bias фильтры
- HTF clearance проверки
- SL/TP калькуляция
"""

import hashlib
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from abc import ABC, abstractmethod


class BaseSignalEngine(ABC):
    """
    Базовый класс для Signal Engines
    
    Содержит общую логику детекции setups и фильтров
    Конкретные engine (M15/H1) наследуются и переопределяют параметры
    """
    
    def __init__(self, 
                 registry,
                 config: Dict,
                 tf_entry: str):
        """
        Args:
            registry: ZoneRegistry instance
            config: Signal engine config
            tf_entry: Entry timeframe ('15m' or '1h')
        """
        self.registry = registry
        self.config = config
        self.tf_entry = tf_entry
        
        # Signal locks (per-TF)
        self._active_signals: Dict[str, Dict] = {}  # signal_id -> signal
        self._signal_locks: Dict[str, int] = {}  # zone_id -> expiry_ts
    
    @abstractmethod
    def tick(self, 
             symbol: str,
             df: pd.DataFrame,
             current_price: float,
             atr: float,
             vwap: pd.Series,
             as_of_ts: int) -> List[Dict]:
        """
        Generate signals on bar close
        
        Must be implemented by concrete engines
        
        Args:
            symbol: Trading symbol
            df: OHLC DataFrame for this TF
            current_price: Current price
            atr: Current ATR for this TF
            vwap: VWAP series for this TF
            as_of_ts: Timestamp of bar close
        
        Returns:
            List of generated signals
        """
        pass
    
    def _detect_flip_retest(self,
                           zone: Dict,
                           df: pd.DataFrame,
                           atr: float,
                           min_reaction_atr: float,
                           reaction_bars: int) -> Optional[Dict]:
        """
        Detect Flip-Retest setup
        
        Setup:
        1. Zone flipped (Support → Resistance or vice versa)
        2. Retest confirmed:
           - Base: 2 consecutive closes beyond zone
           - Alternative: 1 close + retest ≤12 bars + ≥reaction_atr reaction
        
        Args:
            zone: Zone dict from registry
            df: OHLC DataFrame
            atr: Current ATR
            min_reaction_atr: Minimum reaction strength
            reaction_bars: Lookback bars for reaction
        
        Returns:
            Setup dict if detected, None otherwise
        """
        if len(df) < reaction_bars + 5:
            return None
        
        zone_kind = zone['kind']
        zone_low = zone['low']
        zone_high = zone['high']
        
        # Check if zone flipped (from metadata)
        if not zone.get('meta', {}).get('flipped', False):
            return None
        
        # ✅ CRITICAL FIX: Determine direction from CURRENT zone type after flip
        # zone['kind'] = CURRENT type (S or R) AFTER flip
        # For FlipRetest: trade in direction of current zone role
        # - Support (S) → expect bounce UP → LONG
        # - Resistance (R) → expect rejection DOWN → SHORT
        if zone_kind == 'S':
            # Current Support zone → LONG signals (bounce up)
            expected_direction = 'LONG'
            flip_side = 'above'  # Retest from above (price returns to S from above)
        else:
            # Current Resistance zone → SHORT signals (rejection down)
            expected_direction = 'SHORT'
            flip_side = 'below'  # Retest from below (price returns to R from below)
        
        # Look for retest in recent bars
        recent_bars = df.tail(reaction_bars)
        
        # Base confirmation: 2 consecutive closes beyond zone
        base_confirmed = False
        if flip_side == 'below':
            # For SHORT: need 2 closes below zone
            for i in range(len(recent_bars) - 1):
                if (recent_bars.iloc[i]['close'] < zone_low and 
                    recent_bars.iloc[i+1]['close'] < zone_low):
                    base_confirmed = True
                    break
        else:
            # For LONG: need 2 closes above zone
            for i in range(len(recent_bars) - 1):
                if (recent_bars.iloc[i]['close'] > zone_high and 
                    recent_bars.iloc[i+1]['close'] > zone_high):
                    base_confirmed = True
                    break
        
        # Alternative confirmation: 1 close + retest + reaction
        alt_confirmed = False
        retest_bar_idx = None
        
        for i in range(len(recent_bars)):
            bar = recent_bars.iloc[i]
            
            # Check for retest (price returns to zone edge within 0.25 ATR)
            if flip_side == 'below':
                # SHORT: retest from below
                distance_to_edge = abs(bar['low'] - zone_low)
                if distance_to_edge <= 0.25 * atr:
                    # Check reaction AFTER this bar
                    if i < len(recent_bars) - 1:
                        reaction_high = bar['high']
                        future_lows = recent_bars.iloc[i+1:]['low']
                        if len(future_lows) > 0:
                            reaction = reaction_high - future_lows.min()
                            if reaction >= min_reaction_atr * atr:
                                alt_confirmed = True
                                retest_bar_idx = i
                                break
            else:
                # LONG: retest from above
                distance_to_edge = abs(bar['high'] - zone_high)
                if distance_to_edge <= 0.25 * atr:
                    # Check reaction AFTER this bar
                    if i < len(recent_bars) - 1:
                        reaction_low = bar['low']
                        future_highs = recent_bars.iloc[i+1:]['high']
                        if len(future_highs) > 0:
                            reaction = future_highs.max() - reaction_low
                            if reaction >= min_reaction_atr * atr:
                                alt_confirmed = True
                                retest_bar_idx = i
                                break
        
        if not (base_confirmed or alt_confirmed):
            return None
        
        # Setup detected
        setup = {
            'setup_type': 'FlipRetest',
            'direction': expected_direction,
            'confirmation': 'base' if base_confirmed else 'alternative',
            'zone_ref': {
                'zone_id': zone['zone_id'],
                'tf_zone': zone['tf'],
                'kind': zone['kind'],
                'low': zone['low'],
                'high': zone['high'],
                'strength': zone['strength']
            }
        }
        
        return setup
    
    def _detect_sweep_return(self,
                            zone: Dict,
                            df: pd.DataFrame,
                            atr: float,
                            sweep_max_bars: int = 2) -> Optional[Dict]:
        """
        Detect Sweep-Return setup
        
        Setup:
        1. Price sweeps through zone (wick beyond zone edge)
        2. Quick return (≤sweep_max_bars)
        3. Strong wick/body ratio (≥1.5 for normal, ≥1.8 for enhanced)
        
        Args:
            zone: Zone dict from registry
            df: OHLC DataFrame
            atr: Current ATR
            sweep_max_bars: Max bars for return (default: 2)
        
        Returns:
            Setup dict if detected, None otherwise
        """
        if len(df) < sweep_max_bars + 2:
            return None
        
        zone_kind = zone['kind']
        zone_low = zone['low']
        zone_high = zone['high']
        
        # Look for sweep in recent bars
        recent_bars = df.tail(sweep_max_bars + 2)
        
        for i in range(len(recent_bars) - sweep_max_bars):
            sweep_bar = recent_bars.iloc[i]
            
            # Check for sweep
            if zone_kind == 'S':
                # Support sweep: LOW sweeps below zone, close returns inside/above
                if sweep_bar['low'] < zone_low and sweep_bar['close'] >= zone_low:
                    # Potential sweep detected
                    sweep_wick = sweep_bar['close'] - sweep_bar['low']
                    sweep_body = abs(sweep_bar['close'] - sweep_bar['open'])
                    
                    if sweep_body > 0:
                        wick_body_ratio = sweep_wick / sweep_body
                    else:
                        wick_body_ratio = 0
                    
                    # Check if meets threshold
                    if wick_body_ratio >= 1.5:
                        # Check for return within max_bars
                        future_bars = recent_bars.iloc[i+1:i+1+sweep_max_bars]
                        # ✅ FIX: Allow return INSIDE zone (close >= zone_low), not just ABOVE
                        if len(future_bars) > 0 and future_bars.iloc[-1]['close'] >= zone_low:
                            # Sweep-Return confirmed
                            return {
                                'setup_type': 'SweepReturn',
                                'direction': 'LONG',
                                'sweep_details': {
                                    'wick_body_ratio': wick_body_ratio,
                                    'return_bars': len(future_bars)
                                },
                                'zone_ref': {
                                    'zone_id': zone['zone_id'],
                                    'tf_zone': zone['tf'],
                                    'kind': zone['kind'],
                                    'low': zone['low'],
                                    'high': zone['high'],
                                    'strength': zone['strength']
                                }
                            }
            
            else:  # Resistance
                # Resistance sweep: HIGH sweeps above zone, close returns inside/below
                if sweep_bar['high'] > zone_high and sweep_bar['close'] <= zone_high:
                    sweep_wick = sweep_bar['high'] - sweep_bar['close']
                    sweep_body = abs(sweep_bar['close'] - sweep_bar['open'])
                    
                    if sweep_body > 0:
                        wick_body_ratio = sweep_wick / sweep_body
                    else:
                        wick_body_ratio = 0
                    
                    if wick_body_ratio >= 1.5:
                        future_bars = recent_bars.iloc[i+1:i+1+sweep_max_bars]
                        # ✅ FIX: Allow return INSIDE zone (close <= zone_high), not just BELOW
                        if len(future_bars) > 0 and future_bars.iloc[-1]['close'] <= zone_high:
                            return {
                                'setup_type': 'SweepReturn',
                                'direction': 'SHORT',
                                'sweep_details': {
                                    'wick_body_ratio': wick_body_ratio,
                                    'return_bars': len(future_bars)
                                },
                                'zone_ref': {
                                    'zone_id': zone['zone_id'],
                                    'tf_zone': zone['tf'],
                                    'kind': zone['kind'],
                                    'low': zone['low'],
                                    'high': zone['high'],
                                    'strength': zone['strength']
                                }
                            }
        
        return None
    
    def _vwap_bias_ok(self,
                     price: float,
                     vwap_value: float,
                     direction: str,
                     vwap_config: Dict) -> Tuple[bool, str]:
        """
        Check VWAP bias alignment
        
        Args:
            price: Current price
            vwap_value: Current VWAP value
            direction: Signal direction ('LONG' or 'SHORT')
            vwap_config: VWAP configuration
        
        Returns:
            (ok: bool, bias: str)
        """
        required = vwap_config.get('required', True)
        
        # Determine VWAP bias
        if price > vwap_value * 1.001:  # 0.1% buffer
            bias = 'BULL'
        elif price < vwap_value * 0.999:
            bias = 'BEAR'
        else:
            bias = 'NEUTRAL'
        
        # Check alignment
        if direction == 'LONG':
            aligned = bias in ['BULL', 'NEUTRAL']
        else:  # SHORT
            aligned = bias in ['BEAR', 'NEUTRAL']
        
        # If required and not aligned, reject
        if required and not aligned:
            return False, bias
        
        return True, bias
    
    def _htf_clearance_ok(self,
                         entry_price: float,
                         direction: str,
                         htf_bands: Dict,
                         atr: float,
                         min_clearance_mult: float) -> Tuple[bool, Dict]:
        """
        Check HTF clearance (distance to HTF "walls")
        
        Args:
            entry_price: Entry price
            direction: Signal direction
            htf_bands: HTF bands from registry.get_nearest_htf_bands()
            atr: ATR for this TF
            min_clearance_mult: Minimum clearance in ATR multiples
        
        Returns:
            (ok: bool, context: dict)
        """
        min_clearance = min_clearance_mult * atr
        
        context = {
            'distance_to_htf_edge_atr': None,
            'htf_summary': []
        }
        
        if direction == 'LONG':
            # Check distance to resistance above
            resistance = htf_bands.get('nearest_resistance')
            if resistance:
                distance = resistance['low'] - entry_price
                distance_atr = distance / atr if atr > 0 else 999
                context['distance_to_htf_edge_atr'] = distance_atr
                context['htf_summary'].append(f"{resistance['tf']}:R@{resistance['low']:.1f}")
                
                if distance < min_clearance:
                    return False, context
        
        else:  # SHORT
            # Check distance to support below
            support = htf_bands.get('nearest_support')
            if support:
                distance = entry_price - support['high']
                distance_atr = distance / atr if atr > 0 else 999
                context['distance_to_htf_edge_atr'] = distance_atr
                context['htf_summary'].append(f"{support['tf']}:S@{support['high']:.1f}")
                
                if distance < min_clearance:
                    return False, context
        
        return True, context
    
    def _calc_sl_tp(self,
                   zone: Dict,
                   entry_price: float,
                   direction: str,
                   atr: float,
                   sl_buffer_mult: float,
                   tp_config: Dict) -> Dict:
        """
        Calculate SL and TP levels
        
        Args:
            zone: Zone dict
            entry_price: Entry price
            direction: Signal direction
            atr: ATR for this TF
            sl_buffer_mult: SL buffer in ATR multiples
            tp_config: TP configuration
        
        Returns:
            {'sl': float, 'tp1': float, 'tp2': float}
        """
        levels = {}
        
        # Calculate SL (behind zone + buffer)
        if direction == 'LONG':
            levels['sl'] = zone['low'] - (sl_buffer_mult * atr)
        else:  # SHORT
            levels['sl'] = zone['high'] + (sl_buffer_mult * atr)
        
        # Calculate TP1 and TP2
        # Will be implemented by concrete engines with zone lookups
        levels['tp1'] = entry_price  # Placeholder
        levels['tp2'] = entry_price  # Placeholder
        
        return levels
    
    def _generate_signal_id(self,
                           symbol: str,
                           zone_id: str,
                           setup_type: str,
                           bar_ts: int) -> str:
        """
        Generate deterministic signal ID
        
        Args:
            symbol: Trading symbol
            zone_id: Zone ID
            setup_type: Setup type
            bar_ts: Bar timestamp
        
        Returns:
            Signal ID hash
        """
        hash_input = f"{symbol}_{self.tf_entry}_{zone_id}_{setup_type}_{bar_ts}"
        signal_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return signal_id
    
    def _create_signal(self,
                      symbol: str,
                      setup: Dict,
                      levels: Dict,
                      context: Dict,
                      as_of_ts: int,
                      current_price: Optional[float] = None) -> Dict:
        """
        Create normalized signal object
        
        Args:
            symbol: Trading symbol
            setup: Setup dict from detection
            levels: {'sl': float, 'tp1': float, 'tp2': float}
            context: Context dict (vwap_bias, htf_summary, etc)
            as_of_ts: Timestamp
            current_price: Current market price (if None, uses zone edge)
        
        Returns:
            Signal dict
        """
        zone_ref = setup['zone_ref']
        
        signal_id = self._generate_signal_id(
            symbol,
            zone_ref['zone_id'],
            setup['setup_type'],
            as_of_ts
        )
        
        # CRITICAL FIX: Use current_price if provided, otherwise use zone edge
        if current_price is not None:
            entry = current_price
        else:
            # Fallback to zone edge
            if setup['direction'] == 'LONG':
                entry = zone_ref['high']
            else:
                entry = zone_ref['low']
        
        signal = {
            'signal_id': signal_id,
            'symbol': symbol,
            'tf_entry': self.tf_entry,
            'setup_type': setup['setup_type'],
            'direction': setup['direction'],
            'zone_ref': zone_ref,
            'context': context,
            'levels': {
                'entry': entry,
                'sl': levels['sl'],
                'tp1': levels['tp1'],
                'tp2': levels['tp2']
            },
            'risk': {
                'per_trade': self.config.get('risk', {}).get('per_trade', 0.005),
                'stacking': 'none'
            },
            'valid_until_ts': as_of_ts + (self.config.get('timeouts', {}).get('signal_valid_bars', 12) * 60),
            'locks': {
                'signal_lock_scope': 'per-tf',
                'position_lock_scope': 'per-tf'
            },
            'relations': {
                'piggyback_on': None
            },
            'confidence': 70,  # Base confidence
            'reasons': [],
            'created_ts': as_of_ts
        }
        
        # CRITICAL VALIDATION: Verify TP/SL placement is correct
        sl = levels['sl']
        tp1 = levels['tp1']
        tp2 = levels['tp2']
        
        if setup['direction'] == 'LONG':
            # LONG must have: SL < Entry < TP1 < TP2
            if not (sl < entry < tp1 < tp2):
                self.logger.error(
                    f"🚨 INVALID LONG SIGNAL REJECTED: {symbol} {setup['setup_type']}\n"
                    f"   Expected: SL < Entry < TP1 < TP2\n"
                    f"   Got: SL={sl:.8f} | Entry={entry:.8f} | TP1={tp1:.8f} | TP2={tp2:.8f}"
                )
                return None
        else:  # SHORT
            # SHORT must have: SL > Entry > TP1 > TP2
            if not (sl > entry > tp1 > tp2):
                self.logger.error(
                    f"🚨 INVALID SHORT SIGNAL REJECTED: {symbol} {setup['setup_type']}\n"
                    f"   Expected: SL > Entry > TP1 > TP2\n"
                    f"   Got: SL={sl:.8f} | Entry={entry:.8f} | TP1={tp1:.8f} | TP2={tp2:.8f}"
                )
                return None
        
        return signal
