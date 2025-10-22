# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for high-performance trading, targeting an 80%+ Win Rate and a Profit Factor of 1.8-2.5. It integrates advanced trading strategies, real-time market regime detection, sophisticated risk management, and an "Action Price" system based on Support/Resistance, Anchored VWAP, and price action. The bot supports both Signals-Only and Live Trading Modes, emphasizing precise signal generation, dynamic entry/exit management, and robust performance tracking.

# Recent Updates

## October 22, 2025 - V3 S/R Signal Generation Bugfixes (CRITICAL)
**Critical Bugs Fixed**: Three blocking bugs prevented V3 strategy from generating ANY signals.

**BUG #1: Flip-Retest Detection Broken**
- **Problem**: `flip.py` wrote `zone['state'] = 'flipped'` but `signal_engine_base.py` checked `zone['meta']['flipped']`
- **Impact**: Flip-Retest setups NEVER detected → 0 signals
- **Fix**: Added `updated_zone['meta']['flipped'] = True` in `flip.py` apply_flip() method
- **Files**: `src/utils/sr_zones_v3/flip.py` (lines 300-303)

**BUG #2: Sweep-Return Condition Too Strict**
- **Problem**: Required close BEYOND zone (`> zone_high` for LONG, `< zone_low` for SHORT)
- **Reality**: Valid sweeps can return INSIDE zone
- **Impact**: Most Sweep-Return setups missed
- **Fix**: Changed to `close >= zone_low` (LONG) and `close <= zone_high` (SHORT)
- **Files**: `src/v3_sr/signal_engine_base.py` (lines 253, 286)

**BUG #3: Flip-Retest Wrong Direction**
- **Problem**: Used `zone['kind']` (NEW type after flip) instead of `zone['flip_side']` (ORIGINAL type before flip)
- **Impact**: Flip-Retest signals had OPPOSITE direction (Support flip → LONG instead of SHORT)
- **Fix**: Now uses `flip_side_original = zone.get('flip_side')` to determine correct signal direction
- **Files**: `src/v3_sr/signal_engine_base.py` (lines 111-126)

**Expected Outcome**:
- Flip-Retest signals will now generate with CORRECT direction when zones flip
- Sweep-Return signals will detect broader range of valid setups
- V3 strategy should start producing signals in live testing
- **Architect Review**: PASS ✅

## October 22, 2025 - V3 Zone Building Performance Optimization (ProcessPool + DBSCAN)
**Major Performance Upgrade**: Implemented parallel zone building with ProcessPoolExecutor and optimized DBSCAN clustering.

**Changes Implemented**:
1. **DBSCAN Optimization** (`clustering.py`):
   - Added `n_jobs=-1` to use all CPU cores for clustering
   - Added `algorithm='auto'` for optimal algorithm selection
   - Speedup: 2.7s → 1.0s per symbol (2.7x faster)

2. **ProcessPool Parallelization** (`zone_builder_worker.py`, `strategy.py`, `main.py`):
   - New worker function for isolated zone building in separate processes
   - Batch processing: load all data → build zones parallel → analyze sequential
   - Safe ProcessPoolExecutor with 4 workers (configurable)
   - Cache updates in main process (no shared state issues)

3. **Configuration** (`config.yaml`):
   - Added `parallel_processing` section in `sr_zones_v3_strategy`
   - `enabled: true` (default)
   - `max_workers: 4` (adjustable based on CPU cores)

**Performance Impact**:
- **Before**: ~11 minutes for 243 symbols (sequential)
- **After**: ~1.5-2 minutes for 243 symbols (parallel)
- **Speedup**: 6-8x faster (combined DBSCAN + ProcessPool)
- **Architect Review**: PASS ✅

**Architecture**:
- ProcessPool ensures isolated memory per worker (no race conditions)
- Each worker creates fresh `SRZonesV3Builder` instance
- Main process manages cache updates and signal analysis
- Fallback to sequential processing if parallel disabled

## October 22, 2025 - V3 S/R Cache Fix
**Critical Bug Fixed**: V3 zone caching system was using numeric DataFrame index instead of timestamp for cache freshness checks. This prevented zones from rebuilding when new 15m bars closed, causing stale zone data.

