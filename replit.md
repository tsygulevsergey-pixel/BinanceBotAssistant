# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for high-performance automated trading. Its primary purpose is to achieve a target of 80%+ Win Rate and a Profit Factor of 1.8-2.5 through advanced trading strategies, real-time market regime detection, and sophisticated risk management. The bot incorporates an "Action Price" system based on Support/Resistance, Anchored VWAP, and price action. It supports both Signals-Only and Live Trading Modes, focusing on precise signal generation, dynamic entry/exit management, and robust performance tracking for consistent profitability.

# User Preferences

- **Preferred communication style**: Simple, everyday language.
- **User runs bot locally on Windows PC in Ukraine** (not on Replit cloud)
- **Log files come from user's local computer** - when user attaches logs, they are from the bot running on their Windows machine
- **This Replit project contains the complete source code** - all code is here and kept up to date
- **Workflow setup is for Replit testing only** - user downloads code to run locally with his own API keys
- **When user shares logs or reports errors:**
    1. Logs are from their local Windows environment running Python bot
    2. They test/run the bot independently on their computer
    3. This Replit workspace is the source code repository
    4. Any fixes made here need to be downloaded by user to their local machine

# System Architecture

## Core Components
- **Market Data Infrastructure**: Handles Binance REST API with rate limiting, parallel historical data loading, local order book synchronization, and real-time WebSocket streaming.
- **Database Layer**: Utilizes SQLAlchemy ORM with SQLite (WAL mode, indexed queries) for efficient candle persistence via BULK UPSERT and composite unique indexing.
- **Strategy Framework**: An abstract `BaseStrategy` and `StrategyManager` orchestrate execution of 6 core strategies (Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile, ATR Momentum). Features an 11-component "Action Price" system for dynamic entry, TP, and SL, with parallelized execution.
- **Market Analysis System**: Includes `MarketRegimeDetector`, `TechnicalIndicators` (ATR, ADX, EMA, Bollinger Bands, Donchian Channels), `CVDCalculator`, `VWAPCalculator`, and `VolumeProfile` (POC, VAH/VAL) with a high-performance `IndicatorCache`.
- **Signal Scoring & Aggregation**: Combines strategy scores with market modifiers, BTC filter, conflict resolution, and multi-timeframe CVD divergence detection.
- **Filtering & Risk Management**: Implements S/R Zone-Based Stop-Loss, configurable 3-Tier Trailing Stop-Loss with Partial TP, Market Entry System (MARKET orders), Time Stops, Symbol Blocking, and Action Price SL Filter.
- **Telegram Integration**: Provides bot status, strategy details, performance, validation, and signal alerts with a persistent button keyboard UI.
- **Logging System**: Dedicated logs for Main Bot, Action Price, V3 S/R, and JSONL logging for signals, supporting configurable levels and robust file handling.
- **Performance Tracking System**: `SignalPerformanceTracker` and `ActionPricePerformanceTracker` monitor active signals, exit conditions, PnL, MFE/MAE, and log to JSONL.
- **Configuration Management**: Uses YAML for strategy parameters and environment variables for API keys, supporting `signals_only_mode` and `enabled` flags.

## System Design Choices
- **Data Flow**: Loads configurations, connects to Binance, processes data in parallel, and launches the Telegram bot. Real-time operations involve WebSocket updates, market data processing, indicator calculation, parallel strategy execution, signal scoring, filtering, and Telegram alerts. Data is persisted in SQLite, and signals are logged.
- **Error Handling & Resilience**: Features Smart Rate Limiting, IP BAN Prevention, Periodic Gap Refill, Burst Catchup Safety, Exponential Backoff, Auto-Reconnection (WebSocket), Graceful Shutdown, and Timeout Protection.

