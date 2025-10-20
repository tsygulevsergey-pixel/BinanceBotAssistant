from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, Index, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import pytz

Base = declarative_base()


class Candle(Base):
    __tablename__ = 'candles'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    open_time = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    close_time = Column(DateTime, nullable=False)
    quote_volume = Column(Float)
    trades = Column(Integer)
    taker_buy_base = Column(Float)
    taker_buy_quote = Column(Float)
    
    __table_args__ = (
        Index('idx_candles_symbol_timeframe_time', 'symbol', 'timeframe', 'open_time'),
    )


class Trade(Base):
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    trade_id = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    quote_quantity = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    is_buyer_maker = Column(Boolean, nullable=False)
    
    __table_args__ = (
        Index('idx_symbol_trade_id', 'symbol', 'trade_id', unique=True),
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
    )


class Signal(Base):
    __tablename__ = 'signals'
    
    id = Column(Integer, primary_key=True)
    context_hash = Column(String(64), unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    strategy_id = Column(Integer, nullable=False, index=True)
    strategy_name = Column(String(50), nullable=False)
    direction = Column(String(10), nullable=False)
    
    # Price levels
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit_1 = Column(Float)
    take_profit_2 = Column(Float)
    
    # Basic signal info
    score = Column(Float, nullable=False)
    market_regime = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    
    # ═══════════════════════════════════════════════════════════
    # PROFESSIONAL ENHANCEMENTS
    # ═══════════════════════════════════════════════════════════
    
    # Multi-Timeframe Context (4H context → 1H signal → 15M confirmation)
    context_timeframe = Column(String(10))  # "4h" - для определения режима
    signal_timeframe = Column(String(10))   # "1h" - основной ТФ сигнала
    confirmation_timeframe = Column(String(10))  # "15m" - подтверждающий ТФ
    
    # Signal Confluence (2+ стратегий согласны)
    confluence_count = Column(Integer, default=1)  # Количество стратегий
    confluence_strategies = Column(Text)  # JSON: ["liquidity_sweep", "pullback", "profile"]
    confluence_bonus = Column(Float, default=0.0)  # Добавленный бонус к score
    
    # Structure-Based SL/TP Sources
    sl_type = Column(String(30))  # "swing_low", "VAL", "sweep_point", "structure"
    sl_level = Column(Float)      # Базовый уровень структуры
    sl_offset = Column(Float)     # Отступ от уровня
    tp1_type = Column(String(30))  # "1R", "liquidity_pool", "POC"
    tp2_type = Column(String(30))  # "2R", "VAH", "measured_move"
    
    # MAE/MFE Tracking (Max Adverse/Favorable Excursion)
    max_favorable_excursion = Column(Float)  # Макс прибыль до выхода (%)
    max_adverse_excursion = Column(Float)    # Макс убыток до выхода (%)
    bars_to_tp1 = Column(Integer)  # Сколько баров до TP1
    bars_to_exit = Column(Integer)  # Сколько баров до выхода
    
    # Partial Profit Taking (30/40/30 схема)
    tp1_size = Column(Float, default=0.30)  # 30% на TP1
    tp2_size = Column(Float, default=0.40)  # 40% на TP2
    runner_size = Column(Float, default=0.30)  # 30% trailing runner
    
    tp1_pnl_percent = Column(Float)  # Сохраненный PnL на TP1
    tp2_hit = Column(Boolean, default=False)
    tp2_closed_at = Column(DateTime)
    tp2_pnl_percent = Column(Float)  # Сохраненный PnL на TP2
    
    # Trailing Stop для Runner части
    trailing_active = Column(Boolean, default=False)
    trailing_high_water_mark = Column(Float)  # Максимальная цена для trail
    runner_exit_price = Column(Float)  # Цена выхода runner части
    runner_pnl_percent = Column(Float)  # PnL runner части
    
    # ═══════════════════════════════════════════════════════════
    # ORIGINAL FIELDS
    # ═══════════════════════════════════════════════════════════
    
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC))
    status = Column(String(20), nullable=False, default='ACTIVE')
    
    telegram_message_id = Column(Integer)
    
    tp1_hit = Column(Boolean, default=False)
    tp1_closed_at = Column(DateTime)
    
    exit_price = Column(Float)
    exit_reason = Column(String(50))
    exit_type = Column(String(20))
    pnl = Column(Float)
    pnl_percent = Column(Float)
    closed_at = Column(DateTime)
    
    meta_data = Column(JSON)
    
    __table_args__ = (
        Index('idx_status_symbol', 'status', 'symbol'),
        Index('idx_created_at', 'created_at'),
        Index('idx_regime_confidence', 'market_regime', 'confluence_count'),  # Для анализа
    )


