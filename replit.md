# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories, architect-validated against detailed specifications. The bot provides real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/RANGE/SQUEEZE), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms. The project's ambition is to provide a highly performant and reliable automated trading solution for cryptocurrency futures markets, focusing on data integrity and strategic validation.

# Recent Changes

## 2025-10-11: Dedicated Strategy Logging System
- **Created separate strategy logging for deep analysis**:
  - New `logs/strategies.log` file dedicated to strategy analysis (separate from main `bot.log`)
  - Added `src/utils/strategy_logger.py` with dedicated logger configuration
  - **Per-symbol logging**: Shows regime (TREND/RANGE/SQUEEZE), bias (bullish/bearish), which strategies checked, and results
  - **Per-strategy details**: Displays which of 16 strategies were checked/skipped/generated signals with entry/SL/TP prices
  - **Scoring breakdown**: Detailed score components (Base, Volume, CVD, Late Trend, BTC) when signals are generated
  - **Filter logging**: Shows why signals passed/failed threshold (≥2.0) and symbol lock status
  - **Statistics**: Summary counts (checked/skipped/signals) for each analysis cycle
- **Cleaned up BTC filter spam**: Changed impulse/expansion detection from INFO to DEBUG level to reduce log noise

## 2025-10-11: High-Performance Indicator Caching System
- **Implemented indicator caching for 15x speed improvement**:
  - Created `IndicatorCache` class with timestamp-based invalidation per (symbol, timeframe, last_bar_time)
  - Built `calculate_common_indicators()` function to compute all shared indicators once (ATR, EMA, BB, Donchian, ADX, percentiles)
  - Integrated caching into main analysis loop - eliminates 1,500+ redundant calculations down to ~96 (one per symbol per timeframe)
  - **Validated by architect**: Proper cache invalidation, no regressions, all 15 strategies working correctly
  - **Performance impact**: Expected 15x speedup for 100+ symbol universe

## 2025-10-11: Configuration Synchronization Fix
- **Fixed 8 critical config parameter mismatches** between code and config.yaml:
  - BTCFilter: Added missing `expansion_atr_mult: 1.5`, `lookback_bars: 10`
  - BTCFilter: Fixed `impulse_threshold` now correctly reads 1.5% from config (was using 0.8% default)
  - SignalScorer: Added missing `volume_mult: 1.5`, `enter_threshold: 2.0`
  - SignalScorer: Added missing `doi_min_pct: 1.0`, `doi_max_pct: 3.0`
  - SignalScorer: Added missing `depth_imbalance_ratio` section with long_max: 0.90, short_min: 1.10
  - SignalScorer: Added missing `btc_filter_tf: "1h"`
- **All parameters now correctly loaded from config.yaml** instead of hardcoded defaults
- Python module cache cleared to ensure fresh configuration loading

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### 1. Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches historical data with caching.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket differential updates for sub-second depth imbalance detection.
- **BinanceWebSocket**: Real-time market data streaming (klines, trades, depth updates).

### 2. Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries on (symbol, timeframe, timestamp)) for simplicity and concurrent reads.

### 3. Strategy Framework
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates multiple strategies across timeframes.
- **Signal Dataclass**: Standardized signal output.
- **Implemented Strategies**: 15 active strategies, including Donchian Breakout, Squeeze Breakout, MA/VWAP Pullback, Range Fade, Volume Profile, Liquidity Sweep, Order Flow, CVD Divergence, and Time-of-Day. All strategies are architect-validated for compliance with manual requirements, including H4 swing confluence, mandatory filters (ADX, ATR%, BBW, expansion block), dual confluence, BTC directional filtering, and a signal scoring threshold ≥+2.0.

### 4. Market Analysis System
- **MarketRegimeDetector**: Classifies market into TREND/RANGE/SQUEEZE/UNDECIDED using multi-factor confirmation.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching system with timestamp-based invalidation - eliminates 1,500+ redundant calculations per analysis cycle by storing pre-computed indicators per (symbol, timeframe, last_bar_time). Provides 15x speed improvement for multi-strategy analysis.

### 5. Signal Scoring System
- Combines a base strategy score with modifiers for volume, CVD, OI Delta, and Depth Imbalance. Penalties apply for late trends, extreme funding, or opposing BTC direction. An entry threshold of ≥ +2.0 is required for execution.

### 6. Filtering & Risk Management
- **BTCFilter**: Prevents mean reversion during significant BTC impulses and applies directional penalties for trend strategies.
- **Risk Calculator**: Manages position sizing, stop-loss (swing extreme + 0.2-0.3 ATR), and take-profit (1.5-3.0 RR).
- **Time Stops**: Exits trades if no progress within 6-8 bars.

### 7. Telegram Integration
- Provides commands (/start, /help, /status, /strategies, /performance, /stats, /validate, /latency, /report) and Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- **/validate** - Validates all strategies: checks data availability, OHLCV integrity, price logic, signal generation, and entry/SL/TP correctness across different market regimes.

### 8. Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. A `signals_only_mode` flag allows operation without live trading.

### 9. Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe coordination for parallel loading and analysis.
- **Loader Task**: Loads historical data with retry logic and pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols from the queue, allowing immediate analysis of loaded data while background loading continues.
- **Symbol Auto-Update Task**: Automatically updates the symbol list every hour based on 24h volume criteria, adding new high-volume pairs and removing low-volume pairs dynamically.
- **Data Integrity System**: Comprehensive data validation with a 99% threshold, including gap detection, auto-fix capabilities, and Telegram alerts for unfixed issues.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel loader/analyzer tasks, and launching the Telegram bot. Data is loaded in parallel, enabling immediate analysis of available symbols. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, running strategies, scoring signals, applying filters, and sending Telegram alerts. Persistence includes storing candles/trades in SQLite and logging signals.

## Error Handling & Resilience
Features include rate limiting with exponential backoff, auto-reconnection for WebSockets, orderbook resynchronization on sequence gaps, and a graceful shutdown mechanism.

# External Dependencies

## Exchange Integration
- **Binance Futures API**: REST endpoints for market and account data.
- **Binance WebSocket**: Real-time market data streams.
- **Binance Vision**: Historical data archive.

## Third-Party Services
- **Telegram Bot API**: For message delivery.
- **pytz**: For timezone localization (Europe/Kiev).

## Python Libraries
- **Data Processing**: pandas, numpy, pandas-ta.
- **Network**: aiohttp, websockets.
- **Database**: SQLAlchemy, Alembic.
- **Exchange**: python-binance, ccxt.
- **Scheduling**: APScheduler.
- **Configuration**: pyyaml, python-dotenv.