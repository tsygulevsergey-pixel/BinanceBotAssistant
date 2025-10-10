import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
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
    
    if logger.handlers:
        return logger
    
    log_format = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    formatter = KyivFormatter(log_format)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    log_file = Path(config.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    file_handler = TimedRotatingFileHandler(
        log_file,
        when='D',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


logger = setup_logger()
