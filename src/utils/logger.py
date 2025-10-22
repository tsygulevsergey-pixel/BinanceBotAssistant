import logging
import sys
from pathlib import Path
import pytz
from datetime import datetime
from typing import Optional
from src.utils.config import config


class KyivFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.tz = pytz.timezone(config.timezone)
    
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=pytz.UTC)
        dt = dt.astimezone(self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S %Z')


def setup_logger(name: str = 'trading_bot', level: Optional[str] = None) -> logging.Logger:
    if level is None:
        level = config.log_level
    
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # ✅ FIX: ВСЕГДА удаляем старые handlers и создаём новые
    # Закрыть ТОЛЬКО FileHandlers (не StreamHandlers - они используют stdout!)
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            handler.close()  # Закрыть файл
        logger.removeHandler(handler)
    
    log_format = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    formatter = KyivFormatter(log_format)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Создать имя файла с датой/временем запуска
    timestamp = datetime.now(tz=pytz.timezone(config.timezone)).strftime('%Y-%m-%d_%H-%M-%S')
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"bot_{timestamp}.log"
    
    file_handler = logging.FileHandler(
        log_file,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    logger.info(f"📍 Main Bot Logger initialized - log file: {log_file}")
    
    return logger


logger = setup_logger()
