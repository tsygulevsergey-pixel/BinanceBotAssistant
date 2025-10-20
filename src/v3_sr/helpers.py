"""
V3 S/R Strategy Helper Functions

Utility functions for price rounding, R-calculation, pattern detection, etc.
"""

import hashlib
from typing import Optional, Tuple, Dict, Any
from datetime import datetime
import pandas as pd


def round_price_to_tick(price: float, tick_size: float) -> float:
    """
    Round price to nearest tick size
    
    Args:
        price: Price to round
        tick_size: Minimum tick size
        
    Returns:
        Rounded price
    """
    return round(price / tick_size) * tick_size


def calculate_r_multiple(entry: float, exit: float, sl: float, direction: str) -> float:
    """
    Calculate R-multiple for a trade
    
    Args:
        entry: Entry price
        exit: Exit price
        sl: Stop loss price
        direction: "LONG" or "SHORT"
        
    Returns:
        R-multiple (can be negative)
    """
    risk_r = abs(entry - sl)
    
    # Avoid division by zero
    if risk_r < 0.0001:
        return 0.0
    
    if direction.upper() == "LONG":
        pnl = exit - entry
    else:  # SHORT
        pnl = entry - exit
    
    return pnl / risk_r


def generate_signal_id(symbol: str, entry_tf: str, zone_id: str, setup_type: str, timestamp: datetime) -> str:
    """
    Generate deterministic signal ID
    
    Args:
        symbol: Trading symbol
        entry_tf: Entry timeframe
        zone_id: Zone ID
        setup_type: Setup type
        timestamp: Signal timestamp
        
    Returns:
        Deterministic hash string
    """
    # Create unique string
    unique_str = f"{symbol}_{entry_tf}_{zone_id}_{setup_type}_{timestamp.isoformat()}"
    
    # Hash it
    return hashlib.sha256(unique_str.encode()).hexdigest()[:16]


def generate_zone_event_id(zone_id: str, event_type: str, timestamp: datetime) -> str:
    """
    Generate deterministic zone event ID
    
    Args:
        zone_id: Zone ID
        event_type: Event type
        timestamp: Event timestamp
        
    Returns:
        Deterministic hash string
    """
    unique_str = f"{zone_id}_{event_type}_{timestamp.isoformat()}"
    return hashlib.sha256(unique_str.encode()).hexdigest()[:16]


def detect_engulfing(current: pd.Series, previous: pd.Series, direction: str) -> bool:
    """
    Detect engulfing candle pattern
    
    Args:
        current: Current candle (OHLC)
        previous: Previous candle (OHLC)
        direction: "LONG" or "SHORT"
        
    Returns:
        True if engulfing pattern detected
    """
    if direction.upper() == "LONG":
        # Bullish engulfing: current body covers previous body
        curr_body_low = min(current['open'], current['close'])
        curr_body_high = max(current['open'], current['close'])
        prev_body_low = min(previous['open'], previous['close'])
        prev_body_high = max(previous['open'], previous['close'])
        
        # Current is green and covers previous body
        is_green = current['close'] > current['open']
        covers_body = (curr_body_low <= prev_body_low and curr_body_high >= prev_body_high)
        
        return is_green and covers_body
    
    else:  # SHORT
        # Bearish engulfing
        curr_body_low = min(current['open'], current['close'])
        curr_body_high = max(current['open'], current['close'])
        prev_body_low = min(previous['open'], previous['close'])
        prev_body_high = max(previous['open'], previous['close'])
        
        # Current is red and covers previous body
        is_red = current['close'] < current['open']
        covers_body = (curr_body_low <= prev_body_low and curr_body_high >= prev_body_high)
        
        return is_red and covers_body


def detect_choch(df: pd.DataFrame, direction: str, lookback: int = 5) -> bool:
    """
    Detect Change of Character (ChoCh)
    
    Simple implementation: recent swing breaks previous swing in the direction of trade.
    
    Args:
        df: DataFrame with OHLC data
        direction: "LONG" or "SHORT"
        lookback: Bars to look back
        
    Returns:
        True if ChoCh detected
    """
    if len(df) < lookback + 2:
        return False
    
    recent = df.iloc[-lookback:].copy()
    
    if direction.upper() == "LONG":
        # For LONG: recent swing high breaks previous swing high
        recent_high = recent['high'].max()
        previous_high = df.iloc[-lookback-5:-lookback]['high'].max() if len(df) >= lookback + 5 else 0
        return recent_high > previous_high
    
    else:  # SHORT
        # For SHORT: recent swing low breaks previous swing low
        recent_low = recent['low'].min()
        previous_low = df.iloc[-lookback-5:-lookback]['low'].min() if len(df) >= lookback + 5 else float('inf')
        return recent_low < previous_low


def check_volume_spike(current_volume: float, avg_volume: float, threshold: float = 1.5) -> bool:
    """
    Check if volume is spiking
    
    Args:
        current_volume: Current bar volume
        avg_volume: Average volume
        threshold: Spike threshold multiplier
        
    Returns:
        True if volume spike detected
    """
    if avg_volume < 1:
        return False
    
    return current_volume >= (avg_volume * threshold)


def get_volatility_regime(current_atr: float, atr_percentile_25: float, atr_percentile_75: float) -> str:
    """
    Classify volatility regime
    
    Args:
        current_atr: Current ATR value
        atr_percentile_25: 25th percentile of ATR
        atr_percentile_75: 75th percentile of ATR
        
    Returns:
        "low", "normal", or "high"
    """
    if current_atr < atr_percentile_25:
        return "low"
    elif current_atr > atr_percentile_75:
        return "high"
    else:
        return "normal"


def find_nearest_zone(
    current_price: float,
    zones: list,
    direction: str,
    zone_kind: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Find nearest zone in given direction
    
    Args:
        current_price: Current price
        zones: List of zone dicts
        direction: "above" or "below" current price
        zone_kind: Filter by kind ("S" or "R"), None = any
        
    Returns:
        Nearest zone dict or None
    """
    filtered_zones = []
    
    for zone in zones:
        # Filter by kind if specified
        if zone_kind and zone.get('kind') != zone_kind:
            continue
        
        zone_mid = zone.get('mid', (zone.get('low', 0) + zone.get('high', 0)) / 2)
        
        # Filter by direction
        if direction == "above" and zone_mid > current_price:
            filtered_zones.append((zone, zone_mid - current_price))
        elif direction == "below" and zone_mid < current_price:
            filtered_zones.append((zone, current_price - zone_mid))
    
    # Sort by distance
    if not filtered_zones:
        return None
    
    filtered_zones.sort(key=lambda x: x[1])
    return filtered_zones[0][0]


def format_zone_type(zone_tf: str, zone_class: str, zone_kind: str) -> str:
    """
    Format zone type string for display
    
    Args:
        zone_tf: Zone timeframe
        zone_class: Zone class (key, strong, normal, weak)
        zone_kind: Zone kind (S or R)
        
    Returns:
        Formatted string like "H4 Strong Support"
    """
    # Capitalize TF
    tf_display = zone_tf.upper()
    
    # Capitalize class
    class_display = zone_class.capitalize()
    
    # Full name for kind
    kind_display = "Support" if zone_kind == "S" else "Resistance"
    
    return f"{tf_display} {class_display} {kind_display}"
