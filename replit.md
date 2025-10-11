# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories. The bot provides real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/SQUEEZE/RANGE/CHOP), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms. The project's ambition is to provide a highly performant and reliable automated trading solution for cryptocurrency futures markets, focusing on data integrity and strategic validation.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches historical data with caching.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket differential updates.
- **BinanceWebSocket**: Real-time market data streaming.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries on (symbol, timeframe, timestamp)).

### Strategy Framework
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates multiple strategies across timeframes.
- **Signal Dataclass**: Standardized signal output.
- **Implemented Strategies**: 15 active strategies, including Donchian Breakout, Squeeze Breakout, MA/VWAP Pullback, Range Fade, Volume Profile, Liquidity Sweep, Order Flow, CVD Divergence, and Time-of-Day. All strategies include mandatory filters (ADX, ATR%, BBW, expansion block), dual confluence, BTC directional filtering, and a signal scoring threshold.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market into TREND/SQUEEZE/RANGE/CHOP/UNDECIDED using multi-factor confirmation and priority-based detection.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching system with timestamp-based invalidation for pre-computed indicators.

### Signal Scoring System
- **Scoring Formula**: Base strategy score + volume modifier + CVD alignment + OI Delta + Depth Imbalance - Funding Extreme - BTC Opposition.
- **BTC Filter**: Uses 3-bar (2-hour) lookback on H1 with 0.3% threshold to filter noise, applying a penalty for opposing BTC trends.
- **Entry Threshold**: Signals require a final_score ≥ +2.0 for execution.

### Signal Aggregation & Conflict Resolution
- **Score-Based Prioritization**: Signals are scored and sorted by final_score (descending) before processing.
- **Direction-Aware Locks**: Lock key format `signal_lock:{symbol}:{direction}` allows simultaneous LONG and SHORT signals.
- **Best Signal Selection**: For each direction, the highest-scoring signal acquires the lock; lower-scoring signals are rejected.
- **Threshold Gating**: Only signals with final_score ≥ 2.0 proceed to lock acquisition.
- **Conflict Policy**: Multiple signals of the same direction result in the best score winning; opposing directional signals can both execute.
- **Lock TTL**: Redis/SQLite locks expire after a configurable TTL.

### Filtering & Risk Management
- **Stop Distance Validation**: Prevents excessive risk by validating stop distance based on ATR.
- **Hybrid Entry System**: Adaptive MARKET/LIMIT execution based on strategy category (Breakout strategies use MARKET, Pullback/Mean Reversion use LIMIT) with R:R preservation using offset calculations.
- **BTCFilter**: Prevents mean reversion during significant BTC impulses and applies directional penalties.
- **Risk Calculator**: Manages position sizing, stop-loss (swing extreme + 0.2-0.3 ATR), and take-profit (1.5-3.0 RR).
- **Time Stops**: Exits trades if no progress within 6-8 bars.

### Telegram Integration
- Provides commands (/start, /help, /status, /strategies, /performance, /stats, /validate, /latency, /report) and Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- **/validate** - Validates all strategies for data availability, OHLCV integrity, price logic, signal generation, and entry/SL/TP correctness across different market regimes.
- **/performance** - Shows performance metrics with accurate PnL calculations.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals and calculates exit conditions using exact SL/TP levels.
- **Exit Logic**: Uses precise SL/TP levels (not current price) for exit_price and pnl_percent to ensure accurate statistics.
- **LIMIT Order Handling**: When LIMIT order fills, entry_price is updated in DB from target to actual fill price, ensuring accurate PnL calculations. Status transitions from PENDING to ACTIVE.
- **Performance Metrics Explained**:
  - **Средний PnL (Average PnL)**: Average profit/loss across ALL closed trades (wins + losses). Formula: (Total PnL) / (Number of trades). Shows average earnings per trade.
  - **Средняя победа (Average Win)**: Average profit on WINNING trades only. Formula: (Sum of wins) / (Number of wins). Shows typical profit when winning.
  - **Среднее поражение (Average Loss)**: Average loss on LOSING trades only. Formula: (Sum of losses) / (Number of losses). Shows typical loss when losing.
  - **Example**: 5 wins = +13% total (avg +2.60%), 7 losses = -11.7% total (avg -1.67%) → Average PnL = +1.3% / 12 = +0.11%
- **Exit Price Accuracy**: For LONG SL hit at 98 when price drops to 97.5, records exit=98 and PnL=-2% (not -2.5%). For SHORT TP hit at 96 when price drops to 95.8, records exit=96 and PnL=+4% (not +4.2%).

### Symbol Blocking System
- **Purpose**: Prevents multiple signals on the same symbol while an active signal exists.
- **Startup Loading**: On bot start, queries DB for all ACTIVE/PENDING signals and populates `symbols_with_active_signals` set before analysis begins.
- **Block on Signal Creation**: When MARKET or LIMIT signal is saved to DB, symbol is added to blocked set.
- **Skip Analysis**: Analysis loop checks if symbol is blocked before running strategies. Blocked symbols are skipped entirely.
- **Unblock on Closure**: When Performance Tracker closes a signal (SL/TP/TIME_STOP hit), callback removes symbol from blocked set.
- **DB Persistence**: Blocking state survives bot restarts by reloading active signals from database.
- **Logs**: "🔒 Loaded 6 active signals, blocked 6 symbols" on startup, "⏭️ {symbol} skipped - has active signal" during analysis.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. A `signals_only_mode` flag allows operation without live trading.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe coordination for parallel loading and analysis.
- **Loader Task**: Loads historical data with retry logic and pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols from the queue for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list based on 24h volume criteria.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix capabilities, and Telegram alerts.

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
- **pytz**: For timezone localization.

## Python Libraries
- **Data Processing**: pandas, numpy, pandas-ta.
- **Network**: aiohttp, websockets.
- **Database**: SQLAlchemy, Alembic.
- **Exchange**: python-binance, ccxt.
- **Scheduling**: APScheduler.
- **Configuration**: pyyaml, python-dotenv.