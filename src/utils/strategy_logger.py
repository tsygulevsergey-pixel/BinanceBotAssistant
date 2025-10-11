import logging
import sys
from pathlib import Path
import pytz
from datetime import datetime


class KyivFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.tz = pytz.timezone('Europe/Kiev')
    
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=pytz.UTC)
        dt = dt.astimezone(self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S %Z')


def setup_strategy_logger() -> logging.Logger:
    """Отдельный logger для детального логирования стратегий"""
    logger = logging.getLogger('strategy_analysis')
    logger.setLevel(logging.DEBUG)
    
    if logger.handlers:
        return logger
    
    # Формат: время | уровень | сообщение
    log_format = '%(asctime)s | %(levelname)-8s | %(message)s'
    formatter = KyivFormatter(log_format)
    
    # Создать имя файла с датой/временем запуска
    timestamp = datetime.now(tz=pytz.timezone('Europe/Kiev')).strftime('%Y-%m-%d_%H-%M-%S')
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"strategies_{timestamp}.log"
    
    file_handler = logging.FileHandler(
        log_file,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Консольный handler - показывает только важное (INFO+)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)  # Только WARNING и выше в консоль
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger


strategy_logger = setup_strategy_logger()
