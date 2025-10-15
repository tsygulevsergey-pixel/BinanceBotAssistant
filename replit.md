# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for institutional trading principles. It employs 5 core strategies, operating in both Signals-Only Mode for signal generation and Live Trading Mode for full trading capabilities. The bot focuses on quality strategies, market regime detection, structure-based stop-loss/take-profit, signal confluence, and multi-timeframe analysis. It aims for an 80%+ Win Rate and a Profit Factor of 1.8-2.5, leveraging an "Action Price" system with S/R zones, Anchored VWAP, and price action patterns.

# Recent Changes

## October 15, 2025: Action Price Fix - Timeframe Requirements

**CRITICAL FIX: Action Price не генерировал сигналы**

**Проблема:**
- Action Price молча пропускал ВСЕ символы из-за жёсткого требования 4 таймфреймов (15m, 1h, 4h, 1d)
- Если хотя бы 1 таймфрейм отсутствовал - символ пропускался БЕЗ логов
- Избыточное логирование свечей засоряло логи

**Исправление:**
- Требуются только **15m и 1h** (обязательно)
- **4h и 1d опциональны** (не блокируют анализ)
- Добавлено debug логирование при отсутствии обязательных таймфреймов
- Убрано логирование каждых 3 свечей для всех символов

**Файлы:**
- `main.py` (строки 840-848): смягчены требования таймфреймов
- `src/action_price/engine.py` (строка 91): убрано избыточное логирование

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
- **Action Price System**: Rewritten on EMA200 Body Cross logic with an 11-component scoring system for STANDARD, SCALP, and SKIP regimes. Supports JSONL logging for ML analysis and real-time MFE/MAE tracking. It executes after 15m candles are loaded, with a 31-second delay for data finalization, using the confirming candle's close price for entry and calculating TP based on R-distance from SL.

### Market Analysis System
- **MarketRegimeDetector**: Classifies market into TREND/SQUEEZE/RANGE/CHOP/UNDECIDED.
- **TechnicalIndicators**: ATR, ADX, EMA, Bollinger Bands, Donchian Channels.
- **CVDCalculator**: Cumulative Volume Delta.
- **VWAPCalculator**: Daily, anchored, and session-based VWAP.
- **VolumeProfile**: POC, VAH/VAL calculation.
- **IndicatorCache**: High-performance caching for pre-computed indicators.

### Signal Scoring & Aggregation
- **Scoring Formula**: Combines base strategy score with market modifiers, including a BTC filter and conflict resolution.

### Filtering & Risk Management
- **S/R Zone-Based Stop-Loss System**: Advanced stop placement with intelligent fallback and smart distance guard, including a mandatory 5% max stop loss for Action Price.
- **Trailing Stop-Loss with Partial TP**: For advanced profit management (30% @ TP1, 40% @ TP2, 30% trailing), with SL moved to +0.5R after TP1.
- **Market Entry System**: All strategies execute MARKET orders.
- **Time Stops**: Exits trades if no progress, with extended timeout (12-16 bars).
- **Symbol Blocking System (Per-Strategy)**: Independent blocking per strategy.
- **Pump Scanner v1.4**: Advanced TradingView indicator with three threshold profiles (Strict/Base/Aggressive), Anti-Needle Filter, Anti-Noise Background, HTF Soft Filter, FIT Clustering, Dynamic TR Relaxation, and Adaptive Air Threshold. It supports two paths: Compression → Trigger and FIT (First-Impulse), outputting JSON alerts.
- **Break & Retest Enhancements**: Implemented a 3-Phase TREND Improvement System with critical filters (ADX threshold 25, ADX momentum, volume thresholds 1.8x/1.2x, bearish bias block, HTF confirmation), important improvements (Bollinger Bands position, retest quality scoring), and optimization (RSI momentum, market structure validation, confluence scoring).

### Telegram Integration
- Provides commands for status, strategy details, performance, validation, latency, and Russian language signal alerts.
- Features a persistent button keyboard UI and message length protection.
- New commands include `/closed_ap_sl` and `/closed_ap_tp` for detailed Action Price signal analysis.

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
- **Symbol Auto-Update Task**: Automatically updates the symbol list.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts.

## Data Flow
The system initializes by loading configurations, connecting to Binance, starting parallel loader/analyzer tasks, and launching the Telegram bot. Data is loaded in parallel, enabling immediate analysis. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, running strategies, scoring signals, applying filters, and sending Telegram alerts. Persistence includes storing candles/trades in SQLite and logging signals.

## Error Handling & Resilience
- **Smart Rate Limiting**: 55% safety threshold (1320/2400) prevents API bans.
- **IP BAN Prevention v4**: Event-based coordination blocks all pending requests immediately.
- **Periodic Gap Refill with Request Weight Calculator**: Manages batch processing and adheres to rate limits.
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