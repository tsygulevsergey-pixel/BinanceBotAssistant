# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot engineered for high-performance trading, aiming for an 80%+ Win Rate and a Profit Factor of 1.8-2.5. It integrates advanced strategies, real-time market regime detection, sophisticated risk management, and an "Action Price" system based on Support/Resistance, Anchored VWAP, and price action. The bot operates in both Signals-Only and Live Trading Modes, with a strong focus on precise signal generation, dynamic entry/exit management, and robust performance tracking.

## Recent Changes (October 21, 2025)

### 🔗 V3 ZONES INTEGRATION: Break & Retest Strategy ✅ IMPLEMENTED

**Professional S/R Zones for Break & Retest:**
- **New Feature**: Break & Retest strategy now uses V3 professional S/R zones instead of primitive swing ± ATR method
- **Shared Zones Provider** (`src/utils/v3_zones_provider.py`):
  - Singleton pattern for efficient zone caching across strategies
  - Prevents duplicate zone calculations
  - Shared access to V3 zones between Break & Retest and V3 S/R strategies
- **Enhanced Retest Zone Detection**:
  - **V3 Mode** (`use_v3_zones: true`): Uses DBSCAN-clustered zones with reaction validation and multi-TF confluence
  - **Classic Mode** (`use_v3_zones: false`): Fallback to original swing ± 0.3 ATR method
  - Automatic zone quality filtering (minimum strength threshold configurable)
- **Score Bonuses for V3 Zones**:
  - **A-grade zones** (strength ≥80): +2.0 score bonus
  - **B-grade zones** (strength ≥70): +1.5 score bonus
  - **C-grade zones** (strength ≥60): +1.0 score bonus
  - **D-grade zones** (strength ≥50): +0.5 score bonus
  - **HTF zones bonus**: +1.0 (1D), +0.5 (4H) for higher timeframe zones
- **Config Options** (`config.yaml` → `strategies.retest`):
  - `use_v3_zones`: true/false (default: true)
  - `v3_zone_strength_threshold`: 0-100 (default: 50, D-grade minimum)
- **Impact**: Significantly more accurate zone identification, filtering weak swing levels that caused false signals

### 🔧 CRITICAL BUG FIXES: V3 S/R Strategy ✅ FIXED

**Issue 1: SHORT FlipRetest Zone Selection**
- **Problem**: SHORT signals had SL BELOW entry (wrong protection)
- **Root cause**: Used Support zones ('S') instead of Resistance zones ('R')
- **Fix**: Both LONG and SHORT now use Resistance zones correctly:
  - LONG: R zone broken UP → retest from below → SL below zone
  - SHORT: R zone broken DOWN → retest from above → SL above zone

**Issue 2: Confidence Score Calculation**
- **Problem**: 
  - Zone strength not used (read but ignored)
  - Double HTF bonuses (class + timeframe)
  - Fake VWAP bonus without actual check
- **Fix**: Complete rewrite of confidence formula:
  - **Base (0-50)**: zone_strength × 0.5 (main quality factor)
  - **HTF bonus**: +20 (1D) / +15 (4H) / +10 (1H) - NO double counting
  - **Setup**: +10 (FlipRetest) / +5 (SweepReturn)
  - **A-grade**: +20 (high-quality sweeps)
  - **VWAP**: +5 (only if price actually aligned with bias)

**Issue 3: Zone Event Logging Errors**
- **Problem**:
  - Zones missing 'id' field → zone_id='unknown'
  - Invalid timestamp conversion → bar_timestamp='1970-01-01'
  - UNIQUE constraint violations in v3_sr_zone_events table
- **Fix**:
  - Added unique ID generation for all zones (format: "tf_kind_price")
  - Safe timestamp conversion with type checking and fallback
  - Duplicate event detection before database insert
  - Removed nanoseconds warning with .floor('S')

**Additional improvements:**
- Added nearest zones display in Telegram signals
- Diagnostic logging for PnL tracking
- Created check_v3_signals.py for database verification

### V3 Zone Events & Reaction Tracking System ✅ FULLY IMPLEMENTED
Complete real-time zone quality management system to prevent zone degradation:

**Zone Events Logging:**
- **Flip-Retest events**: body_break, flip (R⇄S switch), retest
- **Sweep-Return events**: sweep (with wick/body ratio), return
- Logged fields: event_type, touch_price, side, penetration_depth_atr, wick_to_body_ratio, market_regime, atr_value
- Automatic logging on every candle close for LONG/SHORT setups