class Metric(Base):
    __tablename__ = 'metrics'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=lambda: datetime.now(pytz.UTC))
    metric_type = Column(String(50), nullable=False, index=True)
    symbol = Column(String(20), index=True)
    strategy_id = Column(Integer, index=True)
    
    value = Column(Float, nullable=False)
    meta_data = Column(JSON)
    
    __table_args__ = (
        Index('idx_type_symbol_time', 'metric_type', 'symbol', 'timestamp'),
    )


class MarketState(Base):
    __tablename__ = 'market_state'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    
    regime = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    
    adx = Column(Float)
    atr = Column(Float)
    atr_percent = Column(Float)
    bb_width = Column(Float)
    bb_percentile = Column(Float)
    
    ema_20 = Column(Float)
    ema_50 = Column(Float)
    ema_200 = Column(Float)
    
    late_trend_flag = Column(Boolean, default=False)
    
    meta_data = Column(JSON)
    
    __table_args__ = (
        Index('idx_market_state_symbol_timeframe_time', 'symbol', 'timeframe', 'timestamp'),
    )


class SignalLock(Base):
    __tablename__ = 'signal_locks'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True, unique=True)
    direction = Column(String(10), nullable=False)
    strategy_name = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC), index=True)
    
    __table_args__ = (
        Index('idx_signal_lock_created', 'created_at'),
    )


class ActionPriceSignal(Base):
    __tablename__ = 'action_price_signals'
    
    id = Column(Integer, primary_key=True)
    context_hash = Column(String(64), unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    pattern_type = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    timeframe = Column(String(10), nullable=False)
    
    zone_id = Column(String(50), nullable=False)
    zone_low = Column(Float, nullable=False)
    zone_high = Column(Float, nullable=False)
    
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit_1 = Column(Float, nullable=False)
    take_profit_2 = Column(Float)
    
    avwap_primary = Column(Float)
    avwap_secondary = Column(Float)
    daily_vwap = Column(Float)
    
    ema_50_4h = Column(Float)
    ema_200_4h = Column(Float)
    ema_50_1h = Column(Float)
    ema_200_1h = Column(Float)
    
    confidence_score = Column(Float, nullable=False)
    confluence_flags = Column(JSON)
    
    market_regime = Column(String(20))
    
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC))
    status = Column(String(20), nullable=False, default='PENDING')
    
    telegram_message_id = Column(Integer)
    
    partial_exit_1_at = Column(DateTime)
    partial_exit_1_price = Column(Float)
    partial_exit_2_at = Column(DateTime)
    partial_exit_2_price = Column(Float)
    
    # Trailing stop state (персистентность для 30% остатка после TP2)
    trailing_peak_price = Column(Float)  # Пик цены после TP2 для trailing stop
    
    exit_price = Column(Float)
    exit_reason = Column(String(50))
    pnl = Column(Float)
    pnl_percent = Column(Float)
    closed_at = Column(DateTime)
    
    meta_data = Column(JSON)
    
    __table_args__ = (
        Index('idx_ap_status_symbol', 'status', 'symbol'),
        Index('idx_ap_pattern_tf', 'pattern_type', 'timeframe'),
        Index('idx_ap_created_at', 'created_at'),
    )


