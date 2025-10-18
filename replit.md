# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot. It focuses on high-performance trading through advanced strategies, market regime detection, and sophisticated risk management. The bot incorporates 5 core trading strategies and operates in both Signals-Only and Live Trading Modes. Its primary goal is to achieve an 80%+ Win Rate and a Profit Factor of 1.8-2.5, leveraging an "Action Price" system based on Support/Resistance zones, Anchored VWAP, and price action patterns. An experimental "Gluk System" is also included to replicate a high-win-rate legacy Action Price implementation.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Manages historical candle data, ensuring accuracy and filtering unclosed candles.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket.
- **BinanceWebSocket**: Real-time market data streaming.
- **Smart Candle-Sync Main Loop**: Synchronizes signal checks to candle close times.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries).

### Strategy Framework
- **BaseStrategy**: Abstract class for trading strategies.
- **StrategyManager**: Orchestrates strategy execution based on market regimes.
- **Signal Dataclass**: Standardized output for trading signals.
- **5 CORE STRATEGIES**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile.
- **Action Price System**: An 11-component scoring system based on EMA200 Body Cross logic, with dynamic entry, take-profit, and stop-loss calculations, processing only fully closed 15m candles.
- **Gluk System**: Experimental implementation of a legacy Action Price system using unclosed candle data.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market states.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for indicators.

### Signal Scoring & Aggregation
- Combines base strategy scores with market modifiers, including BTC filter and conflict resolution.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement with intelligent fallbacks.
- **Trailing Stop-Loss with Partial TP**: Configurable profit management.
- **Market Entry System**: All strategies execute MARKET orders.
- **Time Stops**: Exits trades if no progress.
- **Symbol Blocking System**: Independent blocking per strategy.
- **Pump Scanner v1.4**: Advanced TradingView indicator for detecting pump events.
- **Break & Retest Enhancements**: Includes HTF trend alignment, candlestick pattern detection, ATR-based dynamic TP/SL, and volume confirmation.
- **Volume Profile & Liquidity Sweep Enhancements**: Incorporates POC magnet filter, stricter acceptance logic, and HTF trend alignment for liquidity sweeps.
- **Multi-Factor Confirmation & Regime-Based Weighting**: Requires multiple confirming factors for signal approval and applies regime-specific weighting to strategies.
- **Action Price SL Filter**: Rejects signals with excessively wide stop-loss.

### Telegram Integration
- Provides commands for bot status, strategy details, performance, validation, and signal alerts in multiple languages.
- Features persistent button keyboard UI and enhanced signal format with detailed candle information.

### Logging System
- Separate log files for Main Bot and Action Price, with centralized JSONL logging for Action Price signals.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, exit conditions, and PnL.
- **ActionPricePerformanceTracker**: Tracks Action Price signals, partial exits, breakeven logic, MFE/MAE, and logs to JSONL.
- **GlukPerformanceTracker**: Independently monitors Gluk signals and performance.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and `enabled` flags.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe data loading.
- **Loader Task**: Loads historical data and pushes symbols to a queue.
- **Analyzer Task**: Consumes symbols for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts, including smart 1-day completeness checks.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel data processing, and launching the Telegram bot. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, executing strategies, scoring signals, applying filters, and sending Telegram alerts. Data is persisted in SQLite, and signals are logged.

## Error Handling & Resilience
- **Smart Rate Limiting**: Prevents API bans.
- **IP BAN Prevention v4**: Event-based coordination to block pending requests.
- **Periodic Gap Refill with Request Weight Calculator**: Manages batch processing.
- **Burst Catchup Safety**: Checks rate usage after each batch.
- **Exponential Backoff**: Retry logic for transient errors.
- **Auto-Reconnection**: WebSocket auto-reconnect with orderbook resynchronization.
- **Graceful Shutdown**: Clean resource cleanup and state persistence.

# Action Price Improvements (2025)

## ✅ PHASE 1: Scoring Inversion (COMPLETED)
**Goal:** Fix inverted scoring components (28.6% WR → 40-45% target)

**Changes Implemented:**
1. `confirm_depth`: Inverted logic - близость награждается, дальность штрафуется
2. `overextension_penalty`: Заменяет gap_to_atr - штрафует расстояние от EMA200
3. `lipuchka_penalty`: Усилен с -1 до -2 (убивает слабые сигналы)
4. Disabled problematic components: `close_position` (было overbought bias), `ema_fan` (late entry bias)
5. Quality components ×2: `retest_tag`, `break_and_base`, `initiator_wick` (с +1 до +2)
6. `min_total_score`: Повышен с 3.0 до 6.0