**Reaction Tracking (Background Task - every 30 min):**
- Checks if price actually bounced after zone touches
- Updates: reaction_occurred, reaction_bars, reaction_magnitude_atr
- Validates zone effectiveness in real-time

**Auto Zone Strength Updates:**
- Weighted formula: Success rate (±20pts), Recency (±10pts), Reaction magnitude (+20pts), Touch penalty (-2pts after 5th)
- Integrated into zone builder: Every rebuild updates strength from events
- **Result**: Strong zones strengthen, weak zones degrade automatically

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
- **BinanceClient**: Handles REST API with rate limiting and exponential backoff.
- **DataLoader**: Manages historical candle data.
- **OrderBook**: Local engine synchronized via REST and WebSocket.
- **BinanceWebSocket**: Real-time market data streaming.
- **Smart Candle-Sync Main Loop**: Synchronizes signal checks to candle close times.
- **Parallel Data Loading Architecture**: Features `SymbolLoadCoordinator`, `Loader Task`, `Analyzer Task`, and `Symbol Auto-Update Task` for efficient, thread-safe data handling. Includes `Data Integrity System` with gap detection and auto-fix, and a `Smart Data Freshness Check` to optimize API requests.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries).
- **Performance Optimization**: Employs BULK UPSERT for candle persistence and a composite unique index for data integrity, drastically improving save times.

### Strategy Framework
- **BaseStrategy**: Abstract class for trading strategies.
- **StrategyManager**: Orchestrates strategy execution based on market regimes.
- **Signal Dataclass**: Standardized output for trading signals.
- **6 Core Strategies**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile, ATR Momentum.
- **Action Price System**: An 11-component scoring system for dynamic entry, TP, and SL calculations on 15m candles, with improved scoring inversion and dynamic risk management.
- **Strategy Execution Optimization**: Parallelizes regular strategies and runs the Action Price system independently.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market states.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation with vectorized computation.
- **IndicatorCache**: High-performance caching for indicators.

### Signal Scoring & Aggregation
- Combines strategy scores with market modifiers, including BTC filter and conflict resolution.
- **CVD Divergence Confirmation**: Multi-timeframe (15m+1H) divergence detection for bonus scoring.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement with fallbacks.
- **Trailing Stop-Loss with Partial TP**: Configurable 3-Tier TP System (30% @1R, 40% @1.5R/2R, 30% trailing).
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
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and `enabled` flags.

## System Design Choices

### Data Flow
Loads configurations, connects to Binance, processes data in parallel, and launches the Telegram bot. Real-time operations involve WebSocket updates, market data processing, indicator calculation, parallel strategy execution, signal scoring, filtering, and Telegram alerts. Data is persisted in SQLite, and signals are logged.

### Error Handling & Resilience
- Implements `Smart Rate Limiting`, `IP BAN Prevention`, `Periodic Gap Refill`, `Burst Catchup Safety`, `Exponential Backoff`, `Auto-Reconnection` (WebSocket), `Graceful Shutdown`, and `Timeout Protection` for robust operation.

## Feature Specifications

### V3 S/R Strategy System
- **Status**: PRODUCTION READY, fully integrated as an independent trading strategy.
- **Core Setups**: `Flip-Retest Setup` (zone breaks, retest, entry triggers) and `Sweep-Return Setup` (liquidity sweep, wick/body ratio validation, fast return).
- **Architecture**: Dedicated database tables (`v3_sr_signals`, `v3_sr_zone_events`, `v3_sr_signal_locks`), independent performance tracking with virtual partial exits and MFE/MAE tracking, and a comprehensive signal scoring system based on zone quality.
- **Key Features**: VWAP Bias Filter, A-grade Exception, Zone Context, Market Regime Filtering, Adaptive SL/TP, and multi-timeframe analysis (15m/1H entry, 4H/1D context).
- **V3 Zones Infrastructure**: Utilizes DBSCAN-based clustering, reaction strength validation, and an optimized scoring system considering touches, reactions, freshness, confluence (EMA200, round numbers, HTF alignment, VWAP, swing high/low), and noise penalty. Includes adaptive fractal swing detection and volatility-based zone width.

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