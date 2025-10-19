"""
Система блокировок сигналов для политики "1 сигнал на стратегию на символ"
Поддерживает Redis (приоритет) и SQLite (fallback)

Логика:
- Каждая стратегия может независимо давать сигнал на одну монету в одном направлении
- Одна стратегия не может давать >1 активного сигнала на ту же монету+направление
- Блокировка освобождается только для конкретной стратегии при закрытии её сигнала
"""

import hashlib
from datetime import datetime, timedelta
from typing import Optional
import pytz

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from src.utils.config import config
from src.utils.logger import logger
from src.database.db import db
from src.database.models import SignalLock


class SignalLockManager:
    """Менеджер блокировок сигналов"""
    
    def __init__(self):
        self.lock_ttl = config.get('telegram.lock_ttl', 3600)  # seconds
        self.redis_client = None
        self.use_redis = False
        
        # Попытка подключения к Redis
        if REDIS_AVAILABLE:
            try:
                redis_host = config.get('redis.host', 'localhost')
                redis_port = config.get('redis.port', 6379)
                redis_db = config.get('redis.db', 0)
                redis_password = config.get('redis.password', None)
                
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    password=redis_password,
                    decode_responses=True,
                    socket_timeout=2,
                    socket_connect_timeout=2
                )
                
                # Проверка подключения
                self.redis_client.ping()
                self.use_redis = True
                logger.info(f"✅ Redis connected at {redis_host}:{redis_port}")
            except Exception as e:
                logger.warning(f"Redis unavailable ({e}), using SQLite fallback for signal locks")
                self.redis_client = None
                self.use_redis = False
        else:
            logger.warning("Redis library not available, using SQLite fallback for signal locks")
    
    def _generate_lock_key(self, symbol: str, direction: str = None, strategy_name: str = None) -> str:
        """
        Генерировать ключ блокировки для символа, направления и стратегии
        
        Args:
            symbol: Торговая пара
            direction: Направление (LONG/SHORT) - если None, только символ
            strategy_name: Название стратегии - если None, без стратегии
        """
        if direction and strategy_name:
            return f"signal_lock:{symbol}:{direction}:{strategy_name}"
        elif direction:
            return f"signal_lock:{symbol}:{direction}"
        return f"signal_lock:{symbol}"
    
    def acquire_lock(self, symbol: str, direction: str, strategy_name: str) -> bool:
        """
        Попытаться получить блокировку для символа
        
        Args:
            symbol: Торговая пара
            direction: Направление (LONG/SHORT)
            strategy_name: Название стратегии
            
        Returns:
            True если блокировка получена, False если символ уже заблокирован
        """
        if self.use_redis:
            return self._acquire_lock_redis(symbol, direction, strategy_name)
        else:
            return self._acquire_lock_sqlite(symbol, direction, strategy_name)
    
    def _acquire_lock_redis(self, symbol: str, direction: str, strategy_name: str) -> bool:
        """Получить блокировку через Redis"""
        try:
            # Используем direction и strategy_name в ключе для раздельных locks по стратегиям
            key = self._generate_lock_key(symbol, direction, strategy_name)
            lock_data = f"{strategy_name}:{direction}"
            
            # SET NX EX - установить только если не существует с TTL
            result = self.redis_client.set(
                key,
                lock_data,
                nx=True,  # Только если ключа нет
                ex=self.lock_ttl  # TTL в секундах
            )
            
            if result:
                logger.info(f"🔒 Lock acquired: {symbol} {direction} ({strategy_name}) TTL={self.lock_ttl}s")
                return True
            else:
                existing = self.redis_client.get(key)
                logger.warning(f"❌ Lock denied: {symbol} {direction} already locked by {existing}")
                return False
        except Exception as e:
            logger.error(f"Redis lock error for {symbol} {direction}: {e}")
            # Fallback to SQLite on Redis error
            return self._acquire_lock_sqlite(symbol, direction, strategy_name)
    
    def _acquire_lock_sqlite(self, symbol: str, direction: str, strategy_name: str) -> bool:
        """Получить блокировку через SQLite"""
        session = db.get_session()
        try:
            now = datetime.now(pytz.UTC)
            
            # Очистить истекшие блокировки
            expired_threshold = now - timedelta(seconds=self.lock_ttl)
            session.query(SignalLock).filter(
                SignalLock.created_at < expired_threshold
            ).delete()
            session.commit()
            
            # Проверить существующую блокировку для этого символа, направления И стратегии
            existing_lock = session.query(SignalLock).filter(
                SignalLock.symbol == symbol,
                SignalLock.direction == direction,
                SignalLock.strategy_name == strategy_name
            ).first()
            
            if existing_lock:
                logger.warning(
                    f"❌ Lock denied: {symbol} {direction} already locked by "
                    f"{existing_lock.strategy_name}"
                )
                return False
            
            # Создать новую блокировку
            new_lock = SignalLock(
                symbol=symbol,
                direction=direction,
                strategy_name=strategy_name,
                created_at=now
            )
            session.add(new_lock)
            session.commit()
            
            logger.info(f"🔒 Lock acquired (SQLite): {symbol} {direction} ({strategy_name}) TTL={self.lock_ttl}s")
            return True
            
        except Exception as e:
            session.rollback()
            logger.error(f"SQLite lock error for {symbol} {direction}: {e}")
            return False
        finally:
            session.close()
    
    def release_lock(self, symbol: str, direction: str = None, strategy_name: str = None):
        """
        Освободить блокировку символа
        
        Args:
            symbol: Торговая пара
            direction: Направление (LONG/SHORT) - если None, освобождает все locks символа
            strategy_name: Название стратегии - если None, освобождает все locks направления
        """
        if self.use_redis:
            self._release_lock_redis(symbol, direction, strategy_name)
        else:
            self._release_lock_sqlite(symbol, direction, strategy_name)
    
    def _release_lock_redis(self, symbol: str, direction: str = None, strategy_name: str = None):
        """Освободить блокировку через Redis"""
        try:
            if direction and strategy_name:
                # Освободить конкретную стратегию на направлении
                key = self._generate_lock_key(symbol, direction, strategy_name)
                deleted = self.redis_client.delete(key)
                if deleted:
                    logger.info(f"🔓 Lock released: {symbol} {direction} ({strategy_name})")
            elif direction:
                # Освободить все стратегии на направлении
                pattern = f"signal_lock:{symbol}:{direction}:*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    deleted = self.redis_client.delete(*keys)
                    logger.info(f"🔓 Locks released: {symbol} {direction} ({deleted} locks)")
            else:
                # Освободить все locks для символа (все направления и стратегии)
                pattern = f"signal_lock:{symbol}:*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    deleted = self.redis_client.delete(*keys)
                    logger.info(f"🔓 Locks released: {symbol} ({deleted} locks)")
        except Exception as e:
            logger.error(f"Redis unlock error for {symbol}: {e}")
    
    def _release_lock_sqlite(self, symbol: str, direction: str = None, strategy_name: str = None):
        """Освободить блокировку через SQLite"""
        session = db.get_session()
        try:
            query = session.query(SignalLock).filter(SignalLock.symbol == symbol)
            
            if direction and strategy_name:
                # Освободить конкретную стратегию на направлении
                query = query.filter(
                    SignalLock.direction == direction,
                    SignalLock.strategy_name == strategy_name
                )
                deleted = query.delete()
                session.commit()
                if deleted:
                    logger.info(f"🔓 Lock released (SQLite): {symbol} {direction} ({strategy_name})")
            elif direction:
                # Освободить все стратегии на направлении
                query = query.filter(SignalLock.direction == direction)
                deleted = query.delete()
                session.commit()
                if deleted:
                    logger.info(f"🔓 Locks released (SQLite): {symbol} {direction} ({deleted} locks)")
            else:
                # Освободить все locks для символа
                deleted = query.delete()
                session.commit()
                if deleted:
                    logger.info(f"🔓 Locks released (SQLite): {symbol} ({deleted} locks)")
        except Exception as e:
            session.rollback()
            logger.error(f"SQLite unlock error for {symbol}: {e}")
        finally:
            session.close()
    
    def get_active_locks_count(self) -> int:
        """Получить количество активных блокировок"""
        if self.use_redis:
            try:
                pattern = "signal_lock:*"
                keys = self.redis_client.keys(pattern)
                return len(keys)
            except Exception as e:
                logger.error(f"Error counting Redis locks: {e}")
                return 0
        else:
            session = db.get_session()
            try:
                now = datetime.now(pytz.UTC)
                expired_threshold = now - timedelta(seconds=self.lock_ttl)
                count = session.query(SignalLock).filter(
                    SignalLock.created_at >= expired_threshold
                ).count()
                return count
            finally:
                session.close()
    
    def cleanup_expired_locks(self):
        """Очистить истекшие блокировки (только для SQLite, Redis очищает автоматически)"""
        if not self.use_redis:
            session = db.get_session()
            try:
                now = datetime.now(pytz.UTC)
                expired_threshold = now - timedelta(seconds=self.lock_ttl)
                deleted = session.query(SignalLock).filter(
                    SignalLock.created_at < expired_threshold
                ).delete()
                session.commit()
                if deleted > 0:
                    logger.info(f"🧹 Cleaned up {deleted} expired signal locks")
            except Exception as e:
                session.rollback()
                logger.error(f"Error cleaning up locks: {e}")
            finally:
                session.close()