class V3SRSignal(Base):
    """
    V3 S/R Strategy Signal Model
    
    Stores Flip-Retest and Sweep-Return signals with zone context,
    VWAP bias, and detailed performance tracking.
    """
    __tablename__ = 'v3_sr_signals'
    
    # Primary identification
    id = Column(Integer, primary_key=True)
    signal_id = Column(String(64), unique=True, nullable=False, index=True)  # Deterministic hash
    symbol = Column(String(20), nullable=False, index=True)
    
    # Setup identification
    setup_type = Column(String(20), nullable=False)  # "FlipRetest" or "SweepReturn"
    direction = Column(String(10), nullable=False)  # "LONG" or "SHORT"
    entry_tf = Column(String(10), nullable=False)  # "15m" or "1h"
    
    # Zone reference (primary zone that triggered signal)
    zone_id = Column(String(64), nullable=False, index=True)
    zone_tf = Column(String(10), nullable=False)  # "15m", "1h", "4h", "1d"
    zone_kind = Column(String(10), nullable=False)  # "S" or "R"
    zone_low = Column(Float, nullable=False)
    zone_high = Column(Float, nullable=False)
    zone_mid = Column(Float, nullable=False)
    zone_strength = Column(Float, nullable=False)  # 0-100
    zone_class = Column(String(20), nullable=False)  # "key", "strong", "normal", "weak"
    zone_state = Column(String(20))  # "normal", "weakening", "flipped"
    
    # Nearest zones context (для отображения в Telegram)
    nearest_support_low = Column(Float)
    nearest_support_high = Column(Float)
    nearest_support_strength = Column(Float)
    nearest_support_type = Column(String(30))  # "H4 Strong Support"
    
    nearest_resistance_low = Column(Float)
    nearest_resistance_high = Column(Float)
    nearest_resistance_strength = Column(Float)
    nearest_resistance_type = Column(String(30))  # "D Key Resistance"
    
    # HTF context (старшие таймфреймы)
    htf_context = Column(JSON)  # ["D:KeyR", "H4:StrongS", ...]
    
    # VWAP Bias
    vwap_bias = Column(String(20))  # "BULL", "BEAR", "NEUTRAL"
    vwap_value = Column(Float)  # Текущее значение VWAP
    price_vs_vwap = Column(Float)  # Distance from VWAP in ATR
    
    # Price levels (all rounded to tick size)
    entry_price = Column(Float, nullable=False)
    entry_price_raw = Column(Float)  # До округления
    stop_loss = Column(Float, nullable=False)
    stop_loss_raw = Column(Float)
    take_profit_1 = Column(Float, nullable=False)
    tp1_raw = Column(Float)
    take_profit_2 = Column(Float, nullable=False)
    tp2_raw = Column(Float)
    
    # Risk/Reward
    risk_r = Column(Float, nullable=False)  # |entry - sl|
    tp1_r_multiple = Column(Float)  # TP1 в R
    tp2_r_multiple = Column(Float)  # TP2 в R
    
    # Quality & Confidence
    confidence = Column(Float, nullable=False)  # 0-100
    quality_tags = Column(JSON)  # ["flip_confirmed", "vwap_ok", ...]
    
    # Setup-specific audit data
    setup_params = Column(JSON)  # Flip: {break_atr, confirm_closes, retest_delta} | Sweep: {wick_ratio, return_bars}
    
    # Market context
    market_regime = Column(String(20))
    volatility_regime = Column(String(20))  # "low", "normal", "high"
    atr_value = Column(Float)  # ATR на момент сигнала
    
    # Validity
    valid_until_ts = Column(DateTime, nullable=False)  # Timeout для исполнения
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC), index=True)
    
    # Execution tracking
    status = Column(String(20), nullable=False, default='PENDING', index=True)  # PENDING, ACTIVE, CLOSED, CANCELLED
    telegram_message_id = Column(Integer)
    
    # Partial exits (50% TP1, 50% trail to TP2)
    tp1_size = Column(Float, default=0.50)  # 50% exit at TP1
    tp2_trail_size = Column(Float, default=0.50)  # 50% trail to TP2
    
    tp1_hit = Column(Boolean, default=False)
    tp1_hit_at = Column(DateTime)
    tp1_pnl_percent = Column(Float)
    
    tp2_hit = Column(Boolean, default=False)
    tp2_hit_at = Column(DateTime)
    tp2_pnl_percent = Column(Float)
    
    # Breakeven & Trailing
    moved_to_be = Column(Boolean, default=False)  # SL moved to BE after TP1
    moved_to_be_at = Column(DateTime)
    trailing_active = Column(Boolean, default=False)
    trailing_high_water_mark = Column(Float)  # Для LONG / low water mark для SHORT
    
    # Final exit
    exit_price = Column(Float)
    exit_reason = Column(String(50))  # "TP1", "TP2", "SL", "BE", "TRAIL", "TIMEOUT", "MANUAL"
    exit_type = Column(String(20))  # "FULL", "PARTIAL_TP1", "PARTIAL_TP2"
    pnl = Column(Float)
    pnl_percent = Column(Float)
    final_r_multiple = Column(Float)  # Итоговый R-multiple
    closed_at = Column(DateTime)
    
    # Performance metrics
    max_favorable_excursion = Column(Float)  # MFE в R
    max_adverse_excursion = Column(Float)  # MAE в R
    bars_to_tp1 = Column(Integer)
    bars_to_tp2 = Column(Integer)
    bars_to_exit = Column(Integer)
    duration_minutes = Column(Integer)
    
    # Zone reaction quality (после закрытия сигнала)
    zone_reaction_occurred = Column(Boolean)  # Была ли реакция от зоны >= threshold
    zone_reaction_atr = Column(Float)  # Величина реакции в ATR
    
    # Metadata
    meta_data = Column(JSON)
    
    __table_args__ = (
        Index('idx_v3sr_status_symbol', 'status', 'symbol'),
        Index('idx_v3sr_setup_tf', 'setup_type', 'entry_tf'),
        Index('idx_v3sr_zone_id', 'zone_id'),
        Index('idx_v3sr_created', 'created_at'),
    )