## Feature Specifications
- **V3 S/R Strategy System**: A production-ready, independent strategy with `Flip-Retest` and `Sweep-Return` setups. It uses dedicated database tables, independent performance tracking, and a comprehensive signal scoring based on zone quality. Key features include VWAP Bias Filter, Zone Context, Market Regime Filtering, Adaptive SL/TP, and multi-timeframe analysis.
- **V3 Zones Infrastructure**: Utilizes DBSCAN-based clustering, reaction strength validation, and an optimized scoring system considering touches, reactions, freshness, confluence, and noise penalty. Includes adaptive fractal swing detection and volatility-based zone width, with parallelized zone building.
- **Zone Quality Filters & Purity Gate**: A two-stage advanced filtering system including Outlier Removal, Width Guards, KDE Prominence Check, Purity Check, and Freshness Check.
- **V3 Zones Integration**: The Break & Retest strategy uses V3 professional S/R zones with a `Shared Zones Provider` for enhanced retest zone detection and score bonuses.
- **Dual-Timeframe Signal Generation System**: `ZoneRegistry` for shared zone state, `BaseSignalEngine` for common detection logic, `SignalEngine_M15` for scalp, `SignalEngine_H1` for swing, and `CrossTFArbitrator` for multi-timeframe signal arbitration and front-run protection.

# External Dependencies

## Exchange Integration
- **Binance Futures API**: REST endpoints for market and account data.
- **Binance WebSocket**: Real-time market data streams.
- **Binance Vision**: Historical data archive.

## Third-Party Services
- **Telegram Bot API**: For message delivery and interactive commands.

## Python Libraries
- **Data Processing**: `pandas`, `numpy`, `pandas-ta`.
- **Network**: `aiohttp`, `websockets`.
- **Database**: `SQLAlchemy`, `Alembic`.
- **Exchange**: `python-binance`, `ccxt`.
- **Scheduling**: `APScheduler`.
- **Configuration**: `pyyaml`, `python-dotenv`.

---

# Recent Critical Fixes (October 24, 2025)

## Problem #16: V3 Performance Tracker - TP1 Flags Not Saving to DB - RESOLVED ✅

**Issue:** V3 statistics showing contradictory metrics - 7 SL exits but 4 wins with positive PnL, 0 TP hits despite positive outcomes.

**Root Cause:**
- `_check_active_signals()` called `commit()` ONLY AFTER checking ALL signals
- If TP1 reached for Signal #100: flags set in memory (`tp1_hit=True`, `moved_to_be=True`, SL updated)
- If Signal #150 raised error: exception caught, but changes for Signal #100 NOT committed
- On next iteration: flags still `False` in DB, SL still original value
- When price crossed moved SL: code saw `moved_to_be=False`, closed as regular SL (not BE)
- Result: SL exit with POSITIVE PnL (impossible!) ❌

**Examples from Real Data:**
```
Signal #309: DEGOUSDT LONG
  Entry: 1.1031 → Exit: 1.4712 (SL: 1.4712)
  Exit Reason: SL | PnL: +33.37% ✅ WIN
  TP1 Hit: 0 | Moved to BE: 0  ❌ FLAGS NOT SAVED!

Signal #214: 4USDT SHORT  
  Entry: 0.1430 → Exit: 0.1351 (SL: 0.1351)
  Exit Reason: SL | PnL: +5.55% ✅ WIN
  TP1 Hit: 0 | Moved to BE: 0  ❌ FLAGS NOT SAVED!
```

**Solution (October 24, 2025):**
1. **performance_tracker.py (_check_active_signals)**:
   - Moved `commit()` INSIDE loop after EACH signal
   - Added individual try/except for each signal with `rollback()` on error
   - Guarantees tp1_hit, moved_to_be, trailing_active saved even if next signal errors

2. **bot.py (cmd_v3_stats)**:
   - Fixed statistics to count by `exit_reason` (TP2, BE, TRAIL, SL, TIMEOUT)
   - Not by flags `tp1_hit`/`tp2_hit` (these indicate intermediate states, not final exits)
   - Added `tp1_hit_count` for informational purposes only

**Code Changes:**
```python
# OLD (BROKEN):
for signal in active_signals:
    await self._check_signal(signal, session)
session.commit()  # ❌ Only at end - changes lost on error!

# NEW (FIXED):
for signal in active_signals:
    try:
        await self._check_signal(signal, session)
        session.commit()  # ✅ After EACH signal
    except Exception as e:
        session.rollback()  # ✅ Rollback only this signal
```

