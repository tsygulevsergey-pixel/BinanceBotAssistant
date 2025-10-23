# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot. Its primary purpose is to provide a high-performance, automated trading solution with a target of 80%+ Win Rate and a Profit Factor of 1.8-2.5. It integrates advanced trading strategies, real-time market regime detection, sophisticated risk management, and an "Action Price" system based on Support/Resistance, Anchored VWAP, and price action. The bot supports both Signals-Only and Live Trading Modes, focusing on precise signal generation, dynamic entry/exit management, and robust performance tracking to achieve consistent profitability.

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

### Market Data Infrastructure
- **BinanceClient**: Handles REST API with rate limiting.
- **DataLoader**: Manages historical candle data with parallel loading, data integrity, and smart freshness checks.
- **OrderBook**: Local engine synchronized via REST and WebSocket.
- **BinanceWebSocket**: Real-time market data streaming.
- **Smart Candle-Sync Main Loop**: Synchronizes signal checks to candle close times.

### Database Layer
- **Technology**: SQLAlchemy ORM with SQLite backend (WAL mode, indexed queries).
- **Performance Optimization**: Employs BULK UPSERT for candle persistence and composite unique indexing.

### Strategy Framework
- **BaseStrategy**: Abstract class for strategy definition.
- **StrategyManager**: Orchestrates strategy execution based on market regimes.
- **Signal Dataclass**: Standardized output for trading signals.
- **6 Core Strategies**: Liquidity Sweep, Break & Retest, Order Flow, MA/VWAP Pullback, Volume Profile, ATR Momentum.
- **Action Price System**: 11-component scoring for dynamic entry, TP, and SL.
- **Strategy Execution Optimization**: Parallelized strategy execution and independent Action Price processing.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market states.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for indicators.

### Signal Scoring & Aggregation
- Combines strategy scores with market modifiers, BTC filter, and conflict resolution, including multi-timeframe CVD divergence detection.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement.
- **Trailing Stop-Loss with Partial TP**: Configurable 3-Tier TP System.
- **Market Entry System**: All strategies execute MARKET orders.
- **Time Stops**: Exits trades if no progress.
- **Symbol Blocking System**: Independent blocking per strategy.
- **Action Price SL Filter**: Rejects signals with excessively wide stop-loss.

### Telegram Integration
- Provides commands for bot status, strategy details, performance, validation, and signal alerts with a persistent button keyboard UI.

### Logging System
- Features `Main Bot Log`, dedicated `Action Price Log`, `V3 S/R Log`, and `JSONL Logging` for centralized signal data. Supports configurable log levels, lazy initialization, and robust file handling.

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, exit conditions, and PnL.
- **ActionPricePerformanceTracker**: Tracks Action Price signals, partial exits, breakeven logic, MFE/MAE, and logs to JSONL.

### Configuration Management
- Uses YAML for strategy parameters and environment variables for API keys. Supports `signals_only_mode` and `enabled` flags.

## System Design Choices

### Data Flow
Loads configurations, connects to Binance, processes data in parallel, and launches the Telegram bot. Real-time operations involve WebSocket updates, market data processing, indicator calculation, parallel strategy execution, signal scoring, filtering, and Telegram alerts. Data is persisted in SQLite, and signals are logged.

### Error Handling & Resilience
- Implements `Smart Rate Limiting`, `IP BAN Prevention`, `Periodic Gap Refill`, `Burst Catchup Safety`, `Exponential Backoff`, `Auto-Reconnection` (WebSocket), `Graceful Shutdown`, and `Timeout Protection`.

## Feature Specifications

### V3 S/R Strategy System
- **Status**: PRODUCTION READY, fully integrated as an independent trading strategy.
- **Core Setups**: `Flip-Retest Setup` and `Sweep-Return Setup`.
- **Architecture**: Dedicated database tables, independent performance tracking with virtual partial exits and MFE/MAE, and a comprehensive signal scoring system based on zone quality.
- **Key Features**: VWAP Bias Filter, A-grade Exception, Zone Context, Market Regime Filtering, Adaptive SL/TP, and multi-timeframe analysis (15m/1H entry, 4H/1D context).
- **V3 Zones Infrastructure**: Utilizes DBSCAN-based clustering, reaction strength validation, and an optimized scoring system considering touches, reactions, freshness, confluence, and noise penalty. Includes adaptive fractal swing detection and volatility-based zone width. Zone building is parallelized.
- **Zone Quality Filters & Purity Gate**: Two-stage advanced filtering system: Outlier Removal, Width Guards, KDE Prominence Check, Purity Check, and Freshness Check.
- **V3 Zones Integration**: Break & Retest strategy now uses V3 professional S/R zones with a `Shared Zones Provider` for efficient caching, leading to enhanced retest zone detection and score bonuses for high-grade zones.
- **Dual-Timeframe Signal Generation System**:
  - **ZoneRegistry**: Shared zone state updated once per tick.
  - **BaseSignalEngine**: Common detection logic for Flip-Retest and Sweep-Return setups.
  - **SignalEngine_M15**: Scalp conveyor with 0.5% risk, 0.6 ATR/12 bars, SL +0.25 ATR, strict VWAP bias, enhanced confirmation in opposite H1 zones.
  - **SignalEngine_H1**: Swing conveyor with 1.0% risk, 0.7 ATR/8 bars, SL +0.3 ATR, optional VWAP bias with HTF confluence.
  - **CrossTFArbitrator**: Blocks M15 signals against opposite H1 direction, allows piggyback, per-TF locks, front-run protection.
  - **Legacy Format Conversion**: Ensures compatibility with existing tracking/statistics infrastructure.

# External Dependencies

## Exchange Integration
- **Binance Futures API**: REST endpoints for market and account data.
- **Binance WebSocket**: Real-time market data streams.
- **Binance Vision**: Historical data archive.

## Third-Party Services
- **Telegram Bot API**: For message delivery and interactive commands.

## Python Libraries
- **Data Processing**: pandas, numpy, pandas-ta.
- **Network**: aiohttp, websockets.
- **Database**: SQLAlchemy, Alembic.
- **Exchange**: python-binance, ccxt.
- **Scheduling**: APScheduler.
- **Configuration**: pyyaml, python-dotenv.