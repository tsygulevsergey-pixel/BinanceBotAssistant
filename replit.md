# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories, providing real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading with fast catchup and periodic gap refill, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/SQUEEZE/RANGE/CHOP), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms.

A fully integrated **Action Price** strategy system is included, operating independently to identify high-probability setups using Support/Resistance zones, Anchored VWAP, EMA trend filters, and 5 classic price action patterns (Pin-Bar, Engulfing, Inside-Bar, Fakey, PPR) with partial profit-taking capabilities.

# Recent Changes

## Critical Bugfixes: Data Loader & TimeframeSync (October 12, 2025)
- **Issue 1**: Bot crashed with empty error messages during data loading failures (`Error downloading SPXUSDT 15m: . Retry 1/3...`)
- **Issue 2**: TimeframeSync never detected candle closes - strategies never ran (`⏭️ No candles closed - skipping` every check)
- **Root Cause 1**: DataLoader continued execution with incomplete data after download failures, causing unhandled exceptions
- **Root Cause 2**: TimeframeSync checked cache BEFORE checking if candle closed - always returned False even at :00, :15, :30, :45
- **Fix 1**: DataLoader now raises explicit exception on download failure with proper error message; symbol marked as failed, bot continues with other symbols
- **Fix 2**: TimeframeSync logic reordered - checks candle close time FIRST, then cache; detection window expanded to 90 seconds (e.g., 12:45:00-12:46:30)
- **Result**: Bot no longer crashes on network errors; strategies correctly trigger at candle closes; Runtime Fast Catchup executes properly

## Symbol Blocking Logic Fix (October 2025)
- **Issue**: Symbols were blocked from analysis even when signal saving to DB failed, causing permanent blocking with empty database
- **Root Cause**: `_block_symbol()` was called BEFORE verifying successful DB save - if save failed, symbol stayed blocked forever
- **Fix**: 
  - Changed `_save_signal_to_db()` and `_save_action_price_signal()` to return `bool` (True/False)
  - Symbol blocking now happens ONLY after successful DB save
  - If DB save fails, symbol remains available for analysis with warning logged
- **Result**: Symbols only blocked when signal actually saved to DB, preventing phantom blocks on empty database

## Action Price Database Schema Fix (October 2025)
- **Issue 1**: Action Price signals failed to save with `TypeError: 'zone_type' is an invalid keyword argument`
- **Issue 2**: Telegram send failed with `AttributeError: 'TelegramBot' object has no attribute 'send_message'`
- **Root Cause**: 
  - Code tried to save `zone_type` field that doesn't exist in ActionPriceSignal model
  - Wrong Telegram method called (send_message instead of bot.send_message)
- **Fix**: 
  - Updated `_save_action_price_signal()` to use correct database fields: zone_id, zone_low, zone_high, context_hash, all VWAP/EMA values, confluence_flags JSON
  - Changed Telegram call from `send_message()` to `bot.send_message(chat_id, text, parse_mode)` 
  - Properly mapped all signal data to database schema including meta_data JSON
- **Result**: Action Price signals now save correctly to DB and send formatted HTML messages to Telegram with full data

## Telegram HTML Formatting Migration (October 2025)
- **Issue**: All Telegram commands failed with "can't parse entities" errors due to Markdown parsing
- **Root Cause**: Underscores in commands like `/ap_stats` conflicted with Markdown italic syntax
- **Fix**: Replaced all `parse_mode='Markdown'` with `parse_mode='HTML'` across all Telegram bot functions
- **Commands Fixed**: /start, /help, /strategies, /performance, /stats, /ap_stats, /validate, signal formatting
- **Result**: All Telegram communication now stable using HTML formatting

## Config Method Correction (October 2025)
- **Issue**: Bot failed to start with `AttributeError: 'Config' object has no attribute 'get_dict'`
- **Fix**: Replaced non-existent `config.get_dict('action_price')` with `config.get('action_price', {})`
- **Result**: Bot initialization succeeds; Action Price Engine loads configuration correctly

## Fast Catchup Deadlock Fix (October 2025)
- **Issue**: Fast Catchup deadlocked after burst loading - ready_queue.put() blocked when analyzer task wasn't consuming
- **Root Cause**: Analyzer task started AFTER Fast Catchup, causing queue backpressure when 30+ symbols pushed to 50-item queue
- **Fix**: Reordered task creation in main.py - analyzer task now starts BEFORE _fast_catchup_phase()
- **Result**: Fast Catchup restored to 2.1s for 37 symbols (17.3 req/s), background tasks launch successfully

## Strategy & Indicator Fixes (October 2025)
- **Donchian Breakout**: Reduced lookback from 100 to 20 points, 60-day to 14-day percentiles
- **ORB Strategy**: Increased atr_multiplier from 1.1 to 1.3
- **Volume Thresholds**: Adaptive by time (0.6x night, 0.8x evening, 1.0x day) for ORB/VWAP/SwingHigh/EMA strategies
- **BB Width Enhancement**: Manual fallback calculation with min_periods=1 when ta.bbands returns incomplete DataFrame

