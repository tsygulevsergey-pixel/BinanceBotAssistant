# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories, providing real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading with fast catchup and periodic gap refill, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/SQUEEZE/RANGE/CHOP), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms.

A fully integrated **Action Price** strategy system is included, operating independently to identify high-probability setups using Support/Resistance zones, Anchored VWAP, EMA trend filters, and 5 classic price action patterns (Pin-Bar, Engulfing, Inside-Bar, Fakey, PPR) with partial profit-taking capabilities.

# Recent Changes

## Trailing Stop-Loss with Partial TP (October 12, 2025)
- **Feature**: Implemented trailing stop-loss system with partial profit taking
- **Logic**:
  - TP1 hit → Close 50%, move SL to breakeven, record +0.5R
  - After TP1: TP2 → Close remaining 50% with +1.5R total (0.5R + 1R)
  - After TP1: Breakeven → Close remaining 50% with +0.5R total
- **Components Added**:
  - Database fields: `tp1_hit`, `tp1_closed_at`, `exit_type`
  - R-based PnL calculation (0.5R, 1.5R, -1.0R instead of percentages)
  - TP1/TP2 counters in Telegram statistics
- **Status**: ✅ Production-ready, both live tracking and historical backfill use identical trailing logic

## Signal Tracker Backfill Fix (October 12, 2025)
- **Fixed**: Corrected Candle model field references in backfill mechanism from `kline.timestamp` to `kline.open_time`
- **Impact**: Backfill now successfully closes signals missed during bot downtime using historical candle data
- **Testing**: Verified with 18/33 signals closed on startup without errors
- **Components Updated**: 
  - `src/utils/signal_tracker.py`: All 6 instances of `kline.timestamp` replaced with `kline.open_time` in backfill logic
  - Query filters and `signal.closed_at` assignments now use correct field name
- **Status**: ✅ Production-ready, zero AttributeError exceptions

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
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement using Support/Resistance zones with intelligent fallback:
  - Detects swing highs/lows from last 20 candles using fractal pattern (3-bar extreme)
  - Creates S/R zones with ATR-based buffers (0.25 ATR)
  - Places stops behind nearest zone in direction (zone boundary ± 0.1 ATR)
  - **Smart Distance Guard**: Ignores zones >5 ATR away (protects from extreme impulses)
  - **Fallback Logic**: If no valid zone found → uses 2 ATR from entry
  - Fixed take-profits: TP1 at 1R, TP2 at 2R (where R = |Entry - Stop|)
- **Stop Distance Validation**: Prevents excessive risk.
- **Hybrid Entry System**: Adaptive MARKET/LIMIT execution based on strategy type.
- **Time Stops**: Exits trades if no progress within a set number of bars.
- **Symbol Blocking System**: Prevents multiple signals on the same symbol while an active signal exists, persisting across restarts.

### Telegram Integration
- Provides commands for status, strategy details, performance, validation, and latency.
- Delivers Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- Dedicated `ap_stats` command for Action Price performance, including pattern breakdown and partial exit tracking.

### Logging System
- **Main Bot**: Creates new log file on each startup: `bot_{timestamp}.log`
- **Action Price**: Creates separate log file on each startup: `action_price_{timestamp}.log`
- Timezone: Europe/Kyiv (EEST/EET)
- Location: `logs/` directory

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