class V3SRZoneEvent(Base):
    """
    V3 S/R Zone Touch/Reaction Events
    
    Logs all zone touches and reactions for quality analysis.
    """
    __tablename__ = 'v3_sr_zone_events'
    
    id = Column(Integer, primary_key=True)
    event_id = Column(String(64), unique=True, nullable=False, index=True)
    
    # Zone identification
    zone_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    zone_tf = Column(String(10), nullable=False)
    zone_kind = Column(String(10), nullable=False)  # "S" or "R"
    zone_low = Column(Float, nullable=False)
    zone_high = Column(Float, nullable=False)
    zone_strength = Column(Float, nullable=False)
    
    # Event details
    event_type = Column(String(30), nullable=False, index=True)  # "touch", "body_break", "flip", "sweep", "retest"
    bar_timestamp = Column(DateTime, nullable=False, index=True)
    touch_price = Column(Float, nullable=False)
    
    # Touch characteristics
    side = Column(String(10))  # "from_below", "from_above"
    penetration_depth_atr = Column(Float)  # Насколько глубоко зашли в зону (в ATR)
    wick_to_body_ratio = Column(Float)  # Отношение хвоста к телу (для sweeps)
    
    # Reaction tracking
    reaction_occurred = Column(Boolean, default=False)
    reaction_bars = Column(Integer)  # Сколько баров до реакции
    reaction_magnitude_atr = Column(Float)  # Величина реакции в ATR
    reaction_checked_at = Column(DateTime)  # Когда проверили реакцию
    
    # Market context at touch
    market_regime = Column(String(20))
    volatility_regime = Column(String(20))
    atr_value = Column(Float)
    
    # Related signal (если событие привело к сигналу)
    related_signal_id = Column(String(64), index=True)
    
    # Metadata
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC), index=True)
    meta_data = Column(JSON)
    
    __table_args__ = (
        Index('idx_v3sr_events_zone_type', 'zone_id', 'event_type'),
        Index('idx_v3sr_events_symbol_ts', 'symbol', 'bar_timestamp'),
    )


class V3SRSignalLock(Base):
    """
    V3 S/R Signal Locks
    
    Prevents multiple V3 signals on same symbol until current signal closes.
    Independent from other strategy locks.
    """
    __tablename__ = 'v3_sr_signal_locks'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # "LONG" or "SHORT"
    signal_id = Column(String(64), nullable=False)  # Reference to V3SRSignal
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC), index=True)
    
    __table_args__ = (
        Index('idx_v3sr_lock_symbol_dir', 'symbol', 'direction', unique=True),
    )
