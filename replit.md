# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for institutional trading principles. It employs a focused approach with 5 core strategies, operating in both Signals-Only Mode for signal generation and Live Trading Mode for full trading capabilities.

The bot prioritizes quality over quantity with proven strategies, incorporates market regime detection, structure-based stop-loss/take-profit, signal confluence, and multi-timeframe analysis. Key features include a local orderbook, historical data, advanced scoring, and comprehensive performance tracking. The "Action Price" system independently operates with S/R zones, Anchored VWAP, and price action patterns, aiming for an 80%+ Win Rate and a Profit Factor of 1.8-2.5.

# User Preferences

Preferred communication style: Simple, everyday language.

# Recent Changes

## Telegram Closed Signals Commands (October 15, 2025)
- **New Commands**: Added `/closed` and `/closed_ap` to show detailed list of closed signals
- **Features**:
  - `/closed [hours]` - Shows closed signals from main strategies (default 24h, max 20 signals)
  - `/closed_ap [hours]` - Shows closed Action Price signals (default 24h, max 20 signals)
  - Displays: Symbol, Direction (🟢/🔴), Exit Type (TP1/TP2/SL/BE/TIME_STOP), PnL%, Strategy/Pattern
  - Sorted by closed_at DESC (newest first)
  - Custom time range: `/closed 48` shows last 48 hours
- **Implementation**: Direct database queries to `signals` and `action_price_signals` tables
- **Files**: `src/telegram/bot.py` (lines 259-383, 40-41, 85-86, 108-109)

## Action Price Performance Tracker Statistics Fix (October 15, 2025)
- **Problem**: Statistics showed both TP1 and TP2 for same signal (e.g., signal hits TP2 → both counters +1)
- **Root Cause**: Used `partial_exit_1_at/partial_exit_2_at` flags instead of `exit_reason` for counting
- **Solution**: Changed to count by `exit_reason` - mutually exclusive categories:
  - `exit_reason = 'TAKE_PROFIT_1'` → TP1 counter
  - `exit_reason = 'TAKE_PROFIT_2'` → TP2 counter
  - `exit_reason = 'BREAKEVEN'` → Breakeven counter
- **Result**: Correct statistics - if TP2 hit, shows only TP2 (not both TP1+TP2)
- **Files**: `src/action_price/performance_tracker.py` (lines 465-467)

## Action Price Performance Tracker Fix v4 (October 15, 2025)
- **Problem**: Tracker works but shows wrong PnL for TP2 exits (e.g., -0.82% instead of profit)
- **Root Causes**: 
  1. Tracker used wrong logger (invisible in action_price logs) ✅ FIXED
  2. Timezone errors in time stop logic ✅ FIXED
  3. VWAP RuntimeWarning from pandas Timestamp/int ✅ FIXED
  4. Direction case mismatch in exit conditions: DB stores 'long'/'short' but code checks 'LONG'/'SHORT' ✅ FIXED
  5. Silent condition failures: No debug logs ✅ FIXED
  6. ZeroDivisionError after TP1: When SL moves to breakeven (SL=Entry), risk_r=0 → crash in MFE/MAE calc ✅ FIXED
  7. **PnL calculation bug**: Forgot `.upper()` in `_calculate_total_pnl()` → used wrong formula ✅ FIXED
- **Solution v4**: 
  - **Logger Fix**: Tracker uses ap_logger (visible in action_price logs)
  - **Timezone Fix**: Auto-localize naive datetime before comparison
  - **VWAP Fix**: Use numpy arrays instead of pandas Series
  - **Direction Fix**: Convert to uppercase with `.upper()` in ALL functions (_check_exit_conditions, _update_mfe_mae, _calculate_total_pnl)
  - **Debug Logs**: Added PnL calculation breakdown (TP1 30% + Remainder 70% = Total)
  - **Breakeven Protection**: Skip MFE/MAE update when risk_r < 0.0001 (prevents division by zero)
- **Result**: ✅ WORKING - Tracker closes signals correctly with accurate PnL calculations
- **Files**: `src/action_price/performance_tracker.py`, `src/indicators/vwap.py`

