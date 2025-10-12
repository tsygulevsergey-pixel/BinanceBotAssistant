# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories, providing real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading with fast catchup and periodic gap refill, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/SQUEEZE/RANGE/CHOP), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms.

A fully integrated **Action Price** strategy system is included, operating independently to identify high-probability setups using Support/Resistance zones, Anchored VWAP, EMA trend filters, and 5 classic price action patterns (Pin-Bar, Engulfing, Inside-Bar, Fakey, PPR) with partial profit-taking capabilities.

# Recent Changes

## Action Price Architecture Overhaul (October 12, 2025)
- **Issue 1**: 141 сигнала за одну проверку - слишком много сигналов низкого качества
- **Issue 2**: 0% Win Rate - точки входа устаревали к моменту отправки в Telegram, сигналы моментально закрывались по SL
- **Issue 3**: Сигналы с confidence 4.6 принимались - нет минимального порога
- **Issue 4**: PPR паттерн слишком агрессивен - 131/141 сигналов были PPR (любой пробой засчитывался)
- **Root Cause 1**: PPR паттерн использует `entry_trigger = c0['close']` - цена закрытия прошлой свечи, которая устаревает через несколько секунд
- **Root Cause 2**: Stop Loss ставился за экстремумом СВЕЧИ (c0['high']/c0['low']), а не за ЗОНОЙ поддержки/сопротивления
- **Root Cause 3**: Нет проверки минимального confidence score - любой сигнал проходит
- **Root Cause 4**: PPR условие `c0['close'] < c1['low']` слишком простое - даже слабый пробой генерирует сигнал
- **Fix 1 (CRITICAL)**: Полностью переработана архитектура расчета Entry/Stop/Targets:
  - Entry теперь ВСЕГДА = current_price (получается через API запрос Binance get_mark_price, не историческая c0['close'])
  - Stop Loss теперь ставится ЗА ЗОНОЙ (zone['high']/zone['low'] + buffer), а не за свечой:
    * LONG: stop_loss = zone['low'] - buffer (ниже зоны поддержки)
    * SHORT: stop_loss = zone['high'] + buffer (выше зоны сопротивления)
  - TP1 = Entry + 1R (где R = |Entry - Stop Loss|)
  - TP2 = Entry + 2R
- **Fix 2**: Добавлен `min_confidence_score: 150.0` в config.yaml и проверка в engine.py
- **Fix 3**: Ужесточен PPR паттерн - теперь требуется направленная свеча (close < open для SHORT) + сильное тело (≥30% range предыдущей свечи)
- **Fix 4**: Добавлена строгая проверка близости паттерна к зоне S/R - паттерн должен быть либо ВНУТРИ зоны, либо в пределах 2×MTR от ближайшей границы зоны (иначе отбрасывается)
- **Result**: Полное решение проблемы 0% Win Rate - Entry всегда актуальная, Stop Loss корректно за зоной, TP1/TP2 = 1R/2R; ожидается снижение количества сигналов до ~5-30 за проверку с положительным Win Rate

## Critical Bugfixes: Data Loader, TimeframeSync & Main Loop (October 12, 2025)
- **Issue 1**: Bot crashed with empty error messages during data loading failures (`Error downloading SPXUSDT 15m: . Retry 1/3...`)
- **Issue 2**: TimeframeSync never detected candle closes - strategies never ran (`⏭️ No candles closed - skipping` every check)
- **Issue 3**: Main loop strategy check never executed - `iteration % check_interval` never aligned with actual time
- **Root Cause 1**: DataLoader continued execution with incomplete data after download failures, causing unhandled exceptions
- **Root Cause 2**: TimeframeSync checked cache BEFORE checking if candle closed - always returned False even at :00, :15, :30, :45
- **Root Cause 3**: Main loop used `iteration % 60 == 0` which never matched actual time - bot started at 12:52:55, iteration 211 at 12:56:26 → 211 % 60 = 31 ≠ 0
- **Fix 1**: DataLoader now raises explicit exception on download failure with proper error message; symbol marked as failed, bot continues with other symbols
- **Fix 2**: TimeframeSync logic reordered - checks candle close time FIRST, then cache; detection window expanded to 90 seconds (e.g., 12:45:00-12:46:30)
- **Fix 3**: Main loop now uses `(current_time - last_check_time).total_seconds() >= check_interval` - checks real elapsed time instead of iteration counter
- **Result**: Bot no longer crashes on network errors; strategies correctly trigger every 60 seconds; Runtime Fast Catchup executes properly

## Database Cleanup Scripts (October 12, 2025)
- **clear_signals.py**: Interactive script to clean signal data while preserving candle history
  - Supports both standard strategies and Action Price signals
  - Options: Delete all signals, delete by status (WIN/LOSS/TIME_STOP), delete only Action Price, delete ACTIVE/PENDING
  - Shows detailed statistics before deletion with confirmation prompts
  - Safely removes signals without touching valuable candle data (2.4M+ candles preserved)
- **clear_blocked_symbols.py**: Quick script to unblock symbols by removing ACTIVE/PENDING signals
  - Handles both signal types (standard + Action Price)
  - Use when symbols are blocked and preventing new signal generation
  - Requires bot restart after execution

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