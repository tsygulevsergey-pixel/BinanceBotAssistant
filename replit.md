# Overview

This project is a professional-grade Binance USDT-M Futures Trading Bot designed for high-performance trading with an 80%+ Win Rate and a Profit Factor of 1.8-2.5. It employs advanced strategies, market regime detection, sophisticated risk management, and an "Action Price" system based on Support/Resistance, Anchored VWAP, and price action. The bot supports both Signals-Only and Live Trading Modes.

# User Preferences

## Communication
- Preferred communication style: Simple, everyday language.

## Development Environment Context
- **User runs bot locally on Windows PC in Ukraine** (not on Replit cloud)
- **Log files come from user's local computer** - when user attaches logs, they are from the bot running on their Windows machine
- **This Replit project contains the complete source code** - all code is here and kept up to date
- **Workflow setup is for Replit testing only** - user downloads code to run locally with his own API keys

## Important Context for Future Sessions
When user shares logs or reports errors:
1. Logs are from their local Windows environment running Python bot
2. They test/run the bot independently on their computer
3. This Replit workspace is the source code repository
4. Any fixes made here need to be downloaded by user to their local machine

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
- **VolumeProfile**: POC, VAH/VAL calculation (vectorized computation using numpy broadcasting for 50-100x speedup).
- **IndicatorCache**: High-performance caching for indicators (Volume Profile integrated October 2025).

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
- **Main Bot Log**: Standard logging for core bot operations
- **Action Price Log**: `logs/action_price_[дата]_[время].log` - separate file created at bot startup
- **V3 S/R Log**: `logs/v3_[дата]_[время].log` - separate file for V3 S/R strategy (added October 2025)
- **JSONL Logging**: Centralized JSONL logging for Action Price and V3 S/R signals
- **Log Levels**: DEBUG for detailed inner loops, INFO for key events and signal creation

### Performance Tracking System
- **SignalPerformanceTracker**: Monitors active signals, exit conditions, and PnL.
- **ActionPricePerformanceTracker**: Tracks Action Price signals, partial exits, breakeven logic, MFE/MAE, and logs to JSONL.

### Configuration Management
- Uses YAML for strategy parameters and thresholds, and environment variables for API keys. Supports `signals_only_mode` and `enabled` flags.

### Parallel Data Loading Architecture
- **SymbolLoadCoordinator**: Manages thread-safe data loading.
- **Loader Task**: Loads historical data with freshness optimization.
- **Analyzer Task**: Consumes symbols for immediate analysis.
- **Symbol Auto-Update Task**: Automatically updates the symbol list.
- **Data Integrity System**: Comprehensive data validation with gap detection, auto-fix, and Telegram alerts.
- **Smart Data Freshness Check (October 2025)**: Pre-API validation checks DB freshness before requesting Binance:
  - Checks if last candle covers current time period (e.g., 18:40 → current 15m candle is 18:30-18:45)
  - SKIPs API request if data is fresh (massive startup speedup on restarts)
  - Only downloads missing/outdated candles
  - Effect: 10-20 sec startup on short restarts (<15 min) vs 8 min without optimization

### Database Performance Optimization (October 2025)
- **BULK UPSERT**: Candle persistence optimized using SQLite INSERT OR REPLACE (100-500x faster).
- **Unique Index**: Composite unique index on (symbol, timeframe, open_time) prevents duplicates at database level.
- **Migration**: Safe migration script removes duplicates and creates index without data loss.
- **Performance Impact**: 8639 candles now save in ~1 second (previously 3 minutes).
- **Gap Detection Fix (October 2025)**: Fixed "Saved 0 klines" issue by using current candle start time instead of current_time when creating gaps. Eliminates ~600 empty API requests per restart (~3 min saved).

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

### V3 S/R Strategy System ✅ FULLY INTEGRATED (October 2025)
- **Status**: PRODUCTION READY - Fully integrated and running parallel to existing 6 strategies + Action Price
- **Implementation**: Complete independent trading strategy using V3 zones
- **Location**: `src/v3_sr/` (strategy.py, performance_tracker.py, helpers.py, signal_logger.py, logger.py)

#### Two Core Setups
1. **Flip-Retest Setup**:
   - Zone breaks (body close beyond zone + buffer)
   - N-bar confirmation (default: 2 closes beyond)
   - Retest within timeout (default: 12 bars)
   - Entry triggers: Engulfing, CHoCH
   
2. **Sweep-Return Setup**:
   - Liquidity sweep (wick beyond zone, body stays inside)
   - Wick/body ratio validation (≥1.2)
   - Fast return (≤3 bars default)
   - A-grade detection (wick ratio ≥2.0, return ≤2 bars)

#### Architecture Components
- **Database Tables** (auto-created via SQLAlchemy):
  - `v3_sr_signals`: Main signals table (setup_type, zone_strength, tp1/tp2_hit, trailing, mfe/mae)
  - `v3_sr_zone_events`: Zone touch event logging
  - `v3_sr_signal_locks`: Independent symbol blocking (symbol+direction keys)

- **Performance Tracking**:
  - **VIRTUAL Partial exits**: TP1 (50% virtual close) → move SL to BE → TP2 (remaining 50%)
  - Saved TP1 PnL returned on breakeven exits (not 0%)
  - Trailing stop after TP1 (configurable ATR multiplier)
  - MFE/MAE tracking in R-multiples
  - JSONL logging for offline analysis

- **Signal Scoring**:
  - Base: 50 points
  - Zone quality bonuses: Key (+20), Strong (+15), HTF (+15)
  - Setup bonuses: Flip-Retest (+10), A-grade Sweep (+20)
  - VWAP alignment (+5)
  - Min confidence threshold: 65%

#### Integration Points
- **Main Loop**: Runs on 15m/1h candle closes (parallel with Action Price)
- **Data Flow**: Uses same DataLoader, multi-TF data (15m/1h/4h/1d)
- **Independent Blocking**: Separate from main strategies and Action Price
- **Telegram Commands**: /v3_status, /v3_signals, /v3_stats, /v3_zones
- **Configuration**: `config.yaml` → `sr_zones_v3_strategy` section

#### Key Features
- **VWAP Bias Filter**: Enforces directional alignment (epsilon: 0.05 ATR)
- **A-grade Exception**: High-quality sweeps bypass VWAP filter
- **Zone Context**: Stores nearest support/resistance in signals
- **Market Regime Filtering**: Configurable allowed regimes (TREND/RANGE)
- **Adaptive SL/TP**: Calculated from zone boundaries + ATR buffers
- **Entry Timeframes**: 15m and 1H (configurable)
- **Context Timeframes**: 4H and 1D for zone quality

#### V3 Zones Infrastructure
Base system in `src/utils/sr_zones_v3/`:
- **Clustering**: DBSCAN-based zone consolidation (ε=0.6×ATR)
- **Validation**: Reaction strength measurement (≥0.7 ATR retracement)
- **Scoring**: Multi-factor (Touches + Reactions + Freshness + Confluence - Noise)
- **Flip Detection**: R⇄S role switching with confirmation
- **Builder**: Multi-TF orchestrator returns Dict[tf, zones] for efficient access by timeframe (October 2025)
- Adaptive fractal swing detection (k varies by TF)
- Zone width adapts by volatility (e.g., 15m: 0.35-0.7 ATR)
- Freshness decay using exponential function
- Strength classification: key (80+), strong (60-79), normal (40-59), weak (<40)

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