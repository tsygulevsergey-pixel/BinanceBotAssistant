"""
Gluk Symbol Blocker - НЕЗАВИСИМАЯ блокировка монет

КРИТИЧНО:
- Полностью отдельная от Action Price блокировки
- Использует таблицу gluk_blocking в БД
- НЕ влияет на основные стратегии
- НЕ влияет на Action Price
"""
import logging
from typing import Optional
from datetime import datetime
import pytz

from src.gluk.models import GlukBlocking

logger = logging.getLogger(__name__)


class GlukSymbolBlocker:
    """Управление блокировкой монет для Глюк системы"""
    
    def __init__(self, db):
        """
        Args:
            db: Database instance
        """
        self.db = db
        logger.info("✅ Gluk Symbol Blocker initialized (independent from AP)")
    
    def block_symbol(self, symbol: str, direction: str, reason: str = "SIGNAL_ACTIVE"):
        """
        Заблокировать монету
        
        Args:
            symbol: Символ
            direction: LONG/SHORT
            reason: Причина блокировки
        """
        session = self.db.get_session()
        try:
            # Проверить есть ли уже блокировка
            existing = session.query(GlukBlocking).filter(
                GlukBlocking.symbol == symbol
            ).first()
            
            if existing:
                # Обновить существующую
                existing.direction = direction
                existing.blocked_at = datetime.now(pytz.UTC)
                existing.reason = reason
                logger.debug(f"🔒 Gluk updated block: {symbol} {direction} ({reason})")
            else:
                # Создать новую
                block = GlukBlocking(
                    symbol=symbol,
                    direction=direction,
                    blocked_at=datetime.now(pytz.UTC),
                    reason=reason
                )
                session.add(block)
                logger.info(f"🔒 Gluk blocked: {symbol} {direction} ({reason})")
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error blocking Gluk symbol {symbol}: {e}", exc_info=True)
        finally:
            session.close()
    
    def unblock_symbol(self, symbol: str):
        """
        Разблокировать монету
        
        Args:
            symbol: Символ
        """
        session = self.db.get_session()
        try:
            session.query(GlukBlocking).filter(
                GlukBlocking.symbol == symbol
            ).delete()
            session.commit()
            logger.info(f"🔓 Gluk unblocked: {symbol}")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error unblocking Gluk symbol {symbol}: {e}", exc_info=True)
        finally:
            session.close()
    
    def is_blocked(self, symbol: str) -> bool:
        """
        Проверить заблокирована ли монета
        
        Args:
            symbol: Символ
            
        Returns:
            True если заблокирована
        """
        session = self.db.get_session()
        try:
            block = session.query(GlukBlocking).filter(
                GlukBlocking.symbol == symbol
            ).first()
            
            return block is not None
            
        finally:
            session.close()
    
    def get_blocked_symbols(self) -> list:
        """
        Получить список заблокированных монет
        
        Returns:
            Список символов
        """
        session = self.db.get_session()
        try:
            blocks = session.query(GlukBlocking).all()
            return [block.symbol for block in blocks]
            
        finally:
            session.close()
