"""
Gluk Database Models - ОТДЕЛЬНЫЕ таблицы БД

КРИТИЧНО: Эти таблицы ПОЛНОСТЬЮ независимы от Action Price!
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, Index, JSON
from src.database.models import Base
from datetime import datetime
import pytz


class GlukSignal(Base):
    """Сигналы Глюк системы (копия ActionPriceSignal)"""
    __tablename__ = 'gluk_signals'
    
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
        Index('idx_gluk_status_symbol', 'status', 'symbol'),
        Index('idx_gluk_pattern_tf', 'pattern_type', 'timeframe'),
        Index('idx_gluk_created_at', 'created_at'),
    )


class GlukBlocking(Base):
    """Блокировка монет для Глюк системы (НЕЗАВИСИМАЯ от AP)"""
    __tablename__ = 'gluk_blocking'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True, unique=True)
    direction = Column(String(10), nullable=False)
    blocked_at = Column(DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC), index=True)
    reason = Column(String(100))
    
    __table_args__ = (
        Index('idx_gluk_blocking_created', 'blocked_at'),
    )
