# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot, designed for high-performance trading with an emphasis on quality strategies, market regime detection, and advanced risk management. It implements 5 core trading strategies and operates in both Signals-Only and Live Trading Modes. The bot aims for an 80%+ Win Rate and a Profit Factor of 1.8-2.5 by utilizing an "Action Price" system based on Support/Resistance (S/R) zones, Anchored VWAP, and price action patterns. An experimental "Gluk System" is also integrated to replicate a high-win-rate legacy Action Price implementation.

# User Preferences

Preferred communication style: Simple, everyday language.

# Recent Analysis (Oct 18, 2025)

## Action Price Critical Findings

### Current Performance (28 trades, Oct 16-18):
- **Win Rate:** 28.6% pure, 46.4% with BE
- **Profit Factor:** 0.98 (almost break-even)
- **Results:** 8 wins (TP1/TP2), 15 losses (SL), 5 BE
- **Key Issue:** 53.6% trades hit Stop Loss

### CRITICAL PROBLEM: Inverted Scoring System
**PARADOX:** Higher score = Higher loss probability
- **Winners avg score:** 3.6
- **Losers avg score:** 5.5 (53% higher!)

**Problematic Components (losers score higher):**
- `confirm_depth`: losers=1.57 vs winners=1.11 (+41%) - rewards distance from EMA200
- `gap_to_atr`: losers=0.86 vs winners=0.67 (+28%) - rewards extremes
- `close_position`: losers=0.76 vs winners=0.11 (+590%) - rewards overbought/oversold
- `ema_fan`: losers=0.29 vs winners=0.00 - wider spread = worse

**Root Cause:** System rewards characteristics that predict reversals (overbought/oversold extremes) instead of sustainable breakouts.

### Missing Best Practices (from 75-85% WR strategies):
1. **No Pullback/Retest Requirement** - enters immediately after breakout (catches end of impulse)
2. **Entry Timing** - enters when price is FAR from EMA200, guaranteeing retracement
3. **Volume Confirmation** - not used at all
4. **Dynamic ATR Stops** - SL capped at max_sl_percent=10%, too tight for volatile coins
5. **Trend Strength Filter** - ADX threshold=14 too low (should be 25+)
6. **Proximity Scoring** - should reward CLOSENESS to EMA200, not distance

### Recommended Fixes (Priority Order):
1. **Invert proximity scoring** - penalize distance from EMA200, reward closeness
2. **Add pullback requirement** - wait for retest before entry
3. **Dynamic SL** - remove or adapt max_sl_percent based on volatility
4. **Volume filter** - breakout volume > avg, pullback volume < breakout
5. **Raise ADX threshold** - 14 → 25 (filter out ranging markets)
6. **Rebalance weights** - raise score_standard_min to 6.0, strengthen lipuchka penalty

### Expected Improvements:
- Phase 1 (scoring fixes): 28.6% → 40-45% WR
- Phase 2 (pullback + dynamic SL): 45% → 55-65% WR  
- Phase 3 (advanced filters): 65% → 70-80% WR
- Target Profit Factor: 2.0-2.5

## Action Price Improvement Roadmap (Oct 18, 2025)

### ✅ PHASE 1: Scoring System Inversion (COMPLETED)
**Goal:** Fix inverted scoring logic that rewards overbought/oversold extremes instead of quality setups.

**Changes Implemented:**
1. **confirm_depth** (INVERTED):
   - OLD: depth_atr >= 0.40 = +2 points (far from EMA200 = GOOD) ❌
   - NEW: depth_atr < 0.30 = +2 points (close to EMA200 = GOOD) ✅
   - Rationale: Close proximity to EMA200 = fresh breakout with lower retracement risk

2. **gap_to_atr** → **overextension_penalty** (INVERTED):
   - OLD: close to ATR extreme = +1 point (overbought/oversold = GOOD) ❌
   - NEW: close to ATR extreme = -2 points (overbought/oversold = BAD) ✅
   - Rationale: Entering at price extremes = catching end of impulse

3. **close_position** (DISABLED):
   - OLD: close > all EMAs = +1 point (extreme overbought = GOOD) ❌
   - NEW: always 0 (disabled until Phase 2 redesign) ✅
   - Rationale: Component rewarded worst entry timing

4. **ema_fan** (DISABLED):
   - OLD: wide EMA spread = +1 point (extended trend = GOOD) ❌
   - NEW: always 0 (disabled until Phase 2 redesign) ✅
   - Rationale: Wide EMA fan = late trend entry

5. **lipuchka** (STRENGTHENED):
   - OLD: 3+ touches = -1 point
   - NEW: 3+ touches = -2 points ✅
   - Rationale: Multiple EMA200 touches = weak breakout

