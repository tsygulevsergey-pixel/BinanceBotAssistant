# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for high-performance trading, targeting an 80%+ Win Rate and a Profit Factor of 1.8-2.5. It integrates advanced trading strategies, real-time market regime detection, sophisticated risk management, and an "Action Price" system based on Support/Resistance, Anchored VWAP, and price action. The bot supports both Signals-Only and Live Trading Modes, emphasizing precise signal generation, dynamic entry/exit management, and robust performance tracking. The project aims to provide a robust and efficient automated trading solution with a focus on consistent profitability and advanced analytical capabilities.

# Recent Fixes (October 23, 2025)

## Problem #6: V3 Strategy 0 Signals Issue - RESOLVED ✅

**Issue:** V3 S/R strategy was generating 0 signals despite successful zone building (232 symbols, 927 zones built).

**Root Cause Analysis:**

**Primary Cause (CRITICAL):** Signal engines were analyzing zones for ALL symbols instead of filtering by current symbol!
- `zone_registry.get_zones('15m')` returns zones for ALL symbols (BTCUSDT, ETHUSDT, SOLUSDT, etc.)
- Engines checked 200+ zones from different symbols against current symbol's price data
- Setup detection failed because zones didn't match current symbol's price range
- **Result:** 0 signals generated

**Secondary Cause:** Zones missing `flipped=False` metadata initialization
- Flip-Retest detector blocked zones without explicit `flipped` field
- Only affected Flip-Retest setup (Sweep-Return unaffected)

**Solution Implemented:**
1. **signal_engine_m15.py (line 72-73, 79-80):** Added symbol filtering for M15 and H1 zones
2. **signal_engine_h1.py (line 72-73):** Added symbol filtering for H1 zones
3. **builder.py (line 349-352):** Added explicit `zone['meta']['flipped'] = False` for new zones
4. **signal_engine_m15.py (line 149-151):** Added debug logging (INFO level) to track detection/filtering
5. **signal_engine_h1.py (line 146-148):** Added debug logging for H1 engine

**Technical Details:**
- ZoneRegistry accumulates zones for all symbols (update() doesn't clear previous symbols)
- Engines must filter zones by symbol: `m15_zones = [z for z in all_m15_zones if z['symbol'] == symbol]`
- This ensures engines only analyze zones relevant to current symbol
- Debug logging will now show actual zone counts and setup detection statistics per symbol

**Expected Behavior After Fix:**
- Each symbol analyzed with its own zones only
- Setup detection should work for Sweep-Return (Flip-Retest requires flipped zones)
- Debug logs will show: `zones_checked`, `zones_locked`, `flip_detected`, `flip_filtered`, `sweep_detected`, `sweep_filtered`

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
- **DataLoader**: Manages historical candle data with `Parallel Data Loading Architecture`, `Data Integrity System`, and `Smart Data Freshness Check`.
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
- Features `Main Bot Log`, dedicated `Action Price Log`, `V3 S/R Log`, and `JSONL Logging` for centralized signal data. Supports configurable log levels. Loggers utilize lazy initialization and robust file handling to ensure correct log file creation and writing upon bot restarts.

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
- **V3 Zones Infrastructure**: Utilizes DBSCAN-based clustering (optimized with `n_jobs=-1` and `algorithm='auto'`), reaction strength validation, and an optimized scoring system considering touches, reactions, freshness, confluence, and noise penalty. Includes adaptive fractal swing detection and volatility-based zone width. Zone building is parallelized using `ProcessPoolExecutor` for performance.
- **Zone Quality Filters & Purity Gate**: Two-stage advanced filtering system:
  - **Stage 1 - Zone Quality Filters**: Outlier Removal (z-score), Width Guards (shrink/split), KDE Prominence Check
  - **Stage 2 - Purity & Freshness Gate**: Purity Check (bars inside < 35%), Freshness Check (last touch age). This stage runs before validation to prevent metadata corruption.
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