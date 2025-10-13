# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories, providing real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading with fast catchup and periodic gap refill, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/SQUEEZE/RANGE/CHOP), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms.

A fully integrated **Action Price** strategy system is included, operating independently to identify high-probability setups using Support/Resistance zones, Anchored VWAP, EMA trend filters, and 5 classic price action patterns (Pin-Bar, Engulfing, Inside-Bar, Fakey, PPR) with partial profit-taking capabilities.

# Recent Changes

## October 13, 2025 - Smart Rate Limiting (90% Threshold) + Startup Protection
**Problem Resolved**: Bot was hitting Binance API rate limits (429 errors) on startup and during burst catchup, causing crashes and failed data loads.

**Solution Implemented**:
1. **90% Safety Threshold**: Rate limiter now stops at 990/1100 requests (90%) instead of waiting for 429 errors
2. **Intelligent Pausing**: Burst catchup and gap refill automatically pause when approaching limit, wait for reset, then continue
3. **Batch Protection**: Each request checks limit status before execution, preventing rate limit violations
4. **ExchangeInfo Caching**: Precision data cached to file for 1 hour, eliminating redundant API calls on restarts
5. **Startup Delay**: 30-second delay on first startup (only if cache missing) to allow rate limits to reset from previous runs

**Impact**: Bot can now safely load 270+ symbols without hitting rate limits. Repeated restarts use cache and start instantly without API requests.

## October 12, 2025 - Critical Fix: Main Strategies Execution
**Problem Resolved**: Main strategies were blocked and never executing due to `_check_signals()` blocking the main loop for 100+ seconds, causing candle close window misses.

**Solution Implemented**:
1. **Async Non-Blocking Execution**: Refactored `_check_signals()` to use `asyncio.create_task()` with Lock protection, preventing main loop blocking while ensuring single execution
2. **Timestamp-Based Candle Detection**: Rewrote `TimeframeSync` to use floor timestamp tracking instead of strict wall-clock windows, enabling reliable detection even when checks are delayed
3. **Runtime Monitoring**: Added execution time logging for performance tracking and regression detection

**Impact**: All 16 main strategies now successfully execute on candle closes, with confirmed market analysis, regime detection, and filter application.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches historical data with caching, including FastCatchupLoader and PeriodicGapRefill for efficient data management.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket differential updates.
- **BinanceWebSocket**: Real-time market data streaming.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries on (symbol, timeframe, timestamp)).

### Strategy Framework
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates multiple strategies across timeframes.
- **Signal Dataclass**: Standardized signal output.
- **Implemented Strategies**: 15 active strategies covering breakout, pullback, and mean reversion, with mandatory filters (ADX, ATR%, BBW, expansion block), dual confluence, BTC directional filtering, and a signal scoring threshold.
- **Action Price Strategy System**: A production-only module using S/R zones, Anchored VWAP, EMA filters, and 5 price action patterns for signal generation with dedicated performance tracking and partial profit-taking. This system includes an advanced Zone Strength System, Proximity Formalization, EMA Pullback Exception, and Pattern Quality System.

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
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement using Support/Resistance zones with intelligent fallback and smart distance guard. Fixed take-profits: TP1 at 1R, TP2 at 2R.
- **Trailing Stop-Loss with Partial TP**: Implemented for advanced profit management.
- **Stop Distance Validation**: Prevents excessive risk.
- **Hybrid Entry System**: Adaptive MARKET/LIMIT execution based on strategy type.
- **Time Stops**: Exits trades if no progress within a set number of bars.
- **Symbol Blocking System**: Prevents multiple signals on the same symbol, with independent blocking for main strategies and Action Price. Automatically excludes stablecoins from analysis.

### Telegram Integration
- Provides commands for status, strategy details, performance, validation, and latency.
- Delivers Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- `/performance` - unified statistics for main strategies (Total signals, Win Rate, TP1/TP2 counts, Average PnL)
- `/ap_stats` - unified statistics for Action Price (same format as /performance, tracking TP1/TP2 partial exits)

### Logging System
- Separate log files for Main Bot and Action Price, located in the `logs/` directory, using Europe/Kyiv timezone.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, calculates exit conditions using precise SL/TP levels, and updates entry prices for accurate PnL. Provides detailed metrics: Average PnL, Average Win, Average Loss.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and specific configurations for the Action Price system.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe coordination.
- **Loader Task**: Loads historical data, retries on failure, and pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols from the queue for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list based on 24h volume.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts, including smart age-based alerting for new coins.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel loader/analyzer tasks, and launching the Telegram bot. Data is loaded in parallel, enabling immediate analysis. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, running strategies, scoring signals, applying filters, and sending Telegram alerts. Persistence includes storing candles/trades in SQLite and logging signals.

## Error Handling & Resilience
- **Smart Rate Limiting**: 90% safety threshold (990/1100 requests/min) prevents API bans. Automatic pause and resume when approaching limit.
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