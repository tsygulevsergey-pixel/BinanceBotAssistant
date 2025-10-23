# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot. Its primary purpose is to provide a high-performance, automated trading solution with a target of 80%+ Win Rate and a Profit Factor of 1.8-2.5. It integrates advanced trading strategies, real-time market regime detection, sophisticated risk management, and an "Action Price" system based on Support/Resistance, Anchored VWAP, and price action. The bot supports both Signals-Only and Live Trading Modes, focusing on precise signal generation, dynamic entry/exit management, and robust performance tracking to achieve consistent profitability.

# User Preferences

- **Preferred communication style**: Simple, everyday language.
- **User runs bot locally on Windows PC in Ukraine** (not on Replit cloud)
- **Log files come from user's local computer** - when user attaches logs, they are from the bot running on their Windows machine
- **This Replit project contains the complete source code** - all code is here and kept up to date
- **Workflow setup is for Replit testing only** - user downloads code to run locally with his own API keys
- **When user shares logs or reports errors:**
    1. Logs are from their local Windows environment running Python bot
    2. They test/run the bot independently on their computer
    3. This Replit workspace is the source code repository
    4. Any fixes made here need to be downloaded by user to their local machine

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: Handles REST API with rate limiting.
- **DataLoader**: Manages historical candle data with parallel loading, data integrity, and smart freshness checks.
- **OrderBook**: Local engine synchronized via REST and WebSocket.
- **BinanceWebSocket**: Real-time market data streaming.
- **Smart Candle-Sync Main Loop**: Synchronizes signal checks to candle close times.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries).
- **Performance Optimization**: Employs BULK UPSERT for candle persistence and composite unique indexing.

### Strategy Framework
- **BaseStrategy**: Abstract class for strategy definition.
- **StrategyManager**: Orchestrates strategy execution based on market regimes.
- **Signal Dataclass**: Standardized output for trading signals.
- **6 Core Strategies**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile, ATR Momentum.
- **Action Price System**: 11-component scoring for dynamic entry, TP, and SL.
- **Strategy Execution Optimization**: Parallelized strategy execution and independent Action Price processing.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market states.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for indicators.

### Signal Scoring & Aggregation
- Combines strategy scores with market modifiers, BTC filter, and conflict resolution, including multi-timeframe CVD divergence detection.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement.
- **Trailing Stop-Loss with Partial TP**: Configurable 3-Tier TP System.
- **Market Entry System**: All strategies execute MARKET orders.
- **Time Stops**: Exits trades if no progress.
- **Symbol Blocking System**: Independent blocking per strategy.
- **Action Price SL Filter**: Rejects signals with excessively wide stop-loss.

### Telegram Integration
- Provides commands for bot status, strategy details, performance, validation, and signal alerts with a persistent button keyboard UI.

### Logging System
- Features `Main Bot Log`, dedicated `Action Price Log`, `V3 S/R Log`, and `JSONL Logging` for centralized signal data. Supports configurable log levels, lazy initialization, and robust file handling.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, exit conditions, and PnL.
- **ActionPricePerformanceTracker**: Tracks Action Price signals, partial exits, breakeven logic, MFE/MAE, and logs to JSONL.

### Configuration Management
- Uses YAML for strategy parameters and environment variables for API keys. Supports `signals_only_mode` and `enabled` flags.

## System Design Choices

### Data Flow
Loads configurations, connects to Binance, processes data in parallel, and launches the Telegram bot. Real-time operations involve WebSocket updates, market data processing, indicator calculation, parallel strategy execution, signal scoring, filtering, and Telegram alerts. Data is persisted in SQLite, and signals are logged.

### Error Handling & Resilience
- Implements `Smart Rate Limiting`, `IP BAN Prevention`, `Periodic Gap Refill`, `Burst Catchup Safety`, `Exponential Backoff`, `Auto-Reconnection` (WebSocket), `Graceful Shutdown`, and `Timeout Protection`.

## Feature Specifications

