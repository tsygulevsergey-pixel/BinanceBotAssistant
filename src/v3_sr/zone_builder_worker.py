"""
Zone Builder Worker for ProcessPoolExecutor

Isolated worker function for parallel zone building across multiple symbols.
Each worker process creates its own SRZonesV3Builder instance to avoid shared state.
"""

import pandas as pd
from typing import Dict, List, Optional
import logging

from src.utils.sr_zones_v3.builder import SRZonesV3Builder
from src.utils.config import config


logger = logging.getLogger(__name__)


def build_zones_for_symbol(
    symbol: str,
    df_15m: Optional[pd.DataFrame],
    df_1h: Optional[pd.DataFrame],
    df_4h: Optional[pd.DataFrame],
    df_1d: Optional[pd.DataFrame],
    current_price: float,
    ema200_15m: Optional[pd.Series] = None
) -> Dict:
    """
    Worker function to build V3 zones for a single symbol
    
    This function runs in an isolated process with its own memory space.
    Creates a fresh SRZonesV3Builder instance to avoid shared state issues.
    
    Args:
        symbol: Trading symbol
        df_15m: 15m DataFrame
        df_1h: 1H DataFrame
        df_4h: 4H DataFrame
        df_1d: Daily DataFrame
        current_price: Current price
        ema200_15m: EMA200 on 15m (optional)
    
    Returns:
        Dict with symbol and zones:
        {
            'symbol': symbol,
            'zones': {
                '15m': [...],
                '1h': [...],
                '4h': [...],
                '1d': [...]
            },
            'success': True/False,
            'error': error_message or None
        }
    """
    try:
        # Get V3 zone config from global config
        zone_config = config.get('sr_zones_v3', {})
        
        # Create FRESH builder instance (isolated per worker process)
        zone_builder = SRZonesV3Builder(zone_config)
        
        # Build zones
        zones = zone_builder.build_zones(
            symbol=symbol,
            df_1d=df_1d,
            df_4h=df_4h,
            df_1h=df_1h,
            df_15m=df_15m,
            current_price=current_price,
            ema200_15m=ema200_15m
        )
        
        # Return result
        return {
            'symbol': symbol,
            'zones': zones,
            'success': True,
            'error': None
        }
    
    except Exception as e:
        logger.error(f"❌ Worker error building zones for {symbol}: {e}", exc_info=True)
        return {
            'symbol': symbol,
            'zones': {},
            'success': False,
            'error': str(e)
        }