6. **Quality Components** (WEIGHTS x2):
   - retest_tag: +1 → +2 (pullback = 2025 best practice)
   - break_and_base: +1 → +2 (consolidation = strong signal)
   - initiator_wick: +1 → +2 (rejection wick = strong reversal)

7. **min_total_score** (RAISED):
   - OLD: 5.0
   - NEW: 6.0 ✅
   - Rationale: Filter out weaker signals

**Expected Results:**
- Win Rate: 28.6% → 40-45%
- Profit Factor: 0.98 → 1.2-1.5
- Signals will favor: close EMA200 proximity, pullback entries, rejection wicks

### 🔄 PHASE 2: Entry Timing & Dynamic Risk (PLANNED)
**Goal:** Add pullback/retest logic + dynamic ATR-based stops (aligned with 2025 professional practices)

**Planned Changes:**
1. **Pullback/Retest System** (60-70% WR in 2025 studies):
   - Immediate entry IF: depth_atr < 1.5 ATR (not extended)
   - Wait for pullback IF: 1.5 < depth_atr < 2.5 ATR
   - Skip IF: depth_atr > 2.5 ATR (too far, high reversal risk)
   - Pullback criteria: price touches EMA13/21, then resumes trend

2. **Dynamic ATR Stops**:
   - Remove max_sl_percent cap (or raise to 15%)
   - SL = initiator_low - (1.5-2.5 × ATR) based on volatility
   - Adaptive to coin volatility (BTC 2% vs altcoins 8%)

3. **Volume Confirmation**:
   - Breakout volume > 1.2× average
   - Pullback volume < breakout volume (healthy retest)

4. **Redesign close_position**:
   - Reward: close between EMA13-EMA200 (healthy pullback zone)
   - Penalize: close beyond all EMAs (overbought)

5. **Redesign ema_fan**:
   - Reward: compact EMA alignment (early trend)
   - Penalize: wide spread (late trend)

**Expected Results:**
- Win Rate: 45% → 55-65%
- Profit Factor: 1.5 → 1.8-2.2
- Reduced premature stop-outs, better entry prices

### 🎯 PHASE 3: Advanced Filters & Multi-Confirmation (PLANNED)
**Goal:** Add professional-grade filters to reach 70-80% WR target

**Planned Changes:**
1. **ADX Filter Strengthening**:
   - Raise threshold: 14 → 25 (filter out ranging markets)
   - Only trade strong trends (ADX > 25 = confirmed trend)

2. **Multi-Timeframe Confirmation**:
   - HTF (1H/4H) trend must align with 15m signal
   - Use HTF EMA200 as additional filter

3. **VWAP Integration** (NEW - from 2025 research):
   - Institutional flow confirmation
   - Long only if price > VWAP (buying pressure)
   - Bonus for VWAP convergence with EMA200

4. **Position Stacking Prevention**:
   - Max 1 open signal per symbol (prevent over-concentration)
   - Cooldown enhancement

5. **Time-of-Day Filter**:
   - Avoid low-liquidity periods (UTC 0-4)
   - Focus on high-volume sessions

**Expected Results:**
- Win Rate: 65% → 70-80%
- Profit Factor: 2.0 → 2.5+
- Fewer but higher-quality signals

### 📊 Research Validation (2025 Professional Sources)
All improvements validated against current industry best practices:
- Pullback/retest preferred: 60-70% WR (Medium, TradingView, CMC Markets 2025)
- Dynamic ATR stops: Industry standard (NinjaTrader, Flipster 2025)
- ADX >25 filter: Trending market requirement (StockCharts, altFINS 2025)
- Multi-confirmation: EMA + RSI + VWAP + ADX (Advanced strategies 2025)
- Max 2% risk per trade: Universal professional standard

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: REST API client with rate limiting and exponential backoff.
- **DataLoader**: Fetches and manages historical candle data, ensuring accuracy by updating existing records and filtering out unclosed candles.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket.
- **BinanceWebSocket**: Real-time market data streaming.
- **Smart Candle-Sync Main Loop**: Synchronizes signal checks precisely to candle close times for fresh data analysis.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries).

### Strategy Framework
- **BaseStrategy**: Abstract class for all trading strategies.
- **StrategyManager**: Orchestrates strategy execution based on market regimes.
- **Signal Dataclass**: Standardized output for trading signals.
- **5 CORE STRATEGIES**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile.
- **Action Price System**: An 11-component scoring system based on EMA200 Body Cross logic, with dynamic entry, take-profit, and stop-loss calculations. Processes only fully closed 15m candles.
- **Gluk System**: An experimental, isolated implementation of a legacy Action Price system that uses unclosed candle data to replicate a previously observed high win rate.

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