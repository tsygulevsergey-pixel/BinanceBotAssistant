from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from pathlib import Path
from typing import Optional
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
        
        Base.metadata.create_all(bind=self.engine)
        logger.info(f"Database initialized at {db_path}")
    
    def get_session(self) -> Session:
        return self.SessionLocal()
    
    def close(self):
        self.engine.dispose()


db = Database()
