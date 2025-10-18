"""
Gluk Logger - отдельное логирование для Legacy системы

КРИТИЧНО: Полностью независимо от Action Price логирования!
"""
import logging
import os
from datetime import datetime
import pytz


def setup_gluk_logger():
    """
    Настроить отдельный logger для Глюк системы
    
    Returns:
        Configured logger
    """
    # Создать logger
    logger = logging.getLogger('gluk')
    logger.setLevel(logging.INFO)
    logger.propagate = False  # НЕ передавать в root logger
    
    # Удалить существующие handlers
    logger.handlers.clear()
    
    # Создать директорию logs если нет
    os.makedirs('logs', exist_ok=True)
    
    # Файл лога с timestamp
    tz = pytz.timezone('Europe/Kyiv')
    timestamp = datetime.now(tz).strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'logs/gluk_{timestamp}.log'
    
    # File handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s EEST | %(levelname)-8s | gluk | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"🟡 Gluk Logger initialized | Log file: {log_file}")
    
    return logger


# Глобальный logger для Глюк
gluk_logger = setup_gluk_logger()
