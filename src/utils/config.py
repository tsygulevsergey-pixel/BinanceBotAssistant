import os
import yaml
from typing import Any, Dict
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._config = self._load_config()
        self._secrets = self._load_secrets()
    
    def _load_config(self) -> Dict[str, Any]:
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _load_secrets(self) -> Dict[str, str]:
        return {
            'telegram_bot_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
            'telegram_chat_id': os.getenv('TELEGRAM_CHAT_ID', ''),
            'binance_api_key': os.getenv('BINANCE_API_KEY', ''),
            'binance_api_secret': os.getenv('BINANCE_API_SECRET', ''),
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value
    
    def get_secret(self, key: str) -> str:
        return self._secrets.get(key, '')
    
    @property
    def timezone(self) -> str:
        return self.get('timezone', 'Europe/Kiev')
    
    @property
    def database_path(self) -> str:
        return self.get('database.path', 'data/trading_bot.db')
    
    @property
    def log_file(self) -> str:
        return self.get('logging.file', 'logs/bot.log')
    
    @property
    def log_level(self) -> str:
        return self.get('logging.level', 'INFO')


config = Config()
