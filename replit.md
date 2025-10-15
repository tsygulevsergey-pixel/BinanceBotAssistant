# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for institutional trading principles. It employs 5 core strategies, operating in both Signals-Only Mode for signal generation and Live Trading Mode for full trading capabilities.

The bot focuses on quality strategies, market regime detection, structure-based stop-loss/take-profit, signal confluence, and multi-timeframe analysis. Key features include a local orderbook, historical data, advanced scoring, and comprehensive performance tracking. The "Action Price" system independently operates with S/R zones, Anchored VWAP, and price action patterns, aiming for an 80%+ Win Rate and a Profit Factor of 1.8-2.5.

# Recent Changes

## October 15, 2025: Performance Optimization & Enhanced Scoring

**4-Point Optimization System:**

1. **Volume Profile Zone Expansion** (src/strategies/volume_profile.py):
   - Expanded VAH/VAL detection zone from 0.3 ATR to 0.5 ATR
   - Captures more opportunities near Value Area boundaries
   - Maintains quality with acceptance/rejection logic intact

2. **TIME_STOP Patience Increase** (config.yaml):
   - Extended timeout from 6-8 bars to 12-16 bars (3-4 hours on 15m)
   - Allows quality setups more time to develop
   - TIME_STOP still disabled after TP1 hit (position protected)

3. **Aggressive Trailing Stop** (src/utils/signal_tracker.py):
   - After TP1: SL moved to +0.5R instead of breakeven
   - LONG: SL = Entry + 0.5*R_distance
   - SHORT: SL = Entry - 0.5*R_distance
   - Captures additional profit while maintaining protection

4. **Enhanced Score Differentiation** (src/scoring/signal_scorer.py):
   - **+1.0** Strong ADX (>30) in TREND regime
   - **+0.5** RSI extreme reversal (RSI<30 for LONG, RSI>70 for SHORT in MR strategies)
   - **+1.0** Regime alignment (Breakout in TREND, MR in RANGE/SQUEEZE)
   - **-0.5** Extreme ATR volatility (ATR > 2x average)
   - Total: 10 scoring components (6 original + 4 new)

## October 15, 2025: Break & Retest 3-Phase TREND Improvement System

Implemented comprehensive TREND regime improvements based on 19-signal analysis (17% WR → target 40-55% industry standard):

**PHASE 1 - Critical Filters (TREND only):**
- ADX threshold raised to 25 (from 20) for TREND mode, kept 15 for SQUEEZE
- ADX momentum check: requires ADX rising (current > 2 bars ago)
- Volume threshold: 1.8x for TREND, 1.2x for SQUEEZE (regime-specific)
- Bearish bias block: LONG signals blocked in TREND+Bearish (historically 12.5% WR)
- Higher Timeframe Confirmation: 1H EMA50 + 4H EMA50 alignment required when data available

**PHASE 2 - Important Improvements:**
- Bollinger Bands position filter: price must be near outer band (2% tolerance)
- Retest quality scoring: evaluates penetration depth and rejection strength (0-1 score)
- Improved score system: regime-specific bonuses (ADX 30+ = +1.0, volume 2x+ = +1.0, HTF confirmed = +1.0)

**PHASE 3 - Optimization:**
- RSI momentum confirmation: >45 for LONG, <55 for SHORT
- Market structure validation: Higher Highs/Lower Lows pattern check
- Confluence scoring: combines all filters into final signal score

**Key Design Principles:**
- All TREND-specific filters apply ONLY in TREND regime
- SQUEEZE regime (57% WR, +20% PnL) fully preserved with softer thresholds
- HTF confirmation: strict block if data available and disagrees, score penalty if data unavailable
- Config updated with regime-specific parameters (ADX 25/15, volume 1.8/1.2)

