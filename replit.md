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