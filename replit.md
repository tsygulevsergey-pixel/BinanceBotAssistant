# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for high-performance trading. It incorporates advanced strategies, market regime detection, and sophisticated risk management to achieve an 80%+ Win Rate and a Profit Factor of 1.8-2.5. The bot utilizes an "Action Price" system based on Support/Resistance zones, Anchored VWAP, and price action patterns, alongside an experimental "Gluk System" for high-win-rate legacy Action Price implementation. It supports both Signals-Only and Live Trading Modes.

# User Preferences

Preferred communication style: Simple, everyday language.

# Recent Changes

## 3-Tier TP System with SCALP Mode Enhancement (2025-10-19)
- **Problem**: SCALP mode signals (score 3.0-5.9) only got TP1, missing continuation profits. Example: TAOUSDT score 3.0 captured +1.03% at TP1 only, but price peaked at +2.6%, missing +1.57% potential profit (+52% improvement).
- **Solution**: Implemented 30/40/30 position management system for ALL modes:
  - **TP1 @ 1R**: 30% exits (all modes)
  - **TP2 @ 1.5R (SCALP)** or **2R (STANDARD)**: 40% exits
  - **Trailing Stop @ 1.2 ATR**: 30% remainder tracks peak and closes on pullback
- **Configuration** (config.yaml):
  - `tp2_scalp_rr: 1.5` - Conservative TP2 for lower score signals
  - `tp3_trail_atr: 1.2` - ATR-based trailing distance for runners
  - Position split: `tp1_size: 0.30, tp2_size: 0.40, trail_size: 0.30`
- **Database Schema** (models.py):
  - Added `trailing_peak_price` Column to ActionPriceSignal table for persistent peak tracking
  - Ensures trailing stop state survives bot restarts
- **Automatic Migration** (db.py):
  - Added `_apply_migrations()` method that runs before create_all()
  - Automatically adds trailing_peak_price column to existing databases
  - Handles both fresh and production deployments gracefully
- **Code Changes**:
  - `engine.py`: SCALP mode now generates TP2 @ 1.5R (was None)
  - `performance_tracker.py`: 
    - Updated `_calculate_total_pnl()` for 3-level PnL calculation (30/40/30 weighting)
    - TP2 no longer closes signal - activates trailing stop for 30% remainder
    - Added trailing stop logic: tracks peak after TP2 using DB field, closes on ≥1.2 ATR pullback
    - Peak tracking persists in database (signal.trailing_peak_price)
    - Added Time Stop after TP2 (72 hours) for stale runners
    - Updated statistics: added `trailing_stop_count` metric
- **Impact**: Low-score signals (3.0-5.9) can now capture runner profits while maintaining risk-adjusted entries. Expected to improve average PnL per signal by 30-50% for SCALP mode without degrading Win Rate.
- **Persistence**: All trailing stop state stored in database, system survives restarts without losing tracking data.
- **Statistics**: PnL calculation properly handles all 3 exit scenarios (TP1-only, TP2-only, TP2+Trail) with accurate position weighting.

## Per-Strategy Signal Lock System (2025-10-19)
- **Problem**: SignalLockManager blocked symbol+direction globally across ALL strategies. Only first strategy (Break & Retest) could generate signals - others blocked even though enabled.
- **Root Cause**: Lock check only filtered by `symbol` + `direction`, missing `strategy_name` parameter.
- **Fix Applied**:
  - **SQLite**: Added `strategy_name` to lock query filter (signal_lock.py line 136-140)
  - **Redis**: Changed lock key from `signal_lock:{symbol}:{direction}` to `signal_lock:{symbol}:{direction}:{strategy_name}`
  - **Release**: Updated `release_lock()` signature to accept `strategy_name` parameter
  - **Signal Tracker**: All 8 `release_lock()` calls now pass `direction` and `strategy_name`