**Technical Implementation:**
- HTF uses EMA50 on both 1H and 4H (reduced from EMA200 for realistic data requirements)
- 1H/4H DataFrames added to indicators dict in main.py (lines 658-659)
- With 90-day history: 2160 bars on 1H, 540 bars on 4H - more than sufficient
- HTF confirmation returns tuple (confirmed: bool, has_data: bool) for smart blocking

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

### Strategy Framework
- **BaseStrategy**: Abstract base class for strategy definition.
- **StrategyManager**: Orchestrates strategies with regime-based selection.
- **Signal Dataclass**: Standardized signal output with confluence tracking.
- **5 CORE STRATEGIES**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile.
- **Action Price System**: Rewritten on EMA200 Body Cross logic with an 11-component scoring system for STANDARD, SCALP, and SKIP regimes. Includes JSONL logging for ML analysis and real-time MFE/MAE tracking.
  - **Event-Driven Execution**: Runs after 15m candles are loaded and saved. Supports partial loading.
  - **31-Second Delay**: Waits 31 seconds after any candle close for Binance to finalize data.
  - **Entry Price**: Uses close price of confirming candle.
  - **TP Calculation**: TP1 = Entry ± R, TP2 = Entry ± 2R where R = |Entry - SL|.
  - **Telegram Signals**: 🟢 for LONG, 🔴 for SHORT.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market into TREND/SQUEEZE/RANGE/CHOP/UNDECIDED.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for pre-computed indicators.

### Signal Scoring & Aggregation
- **Scoring Formula**: Combines base strategy score with market modifiers.
- **BTC Filter**: Filters noise and applies penalties for opposing BTC trends.
- **Conflict Resolution**: Score-based prioritization and direction-aware locks.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement with intelligent fallback and smart distance guard.
- **Trailing Stop-Loss with Partial TP**: For advanced profit management (30% @ TP1, 40% @ TP2, 30% trailing).
- **Market Entry System**: All strategies execute MARKET orders at current price for immediate entry.
- **Time Stops**: Exits trades if no progress.
- **Symbol Blocking System (Per-Strategy)**: Independent blocking per strategy allows multiple strategies on the same symbol.

### Telegram Integration
- Provides commands for status, strategy details, performance, validation, and latency.
- Delivers Russian language signal alerts with entry/exit levels, regime context, and score breakdown.
- Unified `/performance` and `/ap_stats` commands for statistics.
- **Telegram Keyboard & Menu UI**: Persistent button keyboard for quick access to main functions (4 buttons: Performance, Action Price, Closed Signals, Closed AP). Commands: `/menu` (show/hide), `/closed` (closed signals), `/closed_ap` (AP closed).
- **Message Length Protection**: Auto-splits long messages into multiple parts (Telegram 4096 char limit).

### Logging System
- Separate log files for Main Bot and Action Price in `logs/` directory, using Europe/Kyiv timezone.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, calculates exit conditions, and updates PnL.
- **ActionPricePerformanceTracker**: Tracks Action Price signals with partial exits, breakeven logic, TP1/TP2 tracking, MFE/MAE tracking, and detailed JSONL logging.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and `enabled: true/false` flags for strategies.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe coordination.
- **Loader Task**: Loads historical data, retries on failure, and pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols from the queue for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list based on 24h volume.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel loader/analyzer tasks, and launching the Telegram bot. Data is loaded in parallel, enabling immediate analysis. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, running strategies, scoring signals, applying filters, and sending Telegram alerts. Persistence includes storing candles/trades in SQLite and logging signals.

## Error Handling & Resilience
- **Smart Rate Limiting**: 55% safety threshold (1320/2400) with 1080 requests buffer. Prevents API bans.
- **IP BAN Prevention v4**: Event-based coordination with single-log notification. All pending requests blocked immediately via ip_ban_event flag.
- **Periodic Gap Refill with Request Weight Calculator**: Pre-calculates total requests needed, respects 55% threshold, uses MIN_BATCH_SIZE, FIFO ordering, and batch processing with waits.
- **Burst Catchup Safety**: Rate usage checked after each batch, extra pause if > 50%.
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