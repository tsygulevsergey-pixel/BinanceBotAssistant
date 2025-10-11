# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories, architect-validated against detailed specifications. The bot provides real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/SQUEEZE/RANGE/CHOP), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms. The project's ambition is to provide a highly performant and reliable automated trading solution for cryptocurrency futures markets, focusing on data integrity and strategic validation.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches historical data with caching.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket differential updates for sub-second depth imbalance detection.
- **BinanceWebSocket**: Real-time market data streaming (klines, trades, depth updates).

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries on (symbol, timeframe, timestamp)) for simplicity and concurrent reads.

### Strategy Framework
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates multiple strategies across timeframes.
- **Signal Dataclass**: Standardized signal output.
- **Implemented Strategies**: 15 active strategies, including Donchian Breakout, Squeeze Breakout, MA/VWAP Pullback, Range Fade, Volume Profile, Liquidity Sweep, Order Flow, CVD Divergence, and Time-of-Day. All strategies are architect-validated for compliance with manual requirements, including H4 swing confluence, mandatory filters (ADX, ATR%, BBW, expansion block), dual confluence, BTC directional filtering, and a signal scoring threshold ≥+2.0.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market into TREND/SQUEEZE/RANGE/CHOP/UNDECIDED using multi-factor confirmation with priority-based detection (TREND → SQUEEZE → RANGE/CHOP). Uses percent-normalized EMA slopes (0.05% threshold) to distinguish RANGE (flat EMA) from CHOP (erratic EMA), ensuring accurate detection across all price ranges.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching system with timestamp-based invalidation - eliminates 1,500+ redundant calculations per analysis cycle by storing pre-computed indicators per (symbol, timeframe, last_bar_time). Provides 15x speed improvement for multi-strategy analysis.

### Signal Scoring System
- **Scoring Formula**: Base strategy score (1-3) + volume modifier (+1) + CVD alignment (+1) + OI Delta (+1) + Depth Imbalance (+1) - Funding Extreme (-1) - BTC Opposition (-2)
- **BTC Filter**: Uses 3-bar (2-hour) lookback on H1 with 0.3% threshold to filter noise - applies -2 penalty only for real BTC trends opposing signal direction
- **Entry Threshold**: Signals require final_score ≥ +2.0 for execution
- **Late Trend Removed**: Previous late_trend penalty (based on 4H timeframe) removed as it created false negatives on lower timeframes. Other filters (ADX, BBW, expansion block) provide sufficient protection.

### Signal Aggregation & Conflict Resolution
- **Score-Based Prioritization**: All signals are scored first, then sorted by final_score (descending) before processing. This ensures the highest quality signal is selected.
- **Direction-Aware Locks**: Lock key format `signal_lock:{symbol}:{direction}` allows simultaneous LONG and SHORT signals for the same symbol (different strategies/approaches).
- **Best Signal Selection**: For each direction, the highest-scoring signal acquires the lock; subsequent lower-scoring signals are rejected.
- **Threshold Gating**: Only signals with final_score ≥ 2.0 proceed to lock acquisition. Sub-threshold signals are immediately discarded.
- **Conflict Policy**: 
  - Multiple LONG signals → Best score wins
  - Multiple SHORT signals → Best score wins
  - LONG + SHORT signals → Both can execute (independent locks)
- **Lock TTL**: Redis/SQLite locks expire after configurable TTL (default 3600s) to prevent stale locks.

### Filtering & Risk Management
- **BTCFilter**: Prevents mean reversion during significant BTC impulses and applies directional penalties for trend strategies.
- **Risk Calculator**: Manages position sizing, stop-loss (swing extreme + 0.2-0.3 ATR), and take-profit (1.5-3.0 RR).
- **Time Stops**: Exits trades if no progress within 6-8 bars.

### Telegram Integration
- Provides commands (/start, /help, /status, /strategies, /performance, /stats, /validate, /latency, /report) and Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- **/validate** - Validates all strategies: checks data availability, OHLCV integrity, price logic, signal generation, and entry/SL/TP correctness across different market regimes.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. A `signals_only_mode` flag allows operation without live trading.

### Parallel Data Loading Architecture
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