## Scoring Transparency Enhancement (October 2025)
- **Detailed Component Breakdown**: Each signal now logs all scoring modifiers with explicit values
- **BTC Filter Enhancement**: Shows exact BTC % change and direction when penalty applies
- **Format**: Multi-line breakdown showing Base, Volume ratio, CVD direction, ΔOI %, Imbalance ratio, Funding status, and BTC filter with directional context
- **Example**: `BTC: -2.0 (BTC up 0.45% vs SHORT)` - instantly clear why penalty applied
- **Debugging**: Makes signal rejection/acceptance analysis transparent and actionable

## Strategy Execution Optimization (October 2025)
- **Candle-Based Triggering**: Strategies now run ONLY when candles close (15m/1h/4h), eliminating 93-99% redundant checks
- **TimeframeSync Gating**: _check_signals() aggregates closed timeframes; returns early if none closed
- **Selective Data Loading**: Updated timeframes propagated to _check_symbol_signals for filtered data loading
- **Resource Efficiency**: 15m saves 93%, 1h saves 98%, 4h saves 99.6% of unnecessary strategy executions
- **Multi-TF Context**: 4h data always loaded for regime detection even when only 15m/1h closes
- **Logging**: Shows "⏭️ No candles closed - skipping" until timeframe updates, then "🕯️ Candles closed: 15m - checking"

## Runtime Fast Catchup (October 2025)
- **Parallel Candle Updates**: During runtime, all symbols update candles in parallel at candle close using asyncio.gather
- **Performance**: 67 symbols updated in 0.94s (71.4 req/s) vs ~67s sequential - achieving ~70x speedup
- **Integration**: Replaces sequential update loop in _check_signals with _parallel_update_candles method
- **Failure Handling**: Returns False on failures with debug logging; strategy checks proceed with freshest available data
- **Metrics**: Logs show "⚡ Runtime Fast Catchup: X/Y updates in Zs (R req/s) | X symbols × N TFs"

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches historical data with caching.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket differential updates.
- **BinanceWebSocket**: Real-time market data streaming.
- **FastCatchupLoader**: Optimizes bot restart time by detecting and filling historical data gaps for existing symbols in parallel.
- **PeriodicGapRefill**: Continuously detects and refills data gaps during bot operation using smart scheduling and parallel loading.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries on (symbol, timeframe, timestamp)).

### Strategy Framework
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates multiple strategies across timeframes.
- **Signal Dataclass**: Standardized signal output.
- **Implemented Strategies**: 15 active strategies covering breakout, pullback, and mean reversion, with mandatory filters (ADX, ATR%, BBW, expansion block), dual confluence, BTC directional filtering, and a signal scoring threshold.
- **Action Price Strategy System**: A production-only module using S/R zones, Anchored VWAP, EMA filters, and 5 price action patterns for signal generation with dedicated performance tracking and partial profit-taking.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market into TREND/SQUEEZE/RANGE/CHOP/UNDECIDED.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for pre-computed indicators.

### Signal Scoring & Aggregation
- **Scoring Formula**: Combines base strategy score with market modifiers (volume, CVD, OI Delta, Depth Imbalance, Funding, BTC Opposition).
- **BTC Filter**: Filters noise and applies penalties for opposing BTC trends.
- **Conflict Resolution**: Score-based prioritization and direction-aware locks ensure the highest-scoring signals execute, while preventing conflicting signals for the same direction.

### Filtering & Risk Management
- **Stop Distance Validation**: Prevents excessive risk.
- **Hybrid Entry System**: Adaptive MARKET/LIMIT execution based on strategy type.
- **Risk Calculator**: Manages position sizing, stop-loss (swing extreme + ATR buffer), and take-profit (1.5-3.0 RR).
- **Time Stops**: Exits trades if no progress within a set number of bars.
- **Symbol Blocking System**: Prevents multiple signals on the same symbol while an active signal exists, persisting across restarts.

### Telegram Integration
- Provides commands for status, strategy details, performance, validation, and latency.
- Delivers Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- Dedicated `ap_stats` command for Action Price performance, including pattern breakdown and partial exit tracking.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals and calculates exit conditions using precise SL/TP levels for accurate PnL.
- Updates entry price for LIMIT orders upon fill to ensure accurate PnL calculations.
- Provides detailed metrics: Average PnL, Average Win, Average Loss.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys.
- Supports `signals_only_mode` and specific configurations for the Action Price system.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe coordination.
- **Loader Task**: Loads historical data, retries on failure, and pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols from the queue for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list based on 24h volume.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel loader/analyzer tasks, and launching the Telegram bot. Data is loaded in parallel, enabling immediate analysis. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, running strategies, scoring signals, applying filters, and sending Telegram alerts. Persistence includes storing candles/trades in SQLite and logging signals.

## Error Handling & Resilience
Includes rate limiting with exponential backoff, auto-reconnection for WebSockets, orderbook resynchronization, and graceful shutdown.

# External Dependencies

## Exchange Integration
- **Binance Futures API**: REST endpoints for market and account data.
- **Binance WebSocket**: Real-time market data streams.
- **Binance Vision**: Historical data archive.

## Third-Party Services
- **Telegram Bot API**: For message delivery.

## Python Libraries
- **Data Processing**: pandas, numpy, pandas-ta.
- **Network**: aiohttp, websockets.
- **Database**: SQLAlchemy, Alembic.
- **Exchange**: python-binance, ccxt.
- **Scheduling**: APScheduler.
- **Configuration**: pyyaml, python-dotenv.