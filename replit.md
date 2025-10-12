# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories, providing real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading with fast catchup and periodic gap refill, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/SQUEEZE/RANGE/CHOP), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms.

A fully integrated **Action Price** strategy system is included, operating independently to identify high-probability setups using Support/Resistance zones, Anchored VWAP, EMA trend filters, and 5 classic price action patterns (Pin-Bar, Engulfing, Inside-Bar, Fakey, PPR) with partial profit-taking capabilities.

# Recent Changes

## Independent Symbol Blocking for Main & Action Price (October 12, 2025)
- **Feature**: Раздельные блокировки символов для независимой работы систем
- **Logic**:
  - Main Strategies: `symbols_blocked_main` - блокирует символы только для основных стратегий
  - Action Price: `symbols_blocked_action_price` - блокирует символы только для Action Price
  - Обе системы могут одновременно иметь активные сигналы на одном символе!
- **Example**:
  ```
  BTCUSDT:
    - Action Price SHORT активен → заблокирован только для AP
    - Main Strategies может дать LONG → оба сигнала активны одновременно
  
  Закрытие:
    - Main LONG закрылся → разблокирован только для Main
    - AP SHORT всё ещё активен → заблокирован для AP
  ```
- **Components**:
  - `_block_symbol_main()` / `_unblock_symbol_main()` - управление блокировками Main
  - `_block_symbol_action_price()` / `_unblock_symbol_action_price()` - управление блокировками AP
  - Раздельные callbacks в performance trackers для правильной разблокировки
- **Benefits**:
  - Максимальное использование торговых возможностей
  - Обе системы работают независимо без конфликтов
  - Одна монета может иметь 2 сигнала одновременно (Main + AP)
- **Status**: ✅ Production-ready, полная независимость систем

## Stablecoin Filter (October 12, 2025)
- **Feature**: Automatic exclusion of stablecoins from analysis
- **Reason**: Stablecoins (USDCUSDT, BUSDUSDT, etc.) have zero volatility, making them unsuitable for trading
- **Excluded symbols**: USDCUSDT, BUSDUSDT, TUSDUSDT, USDPUSDT, FDUSDUSDT, DAIUSDT, EURUSDT
- **Configuration**: `universe.exclude_stablecoins: true` in config.yaml (enabled by default)
- **Impact**: Prevents false signals on pegged assets with hundreds of zone touches but micro-movements
- **Status**: ✅ Production-ready, applies to both main strategies and Action Price

## Rate Limit Optimization (October 12, 2025)
- **Issue**: With 300 symbols, bot was hitting Binance API limits (2,400 weight/minute)
- **Solution**: Reduced parallelism to prevent rate limit violations
  - `fast_catchup.max_parallel: 2` (was auto 4-12) → ~50% API load
  - `periodic_gap_refill.max_parallel: 3` (was 8) → ~75% API load
  - Combined load: ~94% of limit (safe margin for bursts)
- **Results**: 
  - Fast catchup: 1,200 weight/min (50% limit)
  - Periodic refill: 1,800 weight/min (75% limit)
  - Auto-refill: 450 weight/min (19% limit)
- **Status**: ✅ Production-ready, tested with 300 symbols on mainnet API

## Trailing Stop-Loss with Partial TP (October 12, 2025)
- **Feature**: Implemented trailing stop-loss system with partial profit taking
- **Logic**:
  - TP1 hit → Move SL to breakeven, continue tracking
  - After TP1: TP2 → Close with full TP2 profit
  - After TP1: Breakeven → Close with 0% (breakeven)
- **PnL Calculation**: Real percentages from entry price
  - LONG TP: (exit - entry) / entry * 100 → positive %
  - SHORT TP: (entry - exit) / entry * 100 → positive %
  - LONG SL: (sl - entry) / entry * 100 → negative %
  - SHORT SL: (entry - sl) / entry * 100 → negative %
- **Components Added**:
  - Database fields: `tp1_hit`, `tp1_closed_at`, `exit_type`
  - TP1/TP2 counters in Telegram statistics
  - Migration script: `migrate_add_tp_fields.py` for safe DB update
- **Status**: ✅ Production-ready, percentage-based PnL with identical logic in live/historical tracking

## Signal Tracker Backfill Fix (October 12, 2025)
- **Fixed**: Corrected Candle model field references in backfill mechanism from `kline.timestamp` to `kline.open_time`
- **Impact**: Backfill now successfully closes signals missed during bot downtime using historical candle data
- **Testing**: Verified with 18/33 signals closed on startup without errors
- **Components Updated**: 
  - `src/utils/signal_tracker.py`: All 6 instances of `kline.timestamp` replaced with `kline.open_time` in backfill logic
  - Query filters and `signal.closed_at` assignments now use correct field name
- **Status**: ✅ Production-ready, zero AttributeError exceptions

## Auto-Refill Data Integrity System (October 12, 2025)
- **Feature**: Automatic data gap detection and refill when data completeness drops below 99%
- **Logic**:
  - When data integrity check detects <99% completeness → auto_refill_incomplete_data() triggered
  - Scans all timeframes (15m, 1h, 4h, 1d) for missing candles across 90-day period
  - Uses validate_candles_continuity() to detect exact gap locations
  - Refills ONLY missing candles (not entire 90 days) via auto_fix_gaps()
  - **Silent Mode for New Coins**: Alerts sent ONLY if symbol age >= 90 days (old coins with real problems)
- **New Coin Detection**:
  - `_get_symbol_age_days()` determines coin age from first available candle
  - Young coins (< 90 days) have expected incomplete data → **no alerts sent**
  - Old coins (>= 90 days) with <99% data → **alert sent** (real data integrity issue)
  - Examples:
    - LYNUSDT (10 days old, 11% data) → 🔇 Silent (expected)
    - BTCUSDT (1500 days old, 95% data) → 🔔 Alert (problem!)
- **Configuration**: 
  - `data_integrity.auto_refill_on_incomplete: true` (enabled by default in config.yaml)
  - Can be disabled to receive alerts without auto-refill
- **Components**:
  - New method: `DataLoader.auto_refill_incomplete_data()` for smart gap detection and refill
  - New method: `DataLoader._get_symbol_age_days()` for coin age detection
  - Integrated into `load_warm_up_data()` with configurable enable/disable
  - Works alongside existing PeriodicGapRefill for comprehensive data coverage
- **Benefits**:
  - Zero manual intervention - gaps fixed automatically
  - Efficient: downloads only missing candles, not full history
  - No false alerts from newly listed coins
  - Database integrity maintained with duplicate prevention
  - Chronological insertion ensures seamless data continuity
- **Status**: ✅ Production-ready, smart age-based alerting prevents false positives

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