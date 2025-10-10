# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates 9 core strategies (with plans for 8+ more) spanning breakout, pullback, and mean reversion categories, all architect-validated against detailed specifications. The bot provides real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/RANGE/SQUEEZE), BTC correlation filtering, an advanced scoring system (volume, CVD, OI delta, depth imbalance), and robust risk management with stop-loss, take-profit, and time-stop mechanisms.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### 1. Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches historical data from data.binance.vision with caching.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket differential updates for sub-second depth imbalance detection.
- **BinanceWebSocket**: Real-time market data streaming (klines, trades, depth updates).

### 2. Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries on (symbol, timeframe, timestamp)) for simplicity and concurrent reads.

### 3. Strategy Framework
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates multiple strategies across timeframes.
- **Signal Dataclass**: Standardized signal output.
- **Implemented Strategies**: 16 strategies are implemented (15 active), including Donchian Breakout (1h), Squeeze Breakout, MA/VWAP Pullback, Range Fade, Volume Profile, Liquidity Sweep, Order Flow, CVD Divergence, and Time-of-Day. Market Making is disabled (requires HFT orderbook). All strategies are architect-validated for compliance with manual requirements, including H4 swing confluence, mandatory filters (ADX, ATR%, BBW, expansion block), dual confluence, BTC directional filtering, and a signal scoring threshold ≥+2.0.

### 4. Market Analysis System
- **MarketRegimeDetector**: Classifies market into TREND/RANGE/SQUEEZE/UNDECIDED using multi-factor confirmation.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.

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

# Recent Changes (October 2025)

## Latest Updates (October 10, 2025)
1. ✅ **Smart Timeframe Synchronization** - Умная докачка данных с Binance
   - **Оптимизированное обновление**: свечи обновляются ТОЛЬКО когда закрываются
     - 15m свечи: каждые 15 минут (00, 15, 30, 45)
     - 1h свечи: каждый час (00:00)
     - 4h свечи: каждые 4 часа (00, 04, 08, 12, 16, 20)
   - TimeframeSync кэширует обновления (избегает дублирующих запросов)
   - Автоматическая докачка gap'ов в данных (если разница >5 минут)
   - Расписание обновлений отображается при запуске бота
   - **Экономия API лимитов**: обновления только когда нужно (не каждую минуту)

## Previous Updates
1. ✅ **Implemented Reclaim Mechanism** - "Hold N bars" validation for ALL mean reversion strategies
   - New module `src/utils/reclaim_checker.py` with reusable reclaim functions:
     - check_value_area_reclaim(): verifies price was outside VA, returned and held N bars inside
     - check_level_reclaim(): for VWAP/EMA levels with tolerance
     - check_range_reclaim(): for range boundaries with hold confirmation
   - **All 4 MR strategies updated** (default 2-bar hold):
     - **VWAP Mean Reversion**: requires hold inside VAL/VAH or VWAP bands
     - **Range Fade**: proximity check (0.3 ATR) + reclaim support/resistance with hold
     - **Volume Profile**: VAH/VAL rejection requires value area reclaim with hold
     - **RSI/Stoch MR**: oscillator signals + reclaim VAL/VWAP levels with hold
   - Reduces false signals from brief touches, improves signal quality significantly
2. ✅ **Implemented Signal Performance Tracking** - Real-time PnL monitoring and win rate analytics
   - SignalPerformanceTracker runs as background task (60s check interval)
   - Monitors active signals: checks TP/SL/time-stop via mark price API
   - Calculates PnL: LONG (exit-entry)/entry×100, SHORT (entry-exit)/entry×100
   - Updates signal status: WIN (TP hit), LOSS (SL hit), TIME_STOP (no progress)
   - Auto-releases symbol lock when signal exits
   - **Telegram commands**: /performance (overall stats), /stats (per-strategy breakdown)
   - Provides: total signals, win rate, avg/total PnL, avg win/loss, closed/active counts
3. ✅ **Implemented "1 signal per symbol" lock** - Redis-based + SQLite fallback
   - SignalLockManager prevents duplicate signals on same symbol
   - TTL-based expiration (3600s default)
   - Automatic lock release on signal exit
4. ✅ **Signal persistence to database** - All signals saved with metadata
   - Stable strategy_id using CRC32 hash
   - Context_hash for deduplication  
   - Telegram message_id linking
   - Timezone-aware timestamps (UTC)