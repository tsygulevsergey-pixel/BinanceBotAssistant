from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config


class CashAndCarryStrategy(BaseStrategy):
    """
    Стратегия #19: Cash-and-Carry (Basis Arbitrage)
    
    Логика:
    - Лонг спот + шорт перп (при +фандинге) или наоборот (при -фандинге)
    - Спот↔квартальник (contango/backwardation)
    - Дельта-нейтральная стратегия на фандинг
    
    Пороги: 8h-фандинг ≥3-5 б.п. после комиссий/заёма
    По квартальнику APR ≥6-10% после издержек
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.cash_and_carry', {})
        super().__init__("Cash-and-Carry", strategy_config)
        
        self.timeframe = '1h'  # Проверяем раз в час
        self.min_funding_bp = 3  # Минимум 3 б.п. (0.03%)
        self.min_apr_pct = 6     # Минимум 6% APR для квартальника
        self.commission_bp = 5   # Комиссии ~0.05% (5 б.п.)
        
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "arbitrage"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Эта стратегия требует данных о funding rate
        # В текущей реализации мы не можем получить funding напрямую
        # Поэтому пропускаем
        # 
        # В полной реализации нужно:
        # 1. Получить funding_rate из Binance API
        # 2. Рассчитать net funding после комиссий
        # 3. Если funding >= min_funding_bp → открыть позицию
        
        # Пока возвращаем None (стратегия не активна без funding данных)
        return None
        
        # Пример логики (закомментирован):
        # funding_rate = indicators.get('funding_rate', 0)
        # funding_bp = funding_rate * 10000  # Переводим в б.п.
        # 
        # # Учитываем комиссии
        # net_funding_bp = funding_bp - self.commission_bp
        # 
        # if net_funding_bp >= self.min_funding_bp:
        #     # Положительный фандинг: лонг спот, шорт перп
        #     current_price = df['close'].iloc[-1]
        #     
        #     return Signal(
        #         symbol=symbol,
        #         direction='short',  # Short перп (лонг спот делается отдельно)
        #         entry_price=current_price,
        #         stop_loss=current_price * 1.05,  # Широкий стоп (дельта-нейтрально)
        #         take_profit_1=current_price,  # TP на закрытие позиции
        #         take_profit_2=current_price,
        #         confidence=3.0,
        #         strategy_name=self.name,
        #         metadata={
        #             'type': 'cash_and_carry',
        #             'funding_bp': net_funding_bp,
        #             'side': 'long_spot_short_perp'
        #         }
        #     )
        # elif net_funding_bp <= -self.min_funding_bp:
        #     # Отрицательный фандинг: шорт спот, лонг перп
        #     current_price = df['close'].iloc[-1]
        #     
        #     return Signal(
        #         symbol=symbol,
        #         direction='long',  # Long перп
        #         entry_price=current_price,
        #         stop_loss=current_price * 0.95,
        #         take_profit_1=current_price,
        #         take_profit_2=current_price,
        #         confidence=3.0,
        #         strategy_name=self.name,
        #         metadata={
        #             'type': 'cash_and_carry',
        #             'funding_bp': abs(net_funding_bp),
        #             'side': 'short_spot_long_perp'
        #         }
        #     )
