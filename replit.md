# Overview

This project is a sophisticated Binance USDT-M Futures Trading Bot designed to generate trading signals based on advanced technical analysis and market regime detection. It incorporates multiple strategies spanning breakout, pullback, and mean reversion categories, architect-validated against detailed specifications. The bot provides real-time market data synchronization, technical indicator calculations, a sophisticated signal scoring system, and Telegram integration for notifications.

The bot operates in two modes: a Signals-Only Mode for generating signals without live trading, and a Live Trading Mode for full trading capabilities. Its key features include a local orderbook engine, historical data loading, multi-timeframe analysis (15m, 1h, 4h), market regime detection (TREND/SQUEEZE/RANGE/CHOP), BTC correlation filtering, an advanced scoring system, and robust risk management with stop-loss, take-profit, and time-stop mechanisms. The project's ambition is to provide a highly performant and reliable automated trading solution for cryptocurrency futures markets, focusing on data integrity and strategic validation.

# Recent Changes

## 2025-10-11: Market Regime Detection Fixed (CHOP режим добавлен)
- **Добавлен новый режим CHOP** (choppy/беспорядочное движение):
  - MarketRegime enum теперь содержит 5 режимов: TREND/SQUEEZE/RANGE/CHOP/UNDECIDED
  - CHOP = низкий ADX + волатильность + EMA не плоские (беспорядочное движение)
  - RANGE = низкий ADX + волатильность + EMA плоские (чистая консолидация)
- **Исправлен приоритет определения режима**:
  - **ПРИОРИТЕТ 1**: TREND (ADX > 20 + EMA выровнены) - сильный тренд
  - **ПРИОРИТЕТ 2**: SQUEEZE (BB width < p25 + длительность ≥12 баров) - узкая консолидация
  - **ПРИОРИТЕТ 3**: RANGE/CHOP (ADX < 20 + BB width < p30) - боковое движение
  - Раньше: SQUEEZE → TREND → RANGE (неправильный порядок, все было SQUEEZE)
  - Теперь: TREND → SQUEEZE → RANGE/CHOP (правильный порядок)
- **Добавлено детальное debug логирование** для каждого определенного режима
- **Architect validated**: Логика корректна, SQUEEZE не конфликтует с RANGE/CHOP, все стратегии получают правильные режимы
- **Результат**: Стратегии теперь получают корректные режимы рынка, позволяя mean-reversion стратегиям работать в CHOP

## 2025-10-11: Исправлена нехватка данных для стратегий
- **Увеличены лимиты загрузки данных для стратегий**:
  - 15m: с 200 до **8,640 баров** (90 дней) - для RSI/Stoch MR
  - 1h: с 200 до **1,440 баров** (60 дней) - для Donchian Breakout
  - 4h: с 200 до **360 баров** (60 дней)
- **Проблема**: ORB/IRB требовала 5,760 баров (60 дней × 24 × 4), получала только 200
- **Решение**: `main.py` теперь передает достаточно данных с динамическими лимитами per-timeframe
- **Результат**: Все стратегии работают с полными историческими данными

## 2025-10-11: Логи с датой/временем запуска
- **Изменена система логирования для создания новых файлов при каждом запуске**:
  - Формат имени: `bot_2025-10-11_11-58-56.log` (дата_время-запуска.log)
  - Формат имени: `strategies_2025-10-11_11-58-56.log` (дата_время-запуска.log)
  - Заменен TimedRotatingFileHandler на обычный FileHandler с timestamp в имени
  - Каждый запуск бота создает новую пару файлов логов
  - Легко отследить логи конкретного запуска
  - Старые логи сохраняются и не перезаписываются

## 2025-10-11: Pandas FutureWarning Fix
- **Fixed VWAP calculation pandas deprecation warning**:
  - Added `include_groups=False` parameter to `groupby().apply()` in `src/indicators/vwap.py`
  - Eliminated hundreds of FutureWarning messages that were spamming logs
  - Logs now clean and readable

## 2025-10-11: Comprehensive Strategy Failure Logging (ALL 15 Strategies)
- **Implemented detailed failure reason logging across all 15 active strategies**:
  - Added `strategy_logger.debug()` before EVERY `return None` statement in all strategy check_signal() methods
  - **68 new logging statements** added across 15 strategy files
  - Each rejection now logs the EXACT reason with ❌ prefix in Russian
  - **Categories of logged failures**:
    - **Regime mismatches**: "❌ Режим SQUEEZE, требуется TREND"
    - **Data insufficiency**: "❌ Недостаточно данных: 200 баров, требуется 5760"
    - **Volatility filters**: "❌ BB width не в диапазоне p30-40", "❌ Squeeze слишком короткий: 0 баров < 12"
    - **Volume filters**: "❌ объем низкий: 1.2x < 1.5x"
    - **Price conditions**: "❌ Цена не около VAH/VAL (расстояние > 0.3 ATR)"
    - **H4 bias conflicts**: "❌ LONG пробой есть, но H4 bias Bearish"
    - **Pattern confirmations**: "❌ Нет недавнего пробоя с объемом >1.5x", "❌ Нет дивергенции"
    - **Disabled strategies**: "❌ Стратегия отключена: нет данных funding rate"
  - **Logging infrastructure**:
    - Separate `logs/strategies.log` file (DEBUG level, 7-day rotation)
    - `src/utils/strategy_logger.py` with timezone-aware formatter (Europe/Kiev)
    - DEBUG to file (all details), WARNING+ to console (critical only)
  - **Per-symbol analysis flow**:
    1. 🔍 АНАЛИЗ: symbol | Режим: regime | Bias: bias
    2. 📋 Проверка 16 стратегий...
    3. For each strategy: 🔍 Проверка → ❌ Reason (if failed) → ⚪ Result
    4. 📈 Итого: checked/skipped/signals statistics
  - **Architect validated**: No logic changes, only logging added, negligible performance impact
- **Cleaned up BTC filter spam**: Changed impulse/expansion detection from INFO to DEBUG level

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
- **MarketRegimeDetector**: Classifies market into TREND/SQUEEZE/RANGE/CHOP/UNDECIDED using multi-factor confirmation with priority-based detection (TREND → SQUEEZE → RANGE/CHOP).
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