**Expected Results:**
- Win Rate: 28.6% → 40-45%
- Profit Factor: 0.98 → 1.2-1.5
- Signals will favor: close EMA200 proximity, pullback entries, rejection wicks

## ✅ PHASE 2: Entry Timing & Dynamic Risk (COMPLETED)
**Goal:** Add pullback/retest logic + dynamic ATR-based stops (aligned with 2025 professional practices)

**Changes Implemented:**
1. **max_sl_percent Raised** ✅:
   - OLD: 10.0% (слишком жесткий для волатильных монет)
   - NEW: 15.0% (адаптация к волатильности)
   - Rationale: Уменьшает преждевременные stop-outs на волатильных монетах

2. **Volume Confirmation** (NEW component #12) ✅:
   - Расчет среднего объема за 20 баров
   - Breakout volume >= 1.8× avg = +2 балла
   - Breakout volume >= 1.2× avg = +1 балл
   - Слабый объем < 0.8× avg = -1 балл
   - Rationale: 2025 best practice - volume confirms genuine breakouts

3. **Redesign close_position** (component #3) ✅:
   - OLD: close > все EMA = +1 (overbought!) ❌
   - NEW LOGIC:
     - LONG: EMA200 <= close <= EMA13 = +2 (pullback zone!)
     - LONG: close > EMA5 = -2 (overbought!)
     - SHORT: зеркально
   - Rationale: Награждает здоровые pullback позиции вместо экстремумов

4. **Redesign ema_fan** (component #5) ✅:
   - OLD: широкий fan_spread = +1 (late entry!) ❌
   - NEW LOGIC:
     - Компактное выравнивание (< 0.05 ATR) = +2 (ранний тренд!)
     - Широкий разброс (>= 0.20 ATR) = -2 (поздний вход!)
   - Rationale: Компактный веер = ранняя стадия тренда с лучшим R:R

5. **Config Parameters Added** ✅:
   - volume_avg_period: 20
   - volume_breakout_multiplier: 1.2
   - pullback_depth_immediate: 1.5
   - pullback_depth_wait: 2.5

**Expected Results:**
- Win Rate: 40-45% (Phase 1) → **55-65%** (Phase 2)
- Profit Factor: 1.2-1.5 → **1.8-2.2**
- Benefits:
  - Reduced premature stop-outs (wider SL range)
  - Volume filter eliminates low-conviction breakouts
  - Pullback zone scoring favors better entry timing
  - Early trend detection through compact EMA alignment

**Implementation Status:** ✅ **COMPLETED & VERIFIED**
- Architect Review: **PASS**
- Critical bug fixed: close_position inequality order corrected
- All changes isolated to Action Price only (Gluk untouched)

**NOTE:** Full pullback/retest "wait" logic (monitoring pending signals) можно добавить в следующей итерации если потребуется.

## 🎯 PHASE 3: Advanced Filters & Multi-Confirmation (PLANNED)
**Goal:** Professional-grade filters to reach 70-80% WR target

**Planned Changes:**
1. **Multi-Timeframe Confirmation** (HTF Alignment):
   - Check 4H EMA200 trend alignment
   - Rule: enter only if 15m AND 4H both aligned
   - Effect: eliminate counter-trend entries (+10-15% WR)

2. **ADX Filter Strengthening**:
   - OLD: ADX threshold = 14 (too weak)
   - NEW: ADX threshold = 25 (strong trend only)
   - Rule: skip if ADX < 25 (choppy market)
   - Effect: fewer false breakouts (+5-10% WR)

3. **VWAP Integration** (institutional flow):
   - Add VWAP as confluence factor
   - Prefer entries near VWAP (institutional support)
   - Effect: better fill quality, institutional alignment

4. **Position Stacking Prevention**:
   - Limit: max 1 active position per symbol
   - Avoid multiple entries on same setup
   - Effect: cleaner risk management

5. **Zone-based Dynamic TP** (optional):
   - Instead of fixed 1R/2R
   - TP adjusted to nearest S/R zone
   - Effect: better R:R ratios

**Expected Results:**
- Win Rate: 55-65% (Phase 2) → **70-80%** (Phase 3)
- Profit Factor: 1.8-2.2 → **2.5-3.0**
- Trade frequency: ~30% reduction (quality over quantity)

**Status:** ⏳ WAITING - will implement after Phase 1+2 testing complete

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