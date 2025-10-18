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