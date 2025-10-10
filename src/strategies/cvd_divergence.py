from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.indicators.technical import calculate_atr


class CVDDivergenceStrategy(BaseStrategy):
    """
    Стратегия #13: CVD Divergence (дивергенции по балансу агрессоров)
    
    Логика:
    - Для MR: дивергенция между ценой и CVD (цена растет, CVD падает → разворот)
    - Для пробоя: подтверждение CVD в направлении движения
    
    У уровня/в режиме; точные данные из aggTrades или барная CVD из klines
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.cvd_divergence', {})
        super().__init__("CVD Divergence", strategy_config)
        
        self.timeframe = '15m'
        self.lookback_bars = 20  # Для поиска дивергенций
        self.divergence_threshold = 0.3  # Порог для определения дивергенции
        
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"  # Базово MR, но может быть breakout
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < self.lookback_bars + 10:
            return None
        
        # CVD из indicators
        cvd = indicators.get('cvd', 0)
        
        # Рассчитываем барную CVD из klines если нет тиковой
        if cvd == 0:
            # Барная CVD: buy volume - sell volume
            buy_volume = df.get('takerBuyBaseAssetVolume', df['volume'] * 0.5)
            sell_volume = df['volume'] - buy_volume
            cvd_series = (buy_volume - sell_volume).cumsum()
        else:
            # Используем существующий CVD
            cvd_series = pd.Series([cvd] * len(df), index=df.index)
        
        # Поиск дивергенции
        divergence_type = self._detect_divergence(df, cvd_series)
        
        if divergence_type is None:
            return None
        
        # ATR для стопов
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Генерация сигнала
        if divergence_type == 'bearish':
            # Медвежья дивергенция: цена вверх, CVD вниз → short
            return self._create_divergence_signal(
                symbol, df, 'short', current_atr, indicators
            )
        elif divergence_type == 'bullish':
            # Бычья дивергенция: цена вниз, CVD вверх → long
            return self._create_divergence_signal(
                symbol, df, 'long', current_atr, indicators
            )
        elif divergence_type == 'confirmation_long':
            # Подтверждение пробоя вверх
            return self._create_confirmation_signal(
                symbol, df, 'long', current_atr, indicators
            )
        elif divergence_type == 'confirmation_short':
            # Подтверждение пробоя вниз
            return self._create_confirmation_signal(
                symbol, df, 'short', current_atr, indicators
            )
        
        return None
    
    def _detect_divergence(self, df: pd.DataFrame, cvd_series: pd.Series) -> Optional[str]:
        """
        Определяет дивергенции и подтверждения по CVD
        """
        # Последние N баров для анализа
        price_tail = df['close'].tail(self.lookback_bars)
        cvd_tail = cvd_series.tail(self.lookback_bars)
        
        # Находим экстремумы
        price_high_idx = price_tail.idxmax()
        price_low_idx = price_tail.idxmin()
        cvd_high_idx = cvd_tail.idxmax()
        cvd_low_idx = cvd_tail.idxmin()
        
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        # МЕДВЕЖЬЯ ДИВЕРГЕНЦИЯ: цена растет (новый хай), но CVD падает
        if current_close > prev_close:
            # Проверяем что цена делает новый хай
            if price_tail.iloc[-1] == price_tail.max():
                # Но CVD не подтверждает (CVD максимум был раньше)
                if price_high_idx > cvd_high_idx:
                    cvd_divergence = (cvd_tail.max() - cvd_tail.iloc[-1]) / abs(cvd_tail.max())
                    if cvd_divergence > self.divergence_threshold:
                        return 'bearish'
        
        # БЫЧЬЯ ДИВЕРГЕНЦИЯ: цена падает (новый лоу), но CVD растет
        if current_close < prev_close:
            if price_tail.iloc[-1] == price_tail.min():
                if price_low_idx > cvd_low_idx:
                    cvd_divergence = (cvd_tail.iloc[-1] - cvd_tail.min()) / abs(cvd_tail.min())
                    if cvd_divergence > self.divergence_threshold:
                        return 'bullish'
        
        # ПОДТВЕРЖДЕНИЕ ПРОБОЯ: CVD в направлении движения
        # Если цена пробивает вверх И CVD также растет
        recent_high = df['high'].tail(30).iloc[:-3].max()
        if current_close > recent_high and cvd_tail.iloc[-1] > cvd_tail.iloc[-5]:
            return 'confirmation_long'
        
        # Если цена пробивает вниз И CVD также падает
        recent_low = df['low'].tail(30).iloc[:-3].min()
        if current_close < recent_low and cvd_tail.iloc[-1] < cvd_tail.iloc[-5]:
            return 'confirmation_short'
        
        return None
    
    def _create_divergence_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                  atr: float, indicators: Dict) -> Signal:
        """
        Создать сигнал по дивергенции (mean reversion)
        """
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        if direction == 'long':
            entry = current_close
            stop_loss = current_low - 0.3 * atr
            take_profit_1 = entry + 1.0 * atr
            take_profit_2 = entry + 2.0 * atr
            
            return Signal(
                symbol=symbol,
                direction='long',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.5,
                strategy_name=self.name,
                metadata={
                    'type': 'cvd_divergence',
                    'divergence': 'bullish'
                }
            )
        else:
            entry = current_close
            stop_loss = current_high + 0.3 * atr
            take_profit_1 = entry - 1.0 * atr
            take_profit_2 = entry - 2.0 * atr
            
            return Signal(
                symbol=symbol,
                direction='short',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.5,
                strategy_name=self.name,
                metadata={
                    'type': 'cvd_divergence',
                    'divergence': 'bearish'
                }
            )
    
    def _create_confirmation_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                   atr: float, indicators: Dict) -> Signal:
        """
        Создать сигнал подтверждения пробоя (breakout confirmation)
        """
        current_close = df['close'].iloc[-1]
        
        if direction == 'long':
            entry = current_close
            stop_loss = entry - 0.5 * atr
            take_profit_1 = entry + 1.5 * atr
            take_profit_2 = entry + 3.0 * atr
            
            return Signal(
                symbol=symbol,
                direction='long',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.0,
                strategy_name=self.name,
                metadata={
                    'type': 'cvd_confirmation',
                    'confirmation': 'breakout_up'
                }
            )
        else:
            entry = current_close
            stop_loss = entry + 0.5 * atr
            take_profit_1 = entry - 1.5 * atr
            take_profit_2 = entry - 3.0 * atr
            
            return Signal(
                symbol=symbol,
                direction='short',
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                confidence=2.0,
                strategy_name=self.name,
                metadata={
                    'type': 'cvd_confirmation',
                    'confirmation': 'breakout_down'
                }
            )