### V3 S/R Strategy System
- **Status**: PRODUCTION READY, fully integrated as an independent trading strategy.
- **Core Setups**: `Flip-Retest Setup` and `Sweep-Return Setup`.
- **Architecture**: Dedicated database tables, independent performance tracking with virtual partial exits and MFE/MAE, and a comprehensive signal scoring system based on zone quality.
- **Key Features**: VWAP Bias Filter, A-grade Exception, Zone Context, Market Regime Filtering, Adaptive SL/TP, and multi-timeframe analysis (15m/1H entry, 4H/1D context).
- **V3 Zones Infrastructure**: Utilizes DBSCAN-based clustering, reaction strength validation, and an optimized scoring system considering touches, reactions, freshness, confluence, and noise penalty. Includes adaptive fractal swing detection and volatility-based zone width. Zone building is parallelized.
- **Zone Quality Filters & Purity Gate**: Two-stage advanced filtering system: Outlier Removal, Width Guards, KDE Prominence Check, Purity Check, and Freshness Check.
- **V3 Zones Integration**: Break & Retest strategy now uses V3 professional S/R zones with a `Shared Zones Provider` for efficient caching, leading to enhanced retest zone detection and score bonuses for high-grade zones.
- **Dual-Timeframe Signal Generation System**:
  - **ZoneRegistry**: Shared zone state updated once per tick.
  - **BaseSignalEngine**: Common detection logic for Flip-Retest and Sweep-Return setups.
  - **SignalEngine_M15**: Scalp conveyor with 0.5% risk, 0.6 ATR/12 bars, SL +0.25 ATR, strict VWAP bias, enhanced confirmation in opposite H1 zones.
  - **SignalEngine_H1**: Swing conveyor with 1.0% risk, 0.7 ATR/8 bars, SL +0.3 ATR, optional VWAP bias with HTF confluence.
  - **CrossTFArbitrator**: Blocks M15 signals against opposite H1 direction, allows piggyback, per-TF locks, front-run protection.
  - **Legacy Format Conversion**: Ensures compatibility with existing tracking/statistics infrastructure.

# External Dependencies

## Exchange Integration
- **Binance Futures API**: REST endpoints for market and account data.
- **Binance WebSocket**: Real-time market data streams.
- **Binance Vision**: Historical data archive.

## Third-Party Services
- **Telegram Bot API**: For message delivery and interactive commands.

## Python Libraries
- **Data Processing**: pandas, numpy, pandas-ta.
- **Network**: aiohttp, websockets.
- **Database**: SQLAlchemy, Alembic.
- **Exchange**: python-binance, ccxt.
- **Scheduling**: APScheduler.
- **Configuration**: pyyaml, python-dotenv.

---

# Recent Fixes (October 23, 2025)

## Problem #11: Stop-Loss Above Entry for LONG Signals (FlipRetest Direction Bug) - RESOLVED ✅

**Issue:** LONG FlipRetest signals had Stop-Loss ABOVE entry price instead of BELOW, making them impossible to trade.

**Example from BTCUSDT Signal:**
```
Entry: 109469.9
SL: 110555.7  ❌ ABOVE entry for LONG!
TP1: 112031.2
TP2: 114482.6
```

**Root Cause (Identified by Architect):**
- **signal_engine_base.py (line 111):** `flip_side_original = zone.get('flip_side', zone_kind)`
- When `flip_side` metadata was missing from zone, code fell back to **current** `zone['kind']` instead of original type BEFORE flip
- Resistance zones (`zone['kind'] = 'R'`) that should flip to Support were incorrectly treated as still being Resistance
- Wrong direction determination → SL placed at `zone['low']` (Resistance floor) which is ABOVE market price
- Result: SL > entry for LONG signals ❌

**Original Logic (WRONG):**
```python
flip_side_original = zone.get('flip_side', zone_kind)  # Fallback to current type

if flip_side_original == 'S':
    expected_direction = 'SHORT'  # Was S, now R
else:
    expected_direction = 'LONG'   # Was R, now S

# But if flip_side missing and zone['kind']='R', it thinks "was R" → LONG
# But zone is STILL R (didn't flip)! → SL above entry
```

