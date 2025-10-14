# Overview

This project is a **professional-grade** Binance USDT-M Futures Trading Bot following institutional trading principles. The bot uses a **focused approach** with 5 CORE strategies instead of attempting to trade everything. It operates in Signals-Only Mode for signal generation and Live Trading Mode for full trading capabilities.

**PROFESSIONAL APPROACH (30-летний опыт трейдера, 80%+ Win Rate):**
- ✅ **Quality over Quantity**: 5 CORE strategies (not 15) - focus on proven edge
- ✅ **Market Regime Detection**: TRENDING/RANGING/VOLATILE/CHOPPY classification before any signal
- ✅ **Structure-Based SL/TP**: Stop-loss at swing lows/VAL, not arbitrary ATR multiples
- ✅ **Signal Confluence**: When 2+ strategies agree → stronger signal with score boost
- ✅ **Multi-Timeframe Analysis**: 4H context → 1H signals → 15M confirmation → 5M execution
- ✅ **Partial Profit Taking**: 30% @ TP1 (1R), 40% @ TP2 (2R), 30% trailing runner
- ✅ **Expected Performance**: 12-16 quality signals/hour, 60-70% Win Rate, 1.8-2.5 Profit Factor

Key features include local orderbook, historical data, multi-TF analysis (4H/1H/15M/5M), market regime detection, BTC filtering, advanced scoring with confluence, structure-based risk management, and comprehensive performance tracking. **Action Price** system operates independently with S/R zones, Anchored VWAP, and 5 price action patterns.

**RECENT CHANGES (Professional Transformation Complete):**
- ✅ Simplified to 5 CORE strategies (disabled 10 weak ones)
- ✅ Added Market Regime Detection (TRENDING/RANGING/VOLATILE/CHOPPY)
- ✅ Extended Signal model with 20+ professional fields (regime, confluence, MAE/MFE, trailing)
- ✅ Created Signal Confluence system (bonus when 2+ strategies agree)
- ✅ Added Telegram commands: /regime_stats, /confluence_stats
- ✅ Partial TP system ready for 30/40/30 implementation (TODO in signal_tracker.py)
- ✅ **CRITICAL FIX (Oct 14)**: Rate limiter bug - properly stops requests at 90% threshold (2160/2400)
- ✅ **API LIMIT FIX (Oct 14)**: Updated to Futures API limit 2400/min (was 1100 for SPOT)
- ✅ **PARALLELISM FIX (Oct 14)**: Reduced to 1 worker (from 2-3) to prevent IP ban
- ✅ **SCORE THRESHOLD (Oct 14)**: Lowered from 4.5 to 3.0 for better signal frequency
- ✅ **EMA200 INDICATOR (Oct 14)**: Created TradingView indicator with 7 professional filters (tradingview/16_ema200_body_cross.pine)
- ✅ **EMA200 STRATEGY (Oct 14)**: Created TradingView strategy for backtesting (tradingview/16_ema200_body_cross_STRATEGY.pine)
- ✅ **PROFESSIONAL FILTERS (Oct 14)**: Updated indicator with slope200, color confirmation, pre-touch, oversized initiator, fan ready, distance filters
- 📋 SQL migration available: migrations/add_professional_fields.sql, apply_migration.py script for Windows

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

### Strategy Framework (Professional Approach)
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates strategies with regime-based selection.
- **Signal Dataclass**: Standardized signal output with confluence tracking.

**5 CORE STRATEGIES (Active):**
1. **Liquidity Sweep** (#11) ⭐⭐⭐ - Primary edge in crypto (stop hunts, false breakouts)
2. **Break & Retest** (#5) ⭐⭐⭐ - Structure-based trading (quality over quantity)
3. **Order Flow** (#12) ⭐⭐ - Smart money tracking (Delta, OI, aggressive buyers/sellers)
4. **MA/VWAP Pullback** (#4) ⭐⭐ - Trend-following (buy pullbacks in uptrend)
5. **Volume Profile** (#9) ⭐⭐ - Institutional levels (VAH/VAL/POC acceptance/rejection)

**Disabled Strategies (may be used as filters later):**
- Donchian (#1), Squeeze (#2), ORB (#3), ATR Momentum (#6), VWAP MR (#7), Range Fade (#8), RSI/Stoch (#10), CVD Divergence (#13), Time of Day (#14)
- Reason: переобучены, не работают в крипте 24/7, или слишком редкие сигналы

**Action Price System**: Independent production module using S/R zones, Anchored VWAP, EMA filters, and 5 price action patterns with advanced Zone Strength System (V2 with score threshold 5.0).

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
- **Symbol Blocking System (Per-Strategy)**: Each strategy independently blocks symbols when it has an active signal. Multiple strategies can work on the same symbol simultaneously (e.g., if Donchian has BTCUSDT signal, CVD Divergence can still generate BTCUSDT signal). Enables accurate per-strategy statistics and performance tracking. Action Price has independent blocking.

### Telegram Integration
- Provides commands for status, strategy details, performance, validation, and latency.
- Delivers Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- `/performance` - unified statistics for main strategies (Total signals, Win Rate, TP1/TP2 counts, Average PnL)
- `/ap_stats` - unified statistics for Action Price (same format as /performance, tracking TP1/TP2 partial exits)

### Logging System
- Separate log files for Main Bot and Action Price, located in the `logs/` directory, using Europe/Kyiv timezone.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, calculates exit conditions using precise SL/TP levels, and updates entry prices for accurate PnL. Provides detailed metrics: Average PnL, Average Win, Average Loss.
- **Breakeven PnL Logic**: When TP1 is hit, the system saves the actual TP1 PnL. If price returns to breakeven, the signal closes with the saved TP1 PnL instead of 0%, accurately reflecting the partial profit taken.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and specific configurations for the Action Price system.
- **Strategy Enable/Disable System**: Each strategy has an `enabled: true/false` flag in config.yaml for easy activation control without code changes. Status displayed at startup showing active/inactive strategies.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe coordination.
- **Loader Task**: Loads historical data, retries on failure, and pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols from the queue for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list based on 24h volume.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts, including smart age-based alerting for new coins.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel loader/analyzer tasks, and launching the Telegram bot. Data is loaded in parallel, enabling immediate analysis. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, running strategies, scoring signals, applying filters, and sending Telegram alerts. Persistence includes storing candles/trades in SQLite and logging signals.

## Error Handling & Resilience
- **Smart Rate Limiting**: 90% safety threshold prevents API bans. Automatic pause and resume when approaching limit.
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