- **New Behavior**:
  - ✅ Multiple strategies CAN signal same symbol+direction simultaneously (e.g., Liquidity Sweep LONG BTCUSDT + Break & Retest LONG BTCUSDT)
  - ❌ Same strategy CANNOT have >1 active signal on same symbol+direction
  - 🔓 Lock releases only for specific strategy when its signal closes (TP/SL)
- **Impact**: All 6 enabled strategies (Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile, ATR Momentum) can now independently generate signals on the same symbols.

## Statistics & Display Fixes (2025-10-19)
- **Fixed Breakeven Statistics**: Corrected exit_type mislabeling in signal_tracker.py (lines 154, 238) - breakeven exits (pnl=0) were incorrectly marked as "TP1".
- **Fixed Action Price R:R Display**: Changed from single incorrect R:R (calculated for TP2) to per-level display showing accurate risk-reward for each target (TP1, TP2, TP3 if exists).
- **Created fix_breakeven.py**: One-time database correction script for historical records with exit_type='TP1' where pnl_percent=0.0 and exit_price=entry_price.

## Rate Limiter & Signal Checker Optimization (2025-10-19)
- **Fixed Rate Limiter Drift**: Corrected counter reset detection when Binance resets to new minute (prevents -108 drift accumulation).
- **Fixed Signal Checker Blocking**: Changed from held lock to flag-based concurrency control to prevent cycle blocking during slow candle refresh.
- **Added Monitoring**: Cycle duration logging and counter reset tracking for performance monitoring.
- **Impact**: Eliminates "Previous signal check still running" warnings and downstream Telegram NetworkError symptoms.

## Action Price Score Logic Discussion (2025-10-19)
- **Current Behavior**: Score < 4.0 = TP1 only; 4.0-6.0 = TP1+TP2; >6.0 = TP1+TP2+trail.
- **Observation**: LTCUSDT Score 3.0 signal captured strong impulse (+0.73% peak) but closed at TP1 only (+0.11%), missing additional +0.62% potential profit.
- **Decision**: Monitor more signals before making architectural changes. MFE/MAE data in JSONL logs will help analyze if low-score signals frequently have high upside potential.
- **Future Consideration**: Dynamic trailing stop after TP1 for low-score signals that show strong momentum continuation.

## Critical Bug Fix: Bot Freeze & Timeout Protection (2025-10-19)
- **Symptom**: Bot froze for 10+ hours (11:44 - 22:00) with no main loop activity, but Performance Tracker continued working.
- **Root Cause #1**: aiohttp.ClientSession created WITHOUT timeout in src/binance/client.py line 46. When Binance API failed to respond to Open Interest History request, bot hung indefinitely on `await response`.
- **Root Cause #2**: WebSocket connection without timeout in src/binance/websocket.py line 64. Could potentially hang indefinitely on connection.
- **Fix #1**: Added ClientTimeout(total=60) to aiohttp session. HTTP requests now timeout after 60 seconds max.
- **Fix #2**: Added asyncio.wait_for(timeout=30) to WebSocket connection. Connection attempts timeout after 30 seconds max.
- **Impact**: Comprehensive protection against infinite hangs from network issues or unresponsive endpoints (HTTP + WebSocket).

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: Handles REST API interactions with rate limiting and exponential backoff.
- **DataLoader**: Manages historical candle data, ensuring accuracy.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket.
- **BinanceWebSocket**: Provides real-time market data streaming.
- **Smart Candle-Sync Main Loop**: Synchronizes signal checks to candle close times.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries).

### Strategy Framework
- **BaseStrategy**: Abstract class for trading strategies.
- **StrategyManager**: Orchestrates strategy execution based on market regimes.
- **Signal Dataclass**: Standardized output for trading signals.
- **6 CORE STRATEGIES**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile, ATR Momentum.
- **Action Price System**: An 11-component scoring system for dynamic entry, TP, and SL calculations on 15m candles.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market states.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for indicators.