**Corrected Logic:**
```python
# Use CURRENT zone type to determine direction
if zone_kind == 'S':
    # Current Support → LONG (bounce up)
    expected_direction = 'LONG'
    flip_side = 'above'
else:
    # Current Resistance → SHORT (rejection down)
    expected_direction = 'SHORT'
    flip_side = 'below'
```

**Solution Implemented:**
- **signal_engine_base.py (lines 111-123):** Refactored direction logic
  - Determine direction from **CURRENT** `zone['kind']` after flip
  - Support zones → LONG signals (expect bounce up)
  - Resistance zones → SHORT signals (expect rejection down)
  - No longer relies on potentially missing `flip_side` metadata

**Result:**
- ✅ LONG signals: SL < Entry (below entry)
- ✅ SHORT signals: SL > Entry (above entry)
- ✅ Direction correctly matches zone role
- ✅ Signals are now tradeable

---

## Problem #10: TP1 = TP2 When HTF Zone Closer Than 1R - RESOLVED ✅

**Issue:** TP1 and TP2 were identical in signals when HTF zone was closer than 1R risk distance.

**Example from BTCUSDT Signal:**
```
Entry: 111175.2
TP1: 111278.9
TP2: 111278.9  ❌ Same as TP1!
```

**Root Cause:**
- **H1 Engine (line 307):** `levels['tp2'] = max(levels['tp1'], tp2_candidate)`
- **M15 Engine (line 444):** `levels['tp2'] = max(levels['tp1'], tp2_candidate)`
- Logic tried to prevent TP2 < TP1 by using max(), but created TP1 = TP2 instead

**Original Logic (WRONG):**
```python
tp1 = entry + risk  # 1R always
tp2 = nearest_htf_zone
if tp2 < tp1:  # If HTF zone closer than 1R
    tp2 = tp1  # ❌ Makes them equal!
```

**Corrected Logic:**
```python
# TP1 = nearest target (HTF zone OR 1R, whichever closer)
# TP2 = next target (next HTF zone OR 2R)

if first_htf_zone < 1R:
    tp1 = first_htf_zone
    tp2 = second_htf_zone or 2R
else:
    tp1 = 1R
    tp2 = first_htf_zone
```

**Solution Implemented:**
1. **signal_engine_h1.py (lines 292-347):** Refactored TP calculation logic
   - Sort HTF zones by distance from entry
   - Compare first HTF zone with 1R
   - Set TP1 to nearest, TP2 to next target
   - Fallback to 2R if no second zone exists

2. **signal_engine_m15.py (lines 429-484):** Applied same logic for M15
   - Uses H1 zones instead of HTF zones
   - Same sorting and comparison logic

**Result:**
- ✅ TP1 always shows nearest target (HTF zone or 1R)
- ✅ TP2 always shows next target (next HTF zone or 2R)
- ✅ TP2 always > TP1 for LONG (or TP2 < TP1 for SHORT)
- ✅ Signals now have meaningful tiered targets

---

## Problem #9: Entry Price Used Zone Edge Instead of Current Price - RESOLVED ✅

**Issue:** Signals used zone edge (zone['high'] for LONG, zone['low'] for SHORT) as entry price instead of actual current market price at signal generation time.

**Root Cause:**
- **signal_engine_base.py (line 484-488):** `_create_signal()` used zone edge for entry calculation
- Entry price did not reflect actual market conditions at signal time

**Solution Implemented:**
1. **signal_engine_base.py (line 465, 490-497):** Added `current_price` parameter to `_create_signal()`
2. **signal_engine_h1.py (line 245):** Pass `current_price` to `_create_signal()`
3. **signal_engine_m15.py (line 248):** Pass `current_price` to `_create_signal()`

**Result:**
- ✅ Entry price = actual current market price at signal time
- ✅ More accurate entry levels for market orders
- ✅ Better reflects real trading conditions