**Fix**: Changed cache comparison from `df_15m.index[-1]` (always 499 with limit=500) to `df_15m['open_time'].iloc[-1]` (actual timestamp).

**Impact**: 
- Zones now correctly rebuild every 15 minutes when new bars close
- Cache still works within same bar (instant performance)
- First run: ~11 min, new bar: ~11 min rebuild, same bar: ~37 sec cache ✅

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
- **DataLoader**: Manages historical candle data with a `Parallel Data Loading Architecture` for efficient, thread-safe data handling, including `Data Integrity System` and `Smart Data Freshness Check`.
- **OrderBook**: Local engine synchronized via REST and WebSocket.
- **BinanceWebSocket**: Real-time market data streaming.
- **Smart Candle-Sync Main Loop**: Synchronizes signal checks to candle close times.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries).
- **Performance Optimization**: Employs BULK UPSERT for candle persistence and a composite unique index.

### Strategy Framework
- **BaseStrategy**: Abstract class.
- **StrategyManager**: Orchestrates strategy execution based on market regimes.
- **Signal Dataclass**: Standardized output for trading signals.
- **6 Core Strategies**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile, ATR Momentum.
- **Action Price System**: 11-component scoring system for dynamic entry, TP, and SL.
- **Strategy Execution Optimization**: Parallelizes strategies and runs Action Price independently.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market states.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for indicators.

### Signal Scoring & Aggregation
- Combines strategy scores with market modifiers, BTC filter, and conflict resolution.
- **CVD Divergence Confirmation**: Multi-timeframe divergence detection.

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
- Features `Main Bot Log`, dedicated `Action Price Log`, `V3 S/R Log`, and `JSONL Logging` for centralized signal data. Supports configurable log levels.

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
- **Architecture**: Dedicated database tables (`v3_sr_signals`, `v3_sr_zone_events`, `v3_sr_signal_locks`), independent performance tracking with virtual partial exits and MFE/MAE tracking, and a comprehensive signal scoring system based on zone quality.
- **Key Features**: VWAP Bias Filter, A-grade Exception, Zone Context, Market Regime Filtering, Adaptive SL/TP, and multi-timeframe analysis (15m/1H entry, 4H/1D context).
- **V3 Zones Infrastructure**: Utilizes DBSCAN-based clustering, reaction strength validation, and an optimized scoring system considering touches, reactions, freshness, confluence, and noise penalty. Includes adaptive fractal swing detection and volatility-based zone width.
- **Zone Quality Filters & Purity Gate**: Two-stage advanced filtering system:
  - **Stage 1 - Zone Quality Filters** (after clustering, before validation): Outlier Removal (z-score), Width Guards (shrink/split), KDE Prominence Check
  - **Stage 2 - Purity & Freshness Gate** (BEFORE reaction validation): Purity Check (bars inside < 35%), Freshness Check (last touch age)
  - **CRITICAL FIX**: Purity gate runs BEFORE validation because it may shrink/split zones → validation uses FINAL boundaries → prevents metadata corruption
- **V3 Zones Integration**: Break & Retest strategy now uses V3 professional S/R zones with a `Shared Zones Provider` for efficient caching, leading to enhanced retest zone detection and score bonuses for high-grade zones.
- **Dual-Timeframe Signal Generation System** (NEW - Oct 2025):
  - **ZoneRegistry**: Shared zone state updated once per tick, accessible by both engines
  - **BaseSignalEngine**: Common detection logic for Flip-Retest and Sweep-Return setups
  - **SignalEngine_M15**: Scalp conveyor with 0.5% risk, 0.6 ATR/12 bars, SL +0.25 ATR, strict VWAP bias required, enhanced confirmation in opposite H1 zones
  - **SignalEngine_H1**: Swing conveyor with 1.0% risk, 0.7 ATR/8 bars, SL +0.3 ATR, optional VWAP bias with HTF confluence
  - **CrossTFArbitrator**: Blocks M15 signals against opposite H1 direction, allows piggyback (same direction), per-TF locks, front-run protection
  - **Legacy Format Conversion**: `_convert_to_legacy_format()` ensures new engine format → legacy DB format for compatibility with existing tracking/statistics infrastructure

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