## Action Price Candle Selection Fix (October 15, 2025)
- **Problem**: Bot analyzed wrong candles (-3, -2) instead of last 2 closed (-2, -1), causing EMA200 mismatch with Binance
- **Root Cause**: Hardcoded indices used -3/-2 instead of -2/-1 for initiator/confirmation
- **Additional Issues**: 
  - Timestamp in JSONL always showed "1970-01-01" (used DataFrame index instead of open_time column)
  - EMA200 values didn't match Binance because wrong candles were analyzed
- **Solution**: 
  - Changed to analyze last 2 closed candles: initiator=-2, confirmation=-1
  - Fixed timestamp to use `open_time` column instead of DataFrame index
- **Result**: Now analyzes correct candles with proper timestamps in logs
- **Files**: `src/action_price/engine.py` (lines 260-275, 700-709)

## Price Precision Fix for Action Price (October 15, 2025)
- **Problem**: Action Price signals showed rounded prices (0.0075 vs actual 0.0075281) - not matching Binance precision
- **Root Cause**: Telegram message formatting used fixed `.4f` format instead of Binance symbol precision
- **Solution**: Use `BinanceClient.format_price()` method which applies correct symbol-specific precision from exchange_info
- **Result**: Prices in signals now match Binance exactly (same decimal length)
- **Files**: `main.py` (lines 1401-1421)

## Semaphore Control for Parallel Updates (October 15, 2025)
- **Problem**: IP ban at 02:01:00 when 15m+1h candles closed - 580 tasks launched simultaneously via `asyncio.gather()` without limits
- **Root Cause**: `_parallel_update_candles()` created massive concurrent request queue (2700 weights vs 2400 limit)
- **Solution**: Added `asyncio.Semaphore(50)` to limit max 50 parallel tasks at once
- **Result**: Controlled request flow, prevents mass bursts at 00:00/02:00 when multiple timeframes close
- **Files**: `main.py` (lines 405-417)

## API Weight Calculation Fix (October 15, 2025)
- **Problem**: IP bans due to incorrect API weight calculations - RateLimiter underestimated request weights by 5-10x
- **Root Cause**: `get_klines()` and `get_depth()` used wrong weight boundaries (e.g., "1-100=1" instead of "1-99=1")
- **Solution**: Corrected weight formulas to match official Binance Futures API documentation:
  - **klines**: 1-99=1, 100-499=2, 500-1000=5, >1000=10
  - **depth**: 1-100=2, 101-500=5, 501-1000=10, 1001-5000=50
- **Result**: No IP bans, rate limiter syncing with ±60-130 diff (normal range), verified with 60s production test
- **Files**: `src/binance/client.py` (lines 207-216, 241-250)

## VWAP RuntimeWarning Fix (October 15, 2025)
- **Fixed**: RuntimeWarning in VWAP calculations ("'<' not supported between instances of 'Timestamp' and 'int'")
- **Solution**: Added `pd.to_numeric()` conversion and explicit `.astype(float)` in `calculate_vwap_bands()` method
- **Result**: Clean execution, no warnings in production logs

## Data Stabilization Fix (October 14, 2025)
- **31-Second Delay**: Added 31-second delay after ANY candle close (15m/1h/4h/1d) before loading data from Binance
- **Problem Solved**: Bot was requesting data 6 seconds after candle close, receiving unstable/temporary prices that Binance updates 10-30 seconds later
- **Timeframe Coverage**: All four timeframes (15m/1h/4h/1d) properly detected and delayed
- **Timer Behavior**: TimeframeSync checks candle closes by real time BEFORE delay executes, maintaining accurate schedule (00:15/00:30/00:45/00:00)
- **Design**: Single consolidated delay per check cycle (efficient)

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches historical data with caching, fast catchup, and periodic gap refill.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket differential updates.
- **BinanceWebSocket**: Real-time market data streaming.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries on (symbol, timeframe, timestamp)).

