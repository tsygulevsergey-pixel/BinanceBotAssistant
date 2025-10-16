# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot. It implements 5 core trading strategies, operating in both Signals-Only Mode for generating trading signals and Live Trading Mode for full trading capabilities. The bot emphasizes quality strategies, market regime detection, structure-based stop-loss/take-profit mechanisms, signal confluence, and multi-timeframe analysis. It aims for an 80%+ Win Rate and a Profit Factor of 1.8-2.5, utilizing an "Action Price" system based on Support/Resistance (S/R) zones, Anchored VWAP, and price action patterns.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches historical data, supports caching, fast catchup, and periodic gap refill. **CLOSED CANDLES ONLY**: Automatically filters out the last unclosed candle from Binance API (checks `close_time > now`). Automated data refresh is enabled on bot startup (10 days), configurable for specific day ranges. All candles in DB are UPDATE-able to ensure data accuracy.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket differential updates.
- **BinanceWebSocket**: Real-time market data streaming.
- **Smart Candle-Sync Main Loop (Oct 17, 2025)**: Main loop now calculates exact candle close times (15m: 00/15/30/45, 1h: 00, 4h: 00/04/08/12/16/20, 1d: 00:00) and waits precisely until close+31s before triggering signal check. Eliminates previous 0-60s random delay from fixed-interval timer. Ensures Action Price and strategies always analyze fresh data exactly 31s after candle close.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries). Existing candles are updated, not skipped, to ensure data accuracy.

### Strategy Framework
- **BaseStrategy**: Abstract base class.
- **StrategyManager**: Orchestrates strategies with regime-based selection.
- **Signal Dataclass**: Standardized signal output with confluence tracking.
- **5 CORE STRATEGIES**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile.
- **Action Price System**: Based on EMA200 Body Cross logic, featuring an 11-component scoring system for different market regimes (STANDARD, SCALP, SKIP). Includes JSONL logging for ML analysis and real-time MFE/MAE tracking. It processes only fully closed 15m candles (filtering out the last unclosed candle). **UPDATED Entry/TP/SL Logic (Oct 16, 2025)**: Risk (R) calculated from SL to Close of confirming candle (fixed), TP levels calculated from Close of confirming candle (TP1=Close±1R, TP2=Close±2R), Entry price fetched via `get_mark_price()` REST API (Binance fair price updated every second) for accurate Signals-Only tracking. Detailed logging of pattern conditions is included for debugging. **Telegram Candle Table Fixed (Oct 17, 2025)**: Added candle detail fields (initiator_timestamp, initiator_open/close, confirm_high/low, EMA200) to return dict from `analyze()` method - now displays correctly in Telegram messages.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market states.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP. Includes divide-by-zero protection in variance calculations using `np.errstate()`.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching.

### Signal Scoring & Aggregation
- **Scoring Formula**: Combines base strategy score with market modifiers, including BTC filter and conflict resolution.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement with intelligent fallback and smart distance guard.
- **Trailing Stop-Loss with Partial TP**: Configurable profit management (e.g., 30% @ TP1, 40% @ TP2, 30% trailing).
- **Market Entry System**: All strategies execute MARKET orders.
- **Time Stops**: Exits trades if no progress.
- **Symbol Blocking System (Per-Strategy)**: Independent blocking.
- **Pump Scanner v1.4**: Advanced TradingView indicator with multiple threshold profiles, anti-needle/noise filters, HTF soft filter, FIT Clustering, Dynamic TR Relaxation, and Adaptive Air Threshold. Outputs JSON alerts.
- **Break & Retest Enhancements (Phase 1 COMPLETED - Oct 16, 2025)**: 
  - ✅ **HTF Trend Alignment with EMA200**: Strict 1H/4H EMA200 check (upgraded from EMA50) for trend confirmation in TREND regime. **CRITICAL BUG FIXED**: Initial implementation required ≥200 bars (blocked all trades), fixed with graceful degradation to EMA50 when <200 bars available (10 days = ~60 bars on 4H)
  - ✅ **Pin Bar & Engulfing Patterns**: Added candlestick pattern detection with quality score bonuses (+0.3 each) for stronger retest confirmation
  - ✅ **ATR-based Dynamic TP/SL**: Configurable option (`use_atr_based_tp_sl`) with multipliers (TP1=1.5×ATR, TP2=2.5×ATR, SL=1.0×ATR) adapts to volatility and solves TIME_STOP problem
  - ✅ **Volume Confirmation**: Adaptive volume thresholds per regime (TREND: 1.8×, SQUEEZE: 1.2×) filters weak breakouts
  - **Previous**: 3-Phase TREND Improvement System with ADX threshold, momentum, volume thresholds, bearish bias block, Bollinger Bands position, retest quality scoring, RSI momentum, and market structure validation
