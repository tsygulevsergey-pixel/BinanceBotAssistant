"""
Отдельный logger для Action Price стратегии
"""
import logging
import os
from datetime import datetime
import pytz


def setup_action_price_logger():
    """
    Настроить отдельный logger для Action Price
    
    Создает новый файл лога при каждом запуске бота с timestamp
    """
    
    # Создать директорию logs если не существует
    os.makedirs('logs', exist_ok=True)
    
    # Создать logger
    logger = logging.getLogger('action_price')
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Не передавать в root logger
    
    # Удалить существующие handlers
    logger.handlers = []
    
    # Формат логов с таймзоной
    class KyivFormatter(logging.Formatter):
        def __init__(self, fmt=None, datefmt=None):
            super().__init__(fmt, datefmt)
            self.tz = pytz.timezone('Europe/Kyiv')
        
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=pytz.UTC)
            dt = dt.astimezone(self.tz)
            return dt.strftime('%Y-%m-%d %H:%M:%S %Z')
    
    formatter = KyivFormatter(
        '%(asctime)s | %(levelname)-8s | %(message)s'
    )
    
    # File handler - НОВЫЙ ФАЙЛ при каждом запуске бота
    timestamp = datetime.now(tz=pytz.timezone('Europe/Kyiv')).strftime('%Y-%m-%d_%H-%M-%S')
    log_filename = f"logs/action_price_{timestamp}.log"
    
    file_handler = logging.FileHandler(
        log_filename,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # Добавить handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"🎯 Action Price Logger initialized - log file: {log_filename}")
    
    return logger


# Singleton instance
ap_logger = setup_action_price_logger()