### Strategy Framework
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates strategies with regime-based selection.
- **Signal Dataclass**: Standardized signal output with confluence tracking.
- **5 CORE STRATEGIES**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile.
- **Action Price System**: Rewritten on EMA200 Body Cross logic with an 11-component scoring system for STANDARD, SCALP, and SKIP regimes. Includes JSONL logging for ML analysis and real-time MFE/MAE tracking.
  - **Event-Driven Execution**: Runs AFTER 15m candles are loaded and saved (not timer-based). Supports partial loading - analyzes only symbols with successfully updated candles.
  - **31-Second Delay**: Waits 31 seconds after ANY candle close (15m/1h/4h/1d) for Binance to finalize data (prevents analyzing unstable/temporary prices).
  - **Entry Price**: Uses close price of confirming candle (not mark price).
  - **TP Calculation**: TP1 = Entry ± R, TP2 = Entry ± 2R where R = |Entry - SL|.
  - **Telegram Signals**: 🟢 for LONG, 🔴 for SHORT.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market into TREND/SQUEEZE/RANGE/CHOP/UNDECIDED.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for pre-computed indicators.

### Signal Scoring & Aggregation
- **Scoring Formula**: Combines base strategy score with market modifiers.
- **BTC Filter**: Filters noise and applies penalties for opposing BTC trends.
- **Conflict Resolution**: Score-based prioritization and direction-aware locks.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement with intelligent fallback and smart distance guard.
- **Trailing Stop-Loss with Partial TP**: For advanced profit management (30% @ TP1, 40% @ TP2, 30% trailing).
- **Hybrid Entry System**: Adaptive MARKET/LIMIT execution.
- **Time Stops**: Exits trades if no progress.
- **Symbol Blocking System (Per-Strategy)**: Independent blocking per strategy allows multiple strategies on the same symbol.

### Telegram Integration
- Provides commands for status, strategy details, performance, validation, and latency.
- Delivers Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- Unified `/performance` and `/ap_stats` commands for statistics.

### Logging System
- Separate log files for Main Bot and Action Price in `logs/` directory, using Europe/Kyiv timezone.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, calculates exit conditions, and updates PnL.
- **ActionPricePerformanceTracker**: Tracks Action Price signals with partial exits, breakeven logic, TP1/TP2 tracking, MFE/MAE tracking, and detailed JSONL logging.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and `enabled: true/false` flags for strategies.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe coordination.
- **Loader Task**: Loads historical data, retries on failure, and pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols from the queue for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list based on 24h volume.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel loader/analyzer tasks, and launching the Telegram bot. Data is loaded in parallel, enabling immediate analysis. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, running strategies, scoring signals, applying filters, and sending Telegram alerts. Persistence includes storing candles/trades in SQLite and logging signals.

## Error Handling & Resilience
- **Smart Rate Limiting**: 55% safety threshold (1320/2400) with 1080 requests buffer to compensate ±430 sync error. Prevents API bans.
- **IP BAN Prevention v4**: Event-based coordination with single-log notification (no duplicate spam). All pending requests blocked immediately via ip_ban_event flag.
- **Periodic Gap Refill with Request Weight Calculator**: 
  - Pre-calculates total requests needed before execution
  - Respects 55% threshold with available capacity check
  - MIN_BATCH_SIZE: 50 requests minimum to start
  - FIFO ordering: First detected gaps sent first
  - Single batch: If total ≤ capacity, sends all at once
  - Multi-batch with wait: If total > capacity, splits and waits 60s for rate reset
  - Safety mini-batches: 20 symbols per mini-batch with 1s pause
  - Startup delay: Disabled first 15 minutes after bot start
  - Pre-check: Only runs if rate usage < 30%
- **Burst Catchup Safety**: Rate usage checked after each batch (20 symbols), extra 2s pause if > 50%.
- **Action Price TP2 Fix**: None check before float() conversion for SCALP/SKIP modes.
- **Exponential Backoff**: Retry logic with progressive delays for transient errors.
- **Auto-Reconnection**: WebSocket auto-reconnect with orderbook resynchronization.
- **Graceful Shutdown**: Clean resource cleanup and state persistence.

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