- **Volume Profile & Liquidity Sweep Enhancements (Phase 2 COMPLETED - Oct 16, 2025)**:
  - ✅ **Volume Profile - POC Magnet Filter**: Rejects rejection signals in RANGE/SQUEEZE when price >1.5 ATR from POC (price tends to revert to POC in range-bound markets)
  - ✅ **Volume Profile - Stricter Acceptance Logic**: Changed from OR to AND - requires BOTH CVD AND Volume Delta confirmation simultaneously for acceptance signals (higher quality)
  - ✅ **Liquidity Sweep - HTF Trend Alignment (1H EMA50)**: Fade signals require HTF against sweep direction (sweep up → HTF down), Continuation signals require HTF with sweep direction (sweep up → HTF up). Configurable via `use_htf_filter` (default: true). Gracefully skips when HTF data absent.
- **Multi-Factor Confirmation & Regime-Based Weighting (Phase 3 COMPLETED - Oct 16, 2025)**:
  - ✅ **Multi-Factor Confirmation System**: 6 factors (Strategy Signal, HTF Alignment, Volume Confirmation, CVD/DOI, Price Action Patterns, S/R Zone Confluence). Requires ≥3 factors for signal approval (configurable). Each factor adds bonus to score.
  - ✅ **Regime-Based Strategy Weighting**: TREND regime favors Break & Retest (1.5x) + MA/VWAP Pullback (1.3x). RANGE regime favors Volume Profile (1.5x) + Liquidity Sweep (1.3x). SQUEEZE regime favors Order Flow (1.5x). Strategies with weight <0.5 are blocked.
  - ✅ **Integrated in StrategyManager**: Both systems active in check_all_signals() - filters weak signals, applies regime weights, adds factor bonuses to score.
- **Action Price SL Filter**: Logs warnings for signals rejected due to excessively wide stop-loss, with a configurable `max_sl_percent` threshold (defaulted to 10.0%).

### Telegram Integration
- Provides commands for status, strategy details, performance, validation, latency, and Russian language signal alerts.
- Features a persistent button keyboard UI and message length protection.
- Includes commands for detailed Action Price signal analysis (`/closed_ap_sl`, `/closed_ap_tp`).
- **Action Price Signal Format (Oct 16, 2025)**: Enhanced with candle details table showing Initiator candle (timestamp, Open→Close, EMA200) and Confirming candle (timestamp, High-Low, EMA200) in structured table format below R:R. Timestamps converted to EEST timezone for readability.

### Logging System
- Separate log files for Main Bot and Action Price in `logs/` directory, using Europe/Kyiv timezone. Action Price signals are logged centrally to a single JSONL file.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, exit conditions, and PnL.
- **ActionPricePerformanceTracker**: Tracks Action Price signals, partial exits, breakeven logic, TP1/TP2, MFE/MAE, and JSONL logging.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and `enabled` flags.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe coordination.
- **Loader Task**: Loads historical data, retries on failure, pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols from the queue for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel loader/analyzer tasks, and launching the Telegram bot. Data is loaded in parallel for immediate analysis. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, running strategies, scoring signals, applying filters, and sending Telegram alerts. Persistence includes storing candles/trades in SQLite and logging signals.

## Error Handling & Resilience
- **Smart Rate Limiting**: 55% safety threshold to prevent API bans.
- **IP BAN Prevention v4**: Event-based coordination blocks pending requests.
- **Periodic Gap Refill with Request Weight Calculator**: Manages batch processing.
- **Burst Catchup Safety**: Checks rate usage after each batch.
- **Exponential Backoff**: Retry logic for transient errors.
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