from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.logger import logger
from src.utils.config import config


class StrategyManager:
    """Менеджер для управления всеми стратегиями"""
    
    def __init__(self):
        self.strategies: List[BaseStrategy] = []
        self.enabled_strategy_ids = config.get('strategies.enabled', [])
        
    def register_strategy(self, strategy: BaseStrategy):
        """Зарегистрировать стратегию"""
        self.strategies.append(strategy)
        logger.info(f"Registered strategy: {strategy.name}")
    
    def register_all(self, strategies: List[BaseStrategy]):
        """Зарегистрировать все стратегии сразу"""
        for strategy in strategies:
            self.register_strategy(strategy)
    
    def check_all_signals(self, symbol: str, timeframe_data: Dict[str, pd.DataFrame],
                         regime: str, bias: str, indicators: Dict) -> List[Signal]:
        """
        Проверить все стратегии на сигналы
        
        Args:
            symbol: Торговая пара
            timeframe_data: Словарь {timeframe: DataFrame}
            regime: Рыночный режим
            bias: Направление тренда H4
            indicators: Рассчитанные индикаторы
            
        Returns:
            Список сгенерированных сигналов
        """
        signals = []
        
        for strategy in self.strategies:
            if not strategy.is_enabled():
                continue
            
            # Получить данные для таймфрейма стратегии
            tf = strategy.get_timeframe()
            df = timeframe_data.get(tf)
            
            if df is None or len(df) < 50:
                continue
            
            try:
                signal = strategy.check_signal(symbol, df, regime, bias, indicators)
                if signal:
                    strategy.increment_signal_count()
                    signals.append(signal)
                    logger.info(
                        f"Signal generated: {signal.strategy_name} | "
                        f"{signal.symbol} {signal.direction} | Score: {signal.base_score}"
                    )
            except Exception as e:
                logger.error(f"Error in strategy {strategy.name}: {e}", exc_info=True)
        
        return signals
    
    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        """Получить стратегию по имени"""
        for strategy in self.strategies:
            if strategy.name == name:
                return strategy
        return None
    
    def enable_strategy(self, name: str):
        """Включить стратегию"""
        strategy = self.get_strategy(name)
        if strategy:
            strategy.enable()
    
    def disable_strategy(self, name: str):
        """Выключить стратегию"""
        strategy = self.get_strategy(name)
        if strategy:
            strategy.disable()
    
    def get_all_stats(self) -> List[Dict]:
        """Получить статистику всех стратегий"""
        return [s.get_stats() for s in self.strategies]
    
    def get_enabled_count(self) -> int:
        """Получить количество активных стратегий"""
        return sum(1 for s in self.strategies if s.is_enabled())
    
    def get_total_signals_count(self) -> int:
        """Получить общее количество сгенерированных сигналов"""
        return sum(s.signals_generated for s in self.strategies)