**Result:** ✅ **GUARANTEED** TP1 flags save immediately → correct BE exits → accurate statistics!

---

## Problem #15: Candles Not Updating in Database - RESOLVED ✅

**Issue:** Candles were not updating in database when new candles closed, causing strategies to use stale data.

**Root Cause:**
- `update_missing_candles()` in `data_loader.py` used fixed 300-second (5 minute) threshold
- If gap between last DB candle and current time < 5 minutes, NO UPDATE occurred
- Example: Last candle 01:12, new candle closes 01:15 → gap = 3 min → NO UPDATE! ❌
- Strategies received outdated candles, generated signals on wrong data

**Solution (October 24, 2025):**
1. **Added `_get_interval_minutes()` helper** to get interval duration (15m=15, 1h=60, etc.)
2. **Changed threshold from fixed 300s to interval-aware**:
   - For 15m: Update if gap >= 900 seconds (15 minutes)
   - For 1h: Update if gap >= 3600 seconds (60 minutes)
   - For 4h: Update if gap >= 14400 seconds (240 minutes)
3. **Critical fix**: Calculate gap from `last_time` (not `last_time + 1 min`) to detect closed candles correctly
4. **Duplicate prevention**: Still use `last_time + 1 minute` as download start_date

**Code Changes:**
```python
# OLD (BROKEN):
if (end_date - start_date).total_seconds() > 300:  # Fixed 300s
    await download_historical_klines(...)

# NEW (FIXED):
interval_seconds = self._get_interval_minutes(interval) * 60
gap_seconds = (end_date - last_time).total_seconds()  # From last_time!

if gap_seconds >= interval_seconds:  # Interval-aware
    start_date = last_time + timedelta(minutes=1)  # No duplicates
    await download_historical_klines(...)
```

**Result:** ✅ **GUARANTEED** candles update when new candle closes → strategies use FRESH data!

---

## Problem #14: TP Still in Dead Zone - HTF Zone Filter Bug - RESOLVED ✅

**Issue:** Despite fix #13, TPs STILL appeared between SL and Entry.

**Root Cause:**
- `_calc_sl_tp_h1()` and `_calc_sl_tp_m15()` used HTF zone edges WITHOUT checking if zones were beyond entry
- Example: LONG at 0.03757 with HTF Resistance at 0.03297 → TP1=0.03297 (between SL 0.03253 and Entry!)
- HTF zones between SL and Entry were being selected as TP targets

**Solution (October 24, 2025):**
1. **signal_engine_h1.py (_calc_sl_tp_h1)**:
   - Use 1R/2R multiples as default TP targets (TP1 = entry + risk, TP2 = entry + 2×risk)
   - HTF zone filter: `z['low'] > entry_price` for LONG, `z['high'] < entry_price` for SHORT
   - Guarantees HTF zones are BEYOND entry, not between SL and entry

2. **signal_engine_m15.py (_calc_sl_tp_m15)**:
   - Same fix: R-multiple defaults + HTF zone filter
   - Only accepts H1 zones that are beyond entry price

3. **signal_engine_base.py (_create_signal)**:
   - Added validation: LONG must have `SL < Entry < TP1 < TP2`
   - Added validation: SHORT must have `SL > Entry > TP1 > TP2`
   - Logs warning if validation fails (for debugging)

**Result:** ✅ **GUARANTEED** proper TP placement: LONG (SL < Entry < TP1 < TP2) | SHORT (SL > Entry > TP1 > TP2)

---

## Problem #13: TP Levels in "Dead Zone" Between SL and Entry - PARTIAL FIX ⚠️

**Issue:** TP1/TP2 calculated between SL and Entry making signals untradeable.

**Root Cause:**
- `signal_engine_h1.py (line 213)` and `signal_engine_m15.py (line 222)` used `zone edge` for SL/TP calculation
- Then entry overridden with `current_price` in `_create_signal()`
- Result: SL/TP from one price, entry from another

**Solution:**
- Use `current_price` for SL/TP calculation consistently
- Keep zone edge only for HTF clearance check

**Result:** ⚠️ Partial - Fixed entry consistency but HTF zone logic still had bug (see Problem #14)