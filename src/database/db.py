from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from pathlib import Path
from typing import Optional
import sqlite3
from src.database.models import Base
from src.utils.config import config
from src.utils.logger import logger


class Database:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = config.database_path
        
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.db_path = db_path
        self.engine = create_engine(
            f'sqlite:///{db_path}',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
            echo=False
        )
        
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.close()
        
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        
        # КРИТИЧНО: Применить миграции ПЕРЕД create_all
        self._apply_migrations()
        
        Base.metadata.create_all(bind=self.engine)
        logger.info(f"Database initialized at {db_path}")
    
    def _apply_migrations(self):
        """Применить миграции схемы БД перед create_all"""
        try:
            # Проверить существует ли таблица action_price_signals
            inspector = inspect(self.engine)
            if 'action_price_signals' not in inspector.get_table_names():
                # Таблица не существует, create_all создаст её с правильной схемой
                return
            
            # Таблица существует - проверить наличие trailing_peak_price
            columns = [col['name'] for col in inspector.get_columns('action_price_signals')]
            
            if 'trailing_peak_price' in columns:
                logger.debug("✅ Column 'trailing_peak_price' already exists")
                return
            
            # Добавить поле через raw SQL
            logger.info("🔧 Applying migration: adding trailing_peak_price to action_price_signals")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                ALTER TABLE action_price_signals 
                ADD COLUMN trailing_peak_price REAL
            """)
            conn.commit()
            conn.close()
            logger.info("✅ Migration applied: trailing_peak_price column added")
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}", exc_info=True)
            # Не падаем - create_all может создать таблицу с нуля
    
    def get_session(self) -> Session:
        return self.SessionLocal()
    
    def close(self):
        self.engine.dispose()


db = Database()
