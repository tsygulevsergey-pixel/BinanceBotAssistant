"""
V3 S/R Strategy - Flip-Retest & Sweep-Return

Professional zone-based strategy using V3 S/R system with:
- Flip-Retest: Zone break → confirmation → retest → entry
- Sweep-Return: Liquidity grab → fast return → entry
- VWAP Bias filtering
- Multi-timeframe context (15m/1H entry, 4H/D context)
- Adaptive SL/TP based on zone structure
"""

from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
import pandas as pd
import pytz

from src.database.models import V3SRSignal, V3SRZoneEvent, V3SRSignalLock
from src.utils.sr_zones_v3.builder import SRZonesV3Builder
from src.indicators.vwap import VWAPCalculator
from src.v3_sr.logger import v3_sr_logger as logger
from src.v3_sr.helpers import (
    round_price_to_tick, calculate_r_multiple, generate_signal_id,
    generate_zone_event_id, detect_engulfing, detect_choch,
    check_volume_spike, get_volatility_regime, find_nearest_zone,
    format_zone_type
)


class SRZonesV3Strategy:
    """
    V3 S/R Strategy Implementation
    
    Generates Flip-Retest and Sweep-Return signals based on V3 zone interactions.
    Independent signal tracking and blocking from other strategies.
    """
    
    def __init__(self, config: dict, db, data_loader, binance_client):
        """
        Initialize V3 S/R Strategy
        
        Args:
            config: Strategy configuration from config.yaml
            db: Database instance
            data_loader: DataLoader instance
            binance_client: BinanceClient instance
        """
        self.config = config.get('sr_zones_v3_strategy', {})
        self.db = db
        self.data_loader = data_loader
        self.binance_client = binance_client
        
        # V3 Zone Builder
        zone_config = config.get('sr_zones_v3', {})
        self.zone_builder = SRZonesV3Builder(zone_config)
        
        # VWAP Calculator
        self.vwap_calc = VWAPCalculator()
        
        # Strategy enabled flag
        self.enabled = self.config.get('enabled', True)
        
        # Cache for zones (to avoid recalculating every bar)
        self.zone_cache = {}  # {symbol: {tf: zones}}
        self.zone_cache_meta = {}  # {symbol: {'last_bar_time': timestamp, 'build_time': timestamp}}
        
        logger.info(f"V3 S/R Strategy initialized (enabled={self.enabled})")
    
    async def analyze(self, symbol: str, df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                     df_4h: pd.DataFrame, df_1d: pd.DataFrame,
                     market_regime: str, indicators: dict) -> Optional[Dict]:
        """
        Analyze symbol for V3 S/R signals
        
        Args:
            symbol: Trading symbol
            df_15m: 15m DataFrame
            df_1h: 1H DataFrame
            df_4h: 4H DataFrame
            df_1d: Daily DataFrame
            market_regime: Current market regime
            indicators: Pre-calculated indicators
            
        Returns:
            Signal dict or None
        """
        if not self.enabled:
            return None
        
        logger.info(f"🔍 Analyzing {symbol} | Regime: {market_regime}")
        
        # Check if symbol is blocked for V3
        if await self._is_symbol_blocked(symbol):
            logger.info(f"🔒 {symbol} blocked (active signal)")
            return None
        
        # Filter by market regime
        allowed_regimes = self.config.get('filters', {}).get('allowed_regimes', ['TREND', 'RANGE'])
        if market_regime not in allowed_regimes:
            logger.info(f"❌ {symbol} regime {market_regime} not in allowed list {allowed_regimes}")
            return None
        
        # Build/update zones for all timeframes
        zones = await self._get_or_build_zones(symbol, {
            '15m': df_15m,
            '1h': df_1h,
            '4h': df_4h,
            '1d': df_1d
        })
        
        if not zones:
            logger.info(f"⚠️ {symbol} no zones built")
            return None
        
        # Try entry timeframes (15m, 1h)
        entry_tfs = self.config.get('general', {}).get('entry_timeframes', ['15m', '1h'])
        
        for entry_tf in entry_tfs:
            # Get DataFrame for entry TF
            df_entry = df_15m if entry_tf == '15m' else df_1h
            
            if df_entry is None or len(df_entry) < 50:
                continue
            
            # Check Flip-Retest setup
            if self.config.get('flip_retest', {}).get('enabled', True):
                signal = await self._check_flip_retest(
                    symbol, entry_tf, df_entry, zones, market_regime, indicators
                )
                if signal:
                    return signal
            
            # Check Sweep-Return setup
            if self.config.get('sweep_return', {}).get('enabled', True):
                signal = await self._check_sweep_return(
                    symbol, entry_tf, df_entry, zones, market_regime, indicators
                )
                if signal:
                    return signal
        
        return None
    
    async def _get_or_build_zones(self, symbol: str, dfs: Dict[str, pd.DataFrame]) -> Dict:
        """
        Get zones from cache or build new
        
        Args:
            symbol: Trading symbol
            dfs: Dict of DataFrames by timeframe
            
        Returns:
            Dict of zones by timeframe
        """
        # ✅ FIX: Check cache freshness - rebuild if 15m data changed
        should_rebuild = False
        
        if symbol in self.zone_cache:
            # Check if 15m data is newer than cached zones
            df_15m = dfs.get('15m')
            if df_15m is not None and len(df_15m) > 0:
                current_bar_time = df_15m.index[-1]
                cached_entry = self.zone_cache_meta.get(symbol, {})
                last_bar_time = cached_entry.get('last_bar_time')
                
                if last_bar_time is None or current_bar_time != last_bar_time:
                    logger.debug(f"🔄 {symbol} zones stale (bar changed), rebuilding...")
                    should_rebuild = True
                else:
                    logger.debug(f"📦 {symbol} zones loaded from cache (fresh)")
                    return self.zone_cache[symbol]
            else:
                # No 15m data - use cache if exists
                return self.zone_cache.get(symbol, {})
        else:
            should_rebuild = True
        
        # Build zones using V3 Builder
        try:
            logger.info(f"🔨 Building V3 zones for {symbol}...")
            
            # Get current price
            current_price = dfs.get('15m')['close'].iloc[-1] if '15m' in dfs and len(dfs['15m']) > 0 else None
            if current_price is None:
                logger.error(f"❌ {symbol}: No 15m data for current price")
                return {}
            
            # Build zones with correct signature
            zones = self.zone_builder.build_zones(
                symbol=symbol,
                df_1d=dfs.get('1d'),
                df_4h=dfs.get('4h'),
                df_1h=dfs.get('1h'),
                df_15m=dfs.get('15m'),
                current_price=current_price
            )
            
            # Update zone strength from accumulated events (real-time quality tracking)
            zones_updated = 0
            for tf, tf_zones in zones.items():
                for zone in tf_zones:
                    zone_id = zone.get('id')
                    if zone_id:
                        updated_strength = await self.update_zone_strength_from_events(symbol, zone_id)
                        if updated_strength is not None:
                            # Update zone strength in place
                            old_strength = zone.get('strength', 0)
                            zone['strength'] = updated_strength
                            zones_updated += 1
                            logger.debug(f"🔄 {symbol} zone {tf}-{zone.get('kind')} strength: {old_strength:.1f} → {updated_strength:.1f}")
            
            if zones_updated > 0:
                logger.info(f"✨ {symbol}: Updated strength for {zones_updated} zones based on events")
            
            # Count zones by TF
            zone_counts = {tf: len(z) for tf, z in zones.items()}
            logger.info(f"✅ {symbol} zones built: {zone_counts}")
            
            # ✅ FIX: Store cache with metadata
            self.zone_cache[symbol] = zones
            self.zone_cache_meta[symbol] = {
                'last_bar_time': dfs.get('15m').index[-1] if '15m' in dfs and len(dfs['15m']) > 0 else None,
                'build_time': datetime.now(pytz.UTC)
            }
            
            return zones
        except Exception as e:
            logger.error(f"❌ Error building V3 zones for {symbol}: {e}")
            return {}
    
    async def _check_flip_retest(self, symbol: str, entry_tf: str, df: pd.DataFrame,
                                 zones: Dict, market_regime: str, indicators: dict) -> Optional[Dict]:
        """
        Check for Flip-Retest setup
        
        Logic:
        1. Find zone that was broken (body close beyond zone)
        2. Check confirmation (N closes beyond zone)
        3. Check retest (price returns to zone within timeout)
        4. Check entry trigger (engulfing/choch)
        5. Validate VWAP bias
        
        Args:
            symbol: Trading symbol
            entry_tf: Entry timeframe
            df: Entry TF DataFrame
            zones: All zones
            market_regime: Market regime
            indicators: Indicators dict
            
        Returns:
            Signal dict or None
        """
        if len(df) < 20:
            return None
        
        # Get config
        flip_config = self.config.get('flip_retest', {})
        break_atr = flip_config.get('break_body_buffer_atr', 0.3)
        confirm_closes = flip_config.get('confirm_closes', 2)
        retest_timeout = flip_config.get('retest_timeout_bars', 12)
        retest_delta_atr = flip_config.get('retest_accept_delta_atr', 0.25)
        
        # Get ATR
        atr = indicators.get(entry_tf, {}).get('atr', df['close'].iloc[-1] * 0.01)
        
        # Get current price
        current_price = df['close'].iloc[-1]
        
        # Get zones for entry TF and HTF
        entry_zones = zones.get(entry_tf, [])
        h4_zones = zones.get('4h', [])
        d_zones = zones.get('1d', [])
        all_zones = entry_zones + h4_zones + d_zones
        
        # Filter strong zones only
        min_strength = self.config.get('general', {}).get('zone_min_strength', 60)
        strong_zones = [z for z in all_zones if z.get('strength', 0) >= min_strength]
        
        logger.info(f"  📊 {symbol} {entry_tf} Flip-Retest check: {len(strong_zones)} strong zones (min strength: {min_strength})")
        
        if not strong_zones:
            return None
        
        # Look for recent zone breaks + retests
        for zone in strong_zones:
            zone_low = zone['low']
            zone_high = zone['high']
            zone_kind = zone['kind']
            
            # Check for LONG setup (Resistance flip)
            if zone_kind == 'R':
                # Look for break above zone
                break_idx = None
                for i in range(len(df) - retest_timeout, len(df) - confirm_closes):
                    if i < 0:
                        continue
                    if df['close'].iloc[i] > zone_high + (break_atr * atr):
                        break_idx = i
                        break
                
                if break_idx is None:
                    continue
                
                logger.debug(f"  🔺 {symbol} {entry_tf} LONG: Zone break found at bar {break_idx} (R @ {zone_high:.4f})")
                
                # Log body_break event
                self._log_zone_event(
                    symbol=symbol,
                    zone=zone,
                    event_type='body_break',
                    bar_data=df.iloc[break_idx],
                    market_regime=market_regime,
                    atr=atr
                )
                
                # Check confirmation (closes above zone)
                confirmed = True
                for i in range(break_idx + 1, min(break_idx + confirm_closes + 1, len(df))):
                    if df['close'].iloc[i] <= zone_high:
                        confirmed = False
                        break
                
                if not confirmed:
                    logger.debug(f"  ❌ {symbol} {entry_tf} LONG: Break not confirmed")
                    continue
                
                logger.debug(f"  ✅ {symbol} {entry_tf} LONG: Break confirmed ({confirm_closes} closes)")
                
                # Log flip event
                self._log_zone_event(
                    symbol=symbol,
                    zone=zone,
                    event_type='flip',
                    bar_data=df.iloc[break_idx + confirm_closes],
                    market_regime=market_regime,
                    atr=atr
                )
                
                # Check retest (price returned to zone)
                retest_found = False
                for i in range(break_idx + confirm_closes, len(df)):
                    low = df['low'].iloc[i]
                    # Price touches zone edge (within delta)
                    if low <= zone_high + (retest_delta_atr * atr):
                        logger.debug(f"  🔄 {symbol} {entry_tf} LONG: Retest found at bar {i}")
                        
                        # Log retest event
                        self._log_zone_event(
                            symbol=symbol,
                            zone=zone,
                            event_type='retest',
                            bar_data=df.iloc[i],
                            market_regime=market_regime,
                            atr=atr
                        )
                        
                        # Check entry trigger
                        if i < len(df) - 1:
                            trigger = self._check_entry_trigger(df, i, i+1, 'LONG', flip_config)
                            if trigger:
                                logger.debug(f"  ✅ {symbol} {entry_tf} LONG: Entry trigger confirmed ({trigger})")
                                
                                # VWAP bias check
                                if not await self._check_vwap_bias(df, 'LONG', indicators):
                                    logger.debug(f"  ❌ {symbol} {entry_tf} LONG: VWAP bias failed")
                                    continue
                                
                                logger.info(f"  🎯 {symbol} {entry_tf} LONG: Building Flip-Retest signal!")
                                
                                # Build signal (pass signal_id for zone event linking later)
                                signal = await self._build_flip_retest_signal(
                                    symbol, entry_tf, df, zone, 'LONG',
                                    market_regime, indicators, atr
                                )
                                
                                return signal
                
            # Check for SHORT setup (Resistance flip - same as LONG, but opposite direction)
            # ✅ FIX: SHORT FlipRetest also uses 'R' zones (Resistance broken DOWN)
            # LONG: R zone broken UP → becomes new S → retest from below
            # SHORT: R zone broken DOWN → becomes new S → retest from above
            # Both start with Resistance zone!
            
            # We already checked R zones for LONG above (lines 289-375)
            # For SHORT, we need to check the SAME R zones but for downside break
            # So we check BOTH directions on each R zone
            
            # Add SHORT check for R zones (after LONG check)
            if zone_kind == 'R':
                # Already checked for LONG above, now check for SHORT
                # Look for break BELOW zone (R broken down)
                break_idx = None
                for i in range(len(df) - retest_timeout, len(df) - confirm_closes):
                    if i < 0:
                        continue
                    if df['close'].iloc[i] < zone_low - (break_atr * atr):
                        break_idx = i
                        break
                
                if break_idx is None:
                    continue
                
                logger.debug(f"  🔻 {symbol} {entry_tf} SHORT: Zone break found at bar {break_idx} (R @ {zone_low:.4f})")
                
                # Log body_break event
                self._log_zone_event(
                    symbol=symbol,
                    zone=zone,
                    event_type='body_break',
                    bar_data=df.iloc[break_idx],
                    market_regime=market_regime,
                    atr=atr
                )
                
                # Check confirmation (closes BELOW zone)
                confirmed = True
                for i in range(break_idx + 1, min(break_idx + confirm_closes + 1, len(df))):
                    if df['close'].iloc[i] >= zone_low:
                        confirmed = False
                        break
                
                if not confirmed:
                    logger.debug(f"  ❌ {symbol} {entry_tf} SHORT: Break not confirmed")
                    continue
                
                logger.debug(f"  ✅ {symbol} {entry_tf} SHORT: Break confirmed ({confirm_closes} closes)")
                
                # Log flip event
                self._log_zone_event(
                    symbol=symbol,
                    zone=zone,
                    event_type='flip',
                    bar_data=df.iloc[break_idx + confirm_closes],
                    market_regime=market_regime,
                    atr=atr
                )
                
                # Check retest (price returns to zone from below)
                for i in range(break_idx + confirm_closes, len(df)):
                    high = df['high'].iloc[i]
                    if high >= zone_low - (retest_delta_atr * atr):
                        logger.debug(f"  🔄 {symbol} {entry_tf} SHORT: Retest found at bar {i}")
                        
                        # Log retest event
                        self._log_zone_event(
                            symbol=symbol,
                            zone=zone,
                            event_type='retest',
                            bar_data=df.iloc[i],
                            market_regime=market_regime,
                            atr=atr
                        )
                        
                        if i < len(df) - 1:
                            trigger = self._check_entry_trigger(df, i, i+1, 'SHORT', flip_config)
                            if trigger:
                                logger.debug(f"  ✅ {symbol} {entry_tf} SHORT: Entry trigger confirmed ({trigger})")
                                
                                if not await self._check_vwap_bias(df, 'SHORT', indicators):
                                    logger.debug(f"  ❌ {symbol} {entry_tf} SHORT: VWAP bias failed")
                                    continue
                                
                                logger.info(f"  🎯 {symbol} {entry_tf} SHORT: Building Flip-Retest signal!")
                                
                                signal = await self._build_flip_retest_signal(
                                    symbol, entry_tf, df, zone, 'SHORT',
                                    market_regime, indicators, atr
                                )
                                
                                return signal
        
        return None
    
    async def _check_sweep_return(self, symbol: str, entry_tf: str, df: pd.DataFrame,
                                  zones: Dict, market_regime: str, indicators: dict) -> Optional[Dict]:
        """
        Check for Sweep-Return (liquidity grab) setup
        
        Logic:
        1. Find zone that was swept (wick beyond zone, body stays inside)
        2. Check fast return (within N bars)
        3. Validate wick/body ratio
        4. Check volume spike
        5. Validate VWAP bias (with exception for A-grade sweeps)
        
        Args:
            symbol: Trading symbol
            entry_tf: Entry timeframe
            df: Entry TF DataFrame
            zones: All zones
            market_regime: Market regime
            indicators: Indicators dict
            
        Returns:
            Signal dict or None
        """
        if len(df) < 10:
            return None
        
        # Get config
        sweep_config = self.config.get('sweep_return', {})
        max_bars = sweep_config.get('sweep_max_bars', 3)
        min_wick_ratio = sweep_config.get('sweep_min_wick_ratio', 1.2)
        return_body_inside = sweep_config.get('return_body_inside', True)
        
        # Get ATR
        atr = indicators.get(entry_tf, {}).get('atr', df['close'].iloc[-1] * 0.01)
        
        # Get zones
        entry_zones = zones.get(entry_tf, [])
        h4_zones = zones.get('4h', [])
        d_zones = zones.get('1d', [])
        all_zones = entry_zones + h4_zones + d_zones
        
        # Filter strong zones
        min_strength = self.config.get('general', {}).get('zone_min_strength', 60)
        strong_zones = [z for z in all_zones if z.get('strength', 0) >= min_strength]
        
        logger.info(f"  📊 {symbol} {entry_tf} Sweep-Return check: {len(strong_zones)} strong zones (min strength: {min_strength})")
        
        if not strong_zones:
            return None
        
        # Look for recent sweeps + returns
        for zone in strong_zones:
            zone_low = zone['low']
            zone_high = zone['high']
            zone_kind = zone['kind']
            
            # Check for LONG setup (Support sweep)
            if zone_kind == 'S':
                # Look for sweep below support
                sweep_idx = None
                for i in range(len(df) - max_bars - 1, len(df) - 1):
                    if i < 0:
                        continue
                    
                    bar = df.iloc[i]
                    # Wick goes below zone
                    if bar['low'] < zone_low:
                        # Body closes inside zone (or above)
                        if bar['close'] >= zone_low:
                            # Check wick/body ratio
                            body_size = abs(bar['close'] - bar['open'])
                            lower_wick = min(bar['open'], bar['close']) - bar['low']
                            
                            if body_size > 0 and (lower_wick / body_size) >= min_wick_ratio:
                                sweep_idx = i
                                break
                
                if sweep_idx is None:
                    continue
                
                logger.debug(f"  💧 {symbol} {entry_tf} LONG: Support sweep found at bar {sweep_idx} (S @ {zone_low:.4f})")
                
                # Calculate wick/body ratio for event logging
                sweep_bar = df.iloc[sweep_idx]
                body_size = abs(sweep_bar['close'] - sweep_bar['open'])
                lower_wick = min(sweep_bar['open'], sweep_bar['close']) - sweep_bar['low']
                wick_ratio = lower_wick / body_size if body_size > 0 else 0
                
                # Log sweep event
                self._log_zone_event(
                    symbol=symbol,
                    zone=zone,
                    event_type='sweep',
                    bar_data=sweep_bar,
                    market_regime=market_regime,
                    atr=atr,
                    wick_to_body_ratio=wick_ratio
                )
                
                # Check return (price back inside/above zone)
                for i in range(sweep_idx + 1, min(sweep_idx + max_bars + 1, len(df))):
                    bar = df.iloc[i]
                    
                    # Return condition
                    if return_body_inside and bar['close'] > zone_low:
                        logger.debug(f"  🔄 {symbol} {entry_tf} LONG: Fast return at bar {i} (within {i - sweep_idx} bars)")
                        
                        # Check entry trigger
                        if i < len(df) - 1:
                            # Check A-grade sweep
                            is_a_grade = self._check_a_grade_sweep(df, sweep_idx, i, sweep_config)
                            if is_a_grade:
                                logger.info(f"  ⭐ {symbol} {entry_tf} LONG: A-GRADE sweep detected!")
                            
                            # VWAP bias (allow exception for A-grade)
                            vwap_ok = await self._check_vwap_bias(df, 'LONG', indicators)
                            if not vwap_ok and not is_a_grade:
                                logger.debug(f"  ❌ {symbol} {entry_tf} LONG: VWAP bias failed (not A-grade)")
                                continue
                            
                            logger.info(f"  🎯 {symbol} {entry_tf} LONG: Building Sweep-Return signal!")
                            
                            # Build signal
                            return await self._build_sweep_return_signal(
                                symbol, entry_tf, df, zone, 'LONG',
                                market_regime, indicators, atr, sweep_idx, is_a_grade
                            )
            
            # Check for SHORT setup (Resistance sweep)
            elif zone_kind == 'R':
                sweep_idx = None
                for i in range(len(df) - max_bars - 1, len(df) - 1):
                    if i < 0:
                        continue
                    
                    bar = df.iloc[i]
                    if bar['high'] > zone_high:
                        if bar['close'] <= zone_high:
                            body_size = abs(bar['close'] - bar['open'])
                            upper_wick = bar['high'] - max(bar['open'], bar['close'])
                            
                            if body_size > 0 and (upper_wick / body_size) >= min_wick_ratio:
                                sweep_idx = i
                                break
                
                if sweep_idx is None:
                    continue
                
                logger.debug(f"  💧 {symbol} {entry_tf} SHORT: Resistance sweep found at bar {sweep_idx} (R @ {zone_high:.4f})")
                
                # Calculate wick/body ratio for event logging
                sweep_bar = df.iloc[sweep_idx]
                body_size = abs(sweep_bar['close'] - sweep_bar['open'])
                upper_wick = sweep_bar['high'] - max(sweep_bar['open'], sweep_bar['close'])
                wick_ratio = upper_wick / body_size if body_size > 0 else 0
                
                # Log sweep event
                self._log_zone_event(
                    symbol=symbol,
                    zone=zone,
                    event_type='sweep',
                    bar_data=sweep_bar,
                    market_regime=market_regime,
                    atr=atr,
                    wick_to_body_ratio=wick_ratio
                )
                
                for i in range(sweep_idx + 1, min(sweep_idx + max_bars + 1, len(df))):
                    bar = df.iloc[i]
                    
                    if return_body_inside and bar['close'] < zone_high:
                        logger.debug(f"  🔄 {symbol} {entry_tf} SHORT: Fast return at bar {i} (within {i - sweep_idx} bars)")
                        
                        if i < len(df) - 1:
                            is_a_grade = self._check_a_grade_sweep(df, sweep_idx, i, sweep_config)
                            if is_a_grade:
                                logger.info(f"  ⭐ {symbol} {entry_tf} SHORT: A-GRADE sweep detected!")
                            
                            vwap_ok = await self._check_vwap_bias(df, 'SHORT', indicators)
                            if not vwap_ok and not is_a_grade:
                                logger.debug(f"  ❌ {symbol} {entry_tf} SHORT: VWAP bias failed (not A-grade)")
                                continue
                            
                            logger.info(f"  🎯 {symbol} {entry_tf} SHORT: Building Sweep-Return signal!")
                            
                            return await self._build_sweep_return_signal(
                                symbol, entry_tf, df, zone, 'SHORT',
                                market_regime, indicators, atr, sweep_idx, is_a_grade
                            )
        
        return None
    
    def _check_entry_trigger(self, df: pd.DataFrame, prev_idx: int, curr_idx: int,
                            direction: str, config: dict) -> bool:
        """Check entry trigger patterns (engulfing, choch)"""
        triggers = config.get('entry_triggers', ['engulfing', 'choch'])
        
        prev_bar = df.iloc[prev_idx]
        curr_bar = df.iloc[curr_idx]
        
        if 'engulfing' in triggers:
            if detect_engulfing(curr_bar, prev_bar, direction):
                return True
        
        if 'choch' in triggers:
            if detect_choch(df.iloc[:curr_idx+1], direction, lookback=5):
                return True
        
        return False
    
    def _check_a_grade_sweep(self, df: pd.DataFrame, sweep_idx: int, return_idx: int,
                            config: dict) -> bool:
        """Check if sweep is A-grade (high quality)"""
        a_wick_ratio = config.get('a_grade_wick_ratio', 2.0)
        a_return_bars = config.get('a_grade_return_bars', 2)
        
        sweep_bar = df.iloc[sweep_idx]
        body_size = abs(sweep_bar['close'] - sweep_bar['open'])
        
        if body_size < 0.0001:
            return False
        
        # Check wick ratio
        if sweep_bar['close'] >= sweep_bar['open']:  # Green bar (support sweep)
            lower_wick = sweep_bar['open'] - sweep_bar['low']
            wick_ratio = lower_wick / body_size
        else:  # Red bar (resistance sweep)
            upper_wick = sweep_bar['high'] - sweep_bar['close']
            wick_ratio = upper_wick / body_size
        
        # Check return speed
        return_bars = return_idx - sweep_idx
        
        return wick_ratio >= a_wick_ratio and return_bars <= a_return_bars
    
    async def _check_vwap_bias(self, df: pd.DataFrame, direction: str, indicators: dict) -> bool:
        """Check VWAP bias alignment"""
        vwap_config = self.config.get('vwap_bias', {})
        
        if not vwap_config.get('enabled', True):
            return True
        
        # Get VWAP value
        vwap = indicators.get('vwap', {}).get('value')
        if vwap is None:
            return True  # No VWAP data - allow signal
        
        current_price = df['close'].iloc[-1]
        epsilon_atr = vwap_config.get('bias_epsilon_atr', 0.05)
        atr = indicators.get('atr', df['close'].iloc[-1] * 0.01)
        epsilon = epsilon_atr * atr
        
        # Check bias
        if direction == 'LONG':
            # Price should be above VWAP (or within epsilon)
            return current_price >= (vwap - epsilon)
        else:  # SHORT
            # Price should be below VWAP (or within epsilon)
            return current_price <= (vwap + epsilon)
    
    async def _build_flip_retest_signal(self, symbol: str, entry_tf: str, df: pd.DataFrame,
                                       zone: dict, direction: str, market_regime: str,
                                       indicators: dict, atr: float) -> Dict:
        """Build Flip-Retest signal"""
        # Calculate entry, SL, TP
        entry_price, sl_price, tp1_price, tp2_price = await self._calculate_levels(
            symbol, df, zone, direction, atr, 'FlipRetest'
        )
        
        # Calculate confidence
        confidence, quality_tags = self._calculate_confidence(
            zone, direction, indicators, 'FlipRetest'
        )
        
        # Check min confidence
        min_conf = self.config.get('quality', {}).get('min_confidence', 65)
        if confidence < min_conf:
            logger.debug(f"V3 SR FlipRetest {symbol} confidence {confidence} < {min_conf}")
            return None
        
        # Find nearest zones for context
        current_price = df['close'].iloc[-1]
        nearest_support = find_nearest_zone(current_price, self.zone_cache.get(symbol, {}).get('all', []), 'below', 'S')
        nearest_resistance = find_nearest_zone(current_price, self.zone_cache.get(symbol, {}).get('all', []), 'above', 'R')
        
        # Generate signal
        signal_data = {
            'setup_type': 'FlipRetest',
            'symbol': symbol,
            'direction': direction,
            'entry_tf': entry_tf,
            'zone': zone,
            'nearest_support': nearest_support,
            'nearest_resistance': nearest_resistance,
            'entry_price': entry_price,
            'stop_loss': sl_price,
            'take_profit_1': tp1_price,
            'take_profit_2': tp2_price,
            'confidence': confidence,
            'quality_tags': quality_tags,
            'market_regime': market_regime,
            'atr': atr
        }
        
        logger.info(f"🚀 FLIP-RETEST SIGNAL CREATED: {symbol} {direction} {entry_tf} | Entry: {entry_price:.4f} | SL: {sl_price:.4f} | TP1: {tp1_price:.4f} | TP2: {tp2_price:.4f} | Conf: {confidence}%")
        
        return signal_data
    
    async def _build_sweep_return_signal(self, symbol: str, entry_tf: str, df: pd.DataFrame,
                                        zone: dict, direction: str, market_regime: str,
                                        indicators: dict, atr: float, sweep_idx: int,
                                        is_a_grade: bool) -> Dict:
        """Build Sweep-Return signal"""
        # Similar to flip-retest but with sweep-specific params
        entry_price, sl_price, tp1_price, tp2_price = await self._calculate_levels(
            symbol, df, zone, direction, atr, 'SweepReturn', sweep_idx
        )
        
        confidence, quality_tags = self._calculate_confidence(
            zone, direction, indicators, 'SweepReturn', is_a_grade
        )
        
        min_conf = self.config.get('quality', {}).get('min_confidence', 65)
        if confidence < min_conf:
            return None
        
        current_price = df['close'].iloc[-1]
        nearest_support = find_nearest_zone(current_price, self.zone_cache.get(symbol, {}).get('all', []), 'below', 'S')
        nearest_resistance = find_nearest_zone(current_price, self.zone_cache.get(symbol, {}).get('all', []), 'above', 'R')
        
        signal_data = {
            'setup_type': 'SweepReturn',
            'symbol': symbol,
            'direction': direction,
            'entry_tf': entry_tf,
            'zone': zone,
            'nearest_support': nearest_support,
            'nearest_resistance': nearest_resistance,
            'entry_price': entry_price,
            'stop_loss': sl_price,
            'take_profit_1': tp1_price,
            'take_profit_2': tp2_price,
            'confidence': confidence,
            'quality_tags': quality_tags,
            'market_regime': market_regime,
            'atr': atr,
            'is_a_grade': is_a_grade
        }
        
        a_grade_tag = " [A-GRADE]" if is_a_grade else ""
        logger.info(f"🚀 SWEEP-RETURN SIGNAL CREATED{a_grade_tag}: {symbol} {direction} {entry_tf} | Entry: {entry_price:.4f} | SL: {sl_price:.4f} | TP1: {tp1_price:.4f} | TP2: {tp2_price:.4f} | Conf: {confidence}%")
        
        return signal_data
    
    async def _calculate_levels(self, symbol: str, df: pd.DataFrame, zone: dict,
                                direction: str, atr: float, setup_type: str,
                                sweep_idx: Optional[int] = None) -> Tuple[float, float, float, float]:
        """
        Calculate entry, SL, TP1, TP2 levels
        
        Returns:
            (entry_price, sl_price, tp1_price, tp2_price)
        """
        sl_tp_config = self.config.get('sl_tp', {})
        current_price = df['close'].iloc[-1]
        
        # Entry = current price (market order)
        entry_price = current_price
        
        # Stop Loss calculation
        sl_buffer_atr = sl_tp_config.get('sl_buffer_atr', 0.25)
        
        if setup_type == 'FlipRetest':
            # SL beyond opposite side of zone
            if direction == 'LONG':
                sl_price = zone['low'] - (sl_buffer_atr * atr)
            else:  # SHORT
                sl_price = zone['high'] + (sl_buffer_atr * atr)
        
        else:  # SweepReturn
            # SL beyond sweep extreme
            if sweep_idx is not None:
                sweep_bar = df.iloc[sweep_idx]
                if direction == 'LONG':
                    sl_price = sweep_bar['low'] - (sl_buffer_atr * atr)
                else:
                    sl_price = sweep_bar['high'] + (sl_buffer_atr * atr)
            else:
                # Fallback to zone edge
                if direction == 'LONG':
                    sl_price = zone['low'] - (sl_buffer_atr * atr)
                else:
                    sl_price = zone['high'] + (sl_buffer_atr * atr)
        
        # Calculate risk R
        risk_r = abs(entry_price - sl_price)
        
        # TP1 calculation
        tp1_target = sl_tp_config.get('tp1_target', 'nearest_local_zone')
        tp1_min_r = sl_tp_config.get('tp1_min_r', 0.8)
        
        if tp1_target == '1R':
            if direction == 'LONG':
                tp1_price = entry_price + (risk_r * 1.0)
            else:
                tp1_price = entry_price - (risk_r * 1.0)
        else:  # nearest_local_zone
            # Find nearest zone in direction
            if direction == 'LONG':
                nearest = find_nearest_zone(current_price, self.zone_cache.get(symbol, {}).get('all', []), 'above')
                if nearest:
                    tp1_price = nearest['low']
                else:
                    tp1_price = entry_price + (risk_r * 1.0)
            else:
                nearest = find_nearest_zone(current_price, self.zone_cache.get(symbol, {}).get('all', []), 'below')
                if nearest:
                    tp1_price = nearest['high']
                else:
                    tp1_price = entry_price - (risk_r * 1.0)
            
            # Ensure minimum R
            if abs(tp1_price - entry_price) < (tp1_min_r * risk_r):
                if direction == 'LONG':
                    tp1_price = entry_price + (tp1_min_r * risk_r)
                else:
                    tp1_price = entry_price - (tp1_min_r * risk_r)
        
        # TP2 calculation
        tp2_min_r = sl_tp_config.get('tp2_min_r', 2.0)
        tp2_max_r = sl_tp_config.get('tp2_max_r', 4.0)
        
        if direction == 'LONG':
            tp2_price = entry_price + (risk_r * tp2_min_r)
        else:
            tp2_price = entry_price - (risk_r * tp2_min_r)
        
        # Get proper tick size from Binance exchange info
        tick_size = self.binance_client.get_tick_size(symbol)
        
        # Round prices to tick size
        entry_price = round_price_to_tick(entry_price, tick_size)
        sl_price = round_price_to_tick(sl_price, tick_size)
        tp1_price = round_price_to_tick(tp1_price, tick_size)
        tp2_price = round_price_to_tick(tp2_price, tick_size)
        
        # ✅ FIX: Ensure TP1 != SL after rounding (prevents invalid signals)
        if tp1_price == sl_price:
            if direction == 'LONG':
                tp1_price = sl_price + tick_size
            else:
                tp1_price = sl_price - tick_size
            logger.warning(f"⚠️ {symbol} {direction}: TP1 rounded to SL, adjusted by 1 tick to {tp1_price}")
        
        # ✅ FIX: Ensure SL != Entry after rounding (safety check)
        if entry_price == sl_price:
            if direction == 'LONG':
                sl_price = entry_price - tick_size
            else:
                sl_price = entry_price + tick_size
            logger.warning(f"⚠️ {symbol} {direction}: SL rounded to Entry, adjusted by 1 tick to {sl_price}")
        
        return entry_price, sl_price, tp1_price, tp2_price
    
    def _calculate_confidence(self, zone: dict, direction: str, indicators: dict,
                             setup_type: str, is_a_grade: bool = False) -> Tuple[float, List[str]]:
        """
        Calculate signal confidence score based on zone quality and setup
        
        Returns:
            (confidence, quality_tags)
        """
        quality_config = self.config.get('quality', {})
        
        # Base confidence from zone strength (0-100 scale)
        zone_strength = zone.get('strength', 50)
        confidence = zone_strength * 0.5  # Convert zone strength to base (0-50)
        tags = []
        
        # Zone class bonus (ONLY if not already counted in HTF)
        zone_class = zone.get('class', 'normal')
        zone_tf = zone.get('tf', '15m')
        
        # HTF zone bonus (based on timeframe, not class to avoid double counting)
        if zone_tf == '1d':
            confidence += quality_config.get('htf_d_zone_bonus', 20)
            tags.append('htf_1d')
        elif zone_tf == '4h':
            confidence += quality_config.get('htf_h4_zone_bonus', 15)
            tags.append('htf_4h')
        elif zone_tf == '1h':
            confidence += 10
            tags.append('htf_1h')
        
        # Setup-specific bonuses
        if setup_type == 'FlipRetest':
            confidence += 10
            tags.append('flip_retest')
        elif setup_type == 'SweepReturn':
            confidence += 5
            tags.append('sweep_return')
            if is_a_grade:
                a_bonus = self.config.get('sweep_return', {}).get('a_grade_bonus', 20)
                confidence += a_bonus
                tags.append('a_grade_sweep')
        
        # VWAP bias check (actual verification)
        vwap = indicators.get('vwap', {}).get('value')
        if vwap:
            current_price = indicators.get('current_price', 0)
            if current_price > 0:
                vwap_aligned = False
                if direction == 'LONG' and current_price >= vwap:
                    vwap_aligned = True
                elif direction == 'SHORT' and current_price <= vwap:
                    vwap_aligned = True
                
                if vwap_aligned:
                    confidence += 5
                    tags.append('vwap_aligned')
        
        # Cap at 100
        confidence = min(100.0, confidence)
        
        return confidence, tags
    
    async def _is_symbol_blocked(self, symbol: str) -> bool:
        """Check if symbol is blocked for V3 strategy"""
        session = self.db.get_session()
        try:
            lock = session.query(V3SRSignalLock).filter(
                V3SRSignalLock.symbol == symbol
            ).first()
            
            return lock is not None
        
        finally:
            session.close()
    
    def _log_zone_event(self, symbol: str, zone: dict, event_type: str,
                       bar_data: pd.Series, market_regime: str, atr: float,
                       related_signal_id: Optional[str] = None, wick_to_body_ratio: Optional[float] = None):
        """
        Log zone touch/reaction event to database
        
        Args:
            symbol: Trading symbol
            zone: Zone dict with id, tf, kind, low, high, strength
            event_type: "touch", "body_break", "flip", "sweep", "retest"
            bar_data: Pandas Series with current bar (open, high, low, close)
            market_regime: Current market regime
            atr: ATR value
            related_signal_id: Signal ID if this event created a signal
            wick_to_body_ratio: Wick/body ratio for sweeps
        """
        session = self.db.get_session()
        try:
            # Generate unique event ID (convert bar timestamp to datetime)
            # Safe timestamp conversion with fallback
            try:
                if isinstance(bar_data.name, pd.Timestamp):
                    bar_timestamp = bar_data.name.floor('S').to_pydatetime()
                elif isinstance(bar_data.name, datetime):
                    bar_timestamp = bar_data.name.replace(microsecond=0)
                else:
                    # Fallback: use current time
                    bar_timestamp = datetime.now(pytz.UTC).replace(microsecond=0)
            except Exception:
                bar_timestamp = datetime.now(pytz.UTC).replace(microsecond=0)
            
            zone_id = zone.get('id', 'unknown')
            event_id = generate_zone_event_id(zone_id, event_type, bar_timestamp)
            
            # Check if event already exists (prevent duplicates)
            existing = session.query(V3SRZoneEvent).filter(
                V3SRZoneEvent.event_id == event_id
            ).first()
            
            if existing:
                logger.debug(f"V3 Zone Event already exists: {event_id}, skipping")
                return
            
            # Determine touch characteristics
            zone_low = zone.get('low', 0)
            zone_high = zone.get('high', 0)
            zone_mid = zone.get('mid', (zone_low + zone_high) / 2)
            
            bar_high = bar_data['high']
            bar_low = bar_data['low']
            bar_close = bar_data['close']
            
            # Determine side (from_below or from_above)
            if bar_low < zone_mid < bar_high:
                side = "from_below" if bar_close > zone_mid else "from_above"
            elif bar_high <= zone_mid:
                side = "from_below"
            else:
                side = "from_above"
            
            # Calculate penetration depth
            if event_type in ['sweep', 'body_break']:
                if side == "from_below":
                    penetration = max(0, bar_high - zone_high)
                else:
                    penetration = max(0, zone_low - bar_low)
                penetration_depth_atr = penetration / atr if atr > 0 else 0
            else:
                penetration_depth_atr = 0
            
            # Touch price (extreme point)
            if side == "from_below":
                touch_price = bar_high
            else:
                touch_price = bar_low
            
            # Create event
            event = V3SRZoneEvent(
                event_id=event_id,
                zone_id=zone.get('id', 'unknown'),
                symbol=symbol,
                zone_tf=zone.get('tf', 'unknown'),
                zone_kind=zone.get('kind', 'U'),
                zone_low=zone_low,
                zone_high=zone_high,
                zone_strength=zone.get('strength', 0),
                event_type=event_type,
                bar_timestamp=bar_timestamp,
                touch_price=touch_price,
                side=side,
                penetration_depth_atr=penetration_depth_atr,
                wick_to_body_ratio=wick_to_body_ratio,
                market_regime=market_regime,
                volatility_regime='normal',  # Simplified for now
                atr_value=atr,
                related_signal_id=related_signal_id,
                created_at=datetime.now(pytz.UTC)
            )
            
            session.add(event)
            session.commit()
            
            logger.debug(f"V3 Zone Event logged: {symbol} {zone.get('tf')}-{zone.get('kind')} {event_type} @ {touch_price:.4f}")
        
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging zone event: {e}", exc_info=True)
        finally:
            session.close()
    
    async def check_zone_reactions(self, lookback_hours: int = 24, min_bars_wait: int = 3, 
                                   reaction_threshold_atr: float = 0.5):
        """
        Check for price reactions after zone touch events
        
        Args:
            lookback_hours: How far back to check events (default: 24 hours)
            min_bars_wait: Minimum bars to wait before checking reaction
            reaction_threshold_atr: Minimum reaction magnitude to count (in ATR)
        """
        session = self.db.get_session()
        try:
            cutoff_time = datetime.now(pytz.UTC) - timedelta(hours=lookback_hours)
            
            # Get unchecked events from the last N hours
            events = session.query(V3SRZoneEvent).filter(
                V3SRZoneEvent.reaction_checked_at.is_(None),
                V3SRZoneEvent.created_at >= cutoff_time,
                V3SRZoneEvent.event_type.in_(['touch', 'sweep'])  # Only check touches and sweeps
            ).all()
            
            if not events:
                return
            
            logger.info(f"Checking reactions for {len(events)} zone events...")
            
            for event in events:
                try:
                    # Determine timeframe from zone_tf
                    tf = event.zone_tf
                    
                    # Load bars after the event
                    df = self.data_loader.get_data(event.symbol, tf)
                    if df is None or df.empty:
                        continue
                    
                    # Find the event bar
                    event_time = event.bar_timestamp
                    df_after = df[df.index > event_time].head(10)  # Check next 10 bars max
                    
                    if len(df_after) < min_bars_wait:
                        # Not enough bars yet, skip
                        continue
                    
                    # Check for reaction
                    reaction_occurred = False
                    reaction_bars = None
                    reaction_magnitude = 0.0
                    
                    zone_low = event.zone_low
                    zone_high = event.zone_high
                    zone_mid = (zone_low + zone_high) / 2
                    atr = event.atr_value
                    
                    # Expected direction based on zone kind and side
                    if event.zone_kind == 'S':  # Support zone
                        # Expect bounce UP
                        for i, (idx, bar) in enumerate(df_after.iterrows(), 1):
                            # Price moved away from zone upward
                            if bar['close'] > zone_high + (reaction_threshold_atr * atr):
                                reaction_occurred = True
                                reaction_bars = i
                                reaction_magnitude = (bar['high'] - zone_high) / atr
                                break
                    
                    elif event.zone_kind == 'R':  # Resistance zone
                        # Expect bounce DOWN
                        for i, (idx, bar) in enumerate(df_after.iterrows(), 1):
                            # Price moved away from zone downward
                            if bar['close'] < zone_low - (reaction_threshold_atr * atr):
                                reaction_occurred = True
                                reaction_bars = i
                                reaction_magnitude = (zone_low - bar['low']) / atr
                                break
                    
                    # Update event in database
                    event.reaction_occurred = reaction_occurred
                    event.reaction_bars = reaction_bars
                    event.reaction_magnitude_atr = reaction_magnitude if reaction_occurred else None
                    event.reaction_checked_at = datetime.now(pytz.UTC)
                    
                    session.commit()
                    
                    if reaction_occurred:
                        logger.debug(f"✅ Reaction detected: {event.symbol} {event.zone_tf}-{event.zone_kind} "
                                   f"(+{reaction_magnitude:.2f}R in {reaction_bars} bars)")
                
                except Exception as e:
                    logger.error(f"Error checking reaction for event {event.event_id}: {e}")
                    continue
            
            logger.info(f"Reaction check completed for {len(events)} events")
        
        except Exception as e:
            logger.error(f"Error in check_zone_reactions: {e}", exc_info=True)
        finally:
            session.close()
    
    async def update_zone_strength_from_events(self, symbol: str, zone_id: str) -> Optional[float]:
        """
        Calculate updated zone strength based on accumulated events
        
        Args:
            symbol: Trading symbol
            zone_id: Zone ID
            
        Returns:
            Updated strength score (0-100) or None if no events
        """
        session = self.db.get_session()
        try:
            # Get all events for this zone
            events = session.query(V3SRZoneEvent).filter(
                V3SRZoneEvent.zone_id == zone_id,
                V3SRZoneEvent.symbol == symbol,
                V3SRZoneEvent.reaction_checked_at.isnot(None)  # Only checked events
            ).all()
            
            if not events:
                return None
            
            # Calculate success metrics
            total_touches = len(events)
            successful_reactions = sum(1 for e in events if e.reaction_occurred)
            
            if total_touches == 0:
                return None
            
            # Success rate
            success_rate = successful_reactions / total_touches
            
            # Average reaction magnitude for successful reactions
            successful_magnitudes = [e.reaction_magnitude_atr for e in events 
                                   if e.reaction_occurred and e.reaction_magnitude_atr]
            avg_reaction = sum(successful_magnitudes) / len(successful_magnitudes) if successful_magnitudes else 0
            
            # Recency factor (newer events matter more)
            now = datetime.now(pytz.UTC)
            recent_events = [e for e in events if (now - e.created_at).days <= 7]
            recent_success_rate = (sum(1 for e in recent_events if e.reaction_occurred) / len(recent_events)) if recent_events else success_rate
            
            # Calculate new strength (weighted formula)
            base_strength = events[0].zone_strength if events else 50.0
            
            # Modifiers
            success_modifier = (success_rate - 0.5) * 40  # ±20 points for 0-100% success
            recency_modifier = (recent_success_rate - 0.5) * 20  # ±10 points for recent performance
            magnitude_modifier = min(avg_reaction * 10, 20)  # Up to +20 for strong reactions
            
            # Degradation factor (too many touches = zone weakening)
            touch_penalty = max(0, (total_touches - 5) * 2)  # -2 per touch after 5th
            
            new_strength = base_strength + success_modifier + recency_modifier + magnitude_modifier - touch_penalty
            new_strength = max(0, min(100, new_strength))  # Clamp 0-100
            
            logger.debug(f"Zone {zone_id} strength update: {base_strength:.1f} → {new_strength:.1f} "
                       f"(success: {success_rate:.1%}, touches: {total_touches}, avg_reaction: {avg_reaction:.2f}R)")
            
            return new_strength
        
        except Exception as e:
            logger.error(f"Error updating zone strength: {e}", exc_info=True)
            return None
        finally:
            session.close()
    
    async def block_symbol(self, symbol: str, direction: str, signal_id: str):
        """Block symbol for V3 strategy"""
        session = self.db.get_session()
        try:
            # Remove old lock if exists
            session.query(V3SRSignalLock).filter(
                V3SRSignalLock.symbol == symbol,
                V3SRSignalLock.direction == direction
            ).delete()
            
            # Create new lock
            lock = V3SRSignalLock(
                symbol=symbol,
                direction=direction,
                signal_id=signal_id,
                created_at=datetime.now(pytz.UTC)
            )
            session.add(lock)
            session.commit()
            
            logger.info(f"V3 SR: Blocked {symbol} {direction} for signal {signal_id}")
        
        except Exception as e:
            session.rollback()
            logger.error(f"Error blocking symbol: {e}")
        finally:
            session.close()
    
    async def unblock_symbol(self, symbol: str, direction: str):
        """Unblock symbol for V3 strategy"""
        session = self.db.get_session()
        try:
            session.query(V3SRSignalLock).filter(
                V3SRSignalLock.symbol == symbol,
                V3SRSignalLock.direction == direction
            ).delete()
            session.commit()
            
            logger.info(f"V3 SR: Unblocked {symbol} {direction}")
        
        except Exception as e:
            session.rollback()
            logger.error(f"Error unblocking symbol: {e}")
        finally:
            session.close()
