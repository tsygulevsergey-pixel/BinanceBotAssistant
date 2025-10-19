# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for high-performance trading with an 80%+ Win Rate and a Profit Factor of 1.8-2.5. It employs advanced strategies, market regime detection, sophisticated risk management, and an "Action Price" system based on Support/Resistance, Anchored VWAP, and price action. The bot supports both Signals-Only and Live Trading Modes.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Components

### Market Data Infrastructure
- **BinanceClient**: Handles REST API interactions with rate limiting and exponential backoff.
- **DataLoader**: Manages historical candle data.
- **OrderBook**: Local engine synchronized via REST snapshots and WebSocket.
- **BinanceWebSocket**: Real-time market data streaming.
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
- **Trailing Stop-Loss with Partial TP**: Configurable profit management (3-Tier TP System: 30% @1R, 40% @1.5R/2R, 30% trailing).
- **Market Entry System**: All strategies execute MARKET orders.
- **Time Stops**: Exits trades if no progress.
- **Symbol Blocking System**: Independent blocking per strategy.
- **Action Price SL Filter**: Rejects signals with excessively wide stop-loss.

### Telegram Integration
- Provides commands for bot status, strategy details, performance, validation, and signal alerts with a persistent button keyboard UI.

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
- **Parallel Strategy Checks**: Regular strategies execute in parallel batches using asyncio.gather.
- **Independent Execution**: Action Price system runs independently.

## Data Flow
The system loads configurations, connects to Binance, starts parallel data processing, and launches the Telegram bot. Real-time operations involve processing WebSocket updates, updating market data, calculating indicators, executing strategies in parallel, scoring signals, applying filters, and sending Telegram alerts. Data is persisted in SQLite, and signals are logged.

## Error Handling & Resilience
- **Smart Rate Limiting**: Prevents API bans.
- **IP BAN Prevention**: Event-based coordination to block pending requests.
- **Periodic Gap Refill with Request Weight Calculator**: Manages batch processing.
- **Burst Catchup Safety**: Checks rate usage after each batch.
- **Exponential Backoff**: Retry logic for transient errors.
- **Auto-Reconnection**: WebSocket auto-reconnect with orderbook resynchronization.
- **Graceful Shutdown**: Clean resource cleanup and state persistence.
- **Timeout Protection**: HTTP requests (30s timeout), WebSocket connections (30s timeout) prevent indefinite hangs. Optimized for both individual requests and bulk API calls (24h ticker for 522 symbols).

## Feature Specifications

### Action Price System Improvements
- **Scoring Inversion**: Corrected inverted scoring components, improved depth confirmation, penalties, and amplified quality components.
- **Entry Timing & Dynamic Risk**: Redesigned `close_position` to favor pullback entries and `ema_fan` to reward early trend stages.

### CVD Divergence as Confirmation Filter
- Implemented as a confirmation bonus (not a standalone trigger) in `SignalScorer` using a multi-timeframe approach (15m + 1H) for scoring bonuses (+0.3 to +0.8).

### ATR Momentum Strategy
- Activated strategy to catch explosive moves (≥1.4× median ATR) with HTF EMA200 Confirmation (1H + 4H), Pin Bar Bonus (+0.5 score), and RSI Overextension Filter.

### S/R Zones V3 System (Created but NOT Integrated)
- **Status**: Fully implemented in `src/utils/sr_zones_v3/` but NOT yet integrated into bot strategies
- **Current System**: Bot continues using V2 system (`src/utils/sr_zones_15m.py`)
- **Architecture**: Modular design with 5 components:
  - **Clustering** (`clustering.py`): DBSCAN-based zone consolidation (ε=0.6×ATR)
  - **Validation** (`validation.py`): Reaction strength measurement (≥0.7 ATR retracement in m bars)
  - **Scoring** (`scoring.py`): Multi-factor scoring system (Touches + Reactions + Freshness + Confluence - Noise)
  - **Flip Detection** (`flip.py`): R⇄S zone role switching with confirmation (body break + 2-bar confirmation or retest)
  - **Builder** (`builder.py`): Main orchestrator for multi-TF zone construction (D→H4→H1→M15)
- **Methodology**: Based on 2024-2025 institutional trading best practices
- **Key Features**:
  - Adaptive fractal swing detection (k varies by TF: 1d=4, 4h=3, 1h=3, 15m=2)
  - Zone width adapts by timeframe and volatility (e.g., 15m: 0.35-0.7 ATR)
  - Freshness decay using exponential function (τ varies by TF)
  - Multi-TF merge with 40% overlap threshold
  - Strength classification: key (80+), strong (60-79), normal (40-59), weak (<40)
  - Confluence detection (EMA200, round numbers)
- **Configuration**: Full parameter set in `config.yaml` under `sr_zones_v3` (enabled: false)
- **Next Steps**: Requires integration via Adapter Pattern to enable A/B testing alongside existing V2 system

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