### Signal Scoring & Aggregation
- Combines strategy scores with market modifiers, including BTC filter and conflict resolution.
- **CVD Divergence Confirmation**: Multi-timeframe (15m+1H) divergence detection for bonus scoring.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement with fallbacks.
- **Trailing Stop-Loss with Partial TP**: Configurable profit management.
- **Market Entry System**: All strategies execute MARKET orders.
- **Time Stops**: Exits trades if no progress.
- **Symbol Blocking System**: Independent blocking per strategy.
- **Pump Scanner v1.4**: TradingView indicator for pump detection.
- **Break & Retest Enhancements**: HTF trend alignment, candlestick patterns, ATR-based dynamic TP/SL, volume confirmation.
- **Volume Profile & Liquidity Sweep Enhancements**: POC magnet filter, stricter acceptance logic, HTF trend alignment.
- **Multi-Factor Confirmation & Regime-Based Weighting**: Requires multiple confirmations and applies regime-specific weighting.
- **Action Price SL Filter**: Rejects signals with excessively wide stop-loss.

### Telegram Integration
- Provides commands for bot status, strategy details, performance, validation, and signal alerts in multiple languages, with a persistent button keyboard UI.

### Logging System
- Separate log files for Main Bot and Action Price, with centralized JSONL logging for Action Price signals.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, exit conditions, and PnL.
- **ActionPricePerformanceTracker**: Tracks Action Price signals, partial exits, breakeven logic, MFE/MAE, and logs to JSONL.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and `enabled` flags.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe data loading.
- **Loader Task**: Loads historical data.
- **Analyzer Task**: Consumes symbols for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts.

### Strategy Execution Optimization
- **Parallel Strategy Checks**: Regular strategies execute in parallel batches using asyncio.gather for performance improvement.
- **Independent Execution**: Action Price system runs independently with its own optimized execution path.

## Data Flow
The system loads configurations, connects to Binance, starts parallel data processing, and launches the Telegram bot. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, executing strategies in parallel, scoring signals, applying filters, and sending Telegram alerts. Data is persisted in SQLite, and signals are logged.

## Error Handling & Resilience
- **Smart Rate Limiting**: Prevents API bans.
- **IP BAN Prevention v4**: Event-based coordination to block pending requests.
- **Periodic Gap Refill with Request Weight Calculator**: Manages batch processing.
- **Burst Catchup Safety**: Checks rate usage after each batch.
- **Exponential Backoff**: Retry logic for transient errors.
- **Auto-Reconnection**: WebSocket auto-reconnect with orderbook resynchronization.
- **Graceful Shutdown**: Clean resource cleanup and state persistence.

## Feature Specifications

### Action Price System Improvements (Phases 1 & 2)
- **Scoring Inversion**: Corrected inverted scoring components, improved `confirm_depth`, `overextension_penalty`, `lipuchka_penalty`, removed problematic components, and amplified quality components. Increased `min_total_score` to favor better signals.
- **Entry Timing & Dynamic Risk**: Raised `max_sl_percent`, added Volume Confirmation as a new scoring component, redesigned `close_position` to favor pullback entries, and redesigned `ema_fan` to reward early trend stages.

### CVD Divergence as Confirmation Filter
- Implemented as a confirmation bonus (not a standalone trigger) in `SignalScorer`.
- Uses a multi-timeframe approach (15m + 1H) for scoring bonuses (+0.3 to +0.8).
- Detects bullish and bearish divergences with volume confirmation and lookback periods.
- Configurable for enabling/disabling and scoring parameters.

### ATR Momentum Strategy
- Activated strategy to catch explosive moves (≥1.4× median ATR) with high conviction.
- Includes HTF EMA200 Confirmation (1H + 4H) to filter counter-trend impulses.
- Adds a Pin Bar Bonus (+0.5 score) for high-conviction setups.
- Incorporates an RSI Overextension Filter to avoid entries at market extremes (RSI > 70 or < 30).
- Increased `min_distance_resistance` to 2.0 ATR for stricter quality checks.

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