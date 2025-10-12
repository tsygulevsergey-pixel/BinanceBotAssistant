"""
Отдельный logger для Action Price стратегии
"""
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from datetime import datetime


def setup_action_price_logger():
    """Настроить отдельный logger для Action Price"""
    
    # Создать директорию logs если не существует
    os.makedirs('logs', exist_ok=True)
    
    # Создать logger
    logger = logging.getLogger('action_price')
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Не передавать в root logger
    
    # Удалить существующие handlers
    logger.handlers = []
    
    # Формат логов
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler с ротацией по дням
    log_filename = f"logs/action_price_{datetime.now().strftime('%Y-%m-%d')}.log"
    file_handler = TimedRotatingFileHandler(
        log_filename,
        when='midnight',
        interval=1,
        backupCount=30,  # Хранить 30 дней
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
    
    return logger


# Singleton instance
ap_logger = setup_action_price_logger()
