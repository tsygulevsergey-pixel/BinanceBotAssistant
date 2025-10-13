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
