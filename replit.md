# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for institutional trading principles. It employs a focused approach with 5 core strategies, operating in both Signals-Only Mode for signal generation and Live Trading Mode for full trading capabilities.

The bot prioritizes quality over quantity with proven strategies, incorporates market regime detection, structure-based stop-loss/take-profit, signal confluence, and multi-timeframe analysis. Key features include a local orderbook, historical data, advanced scoring, and comprehensive performance tracking. The "Action Price" system independently operates with S/R zones, Anchored VWAP, and price action patterns, aiming for an 80%+ Win Rate and a Profit Factor of 1.8-2.5.

# User Preferences

Preferred communication style: Simple, everyday language.

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