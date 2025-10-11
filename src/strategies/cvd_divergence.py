from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
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
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется {self.lookback_bars + 10}")
            return None
        
        # Получаем CVD Series из indicators или рассчитываем
        cvd = indicators.get(self.timeframe, {}).get('cvd', indicators.get('cvd', None))
        
        # Проверяем тип CVD
        if cvd is None or (isinstance(cvd, (int, float)) and cvd == 0):
            # Рассчитываем барную CVD из klines
            buy_volume = df.get('takerBuyBaseAssetVolume', df['volume'] * 0.5)
            sell_volume = df['volume'] - buy_volume
            cvd_series = (buy_volume - sell_volume).cumsum()
        elif isinstance(cvd, pd.Series):
            # CVD уже Series - используем напрямую
            cvd_series = cvd
            if len(cvd_series) != len(df):
                strategy_logger.debug(f"    ❌ Длина CVD Series ({len(cvd_series)}) не совпадает с df ({len(df)})")
                return None
        else:
            # CVD скаляр - это последнее значение, нужно рассчитать историю
            strategy_logger.debug(f"    ⚠️ CVD передан как скаляр ({cvd}), рассчитываем барную CVD")
            buy_volume = df.get('takerBuyBaseAssetVolume', df['volume'] * 0.5)
            sell_volume = df['volume'] - buy_volume
            cvd_series = (buy_volume - sell_volume).cumsum()
        
        # Regime фильтр: дивергенции лучше работают в RANGE/SQUEEZE, хуже в TREND
        regime_score_multiplier = 1.0
        if regime == 'TREND':
            strategy_logger.debug(f"    ⚠️ Режим TREND - дивергенции менее надежны, уменьшаем score")
            regime_score_multiplier = 0.5  # Снижаем score в 2 раза
        elif regime in ['RANGE', 'SQUEEZE', 'CHOP']:
            strategy_logger.debug(f"    ✅ Режим {regime} - оптимален для дивергенций")
            regime_score_multiplier = 1.0
        
        # Поиск дивергенции с volume проверкой
        divergence_type = self._detect_divergence(df, cvd_series, regime_score_multiplier)
        
        if divergence_type is None:
            strategy_logger.debug(f"    ❌ Нет дивергенции или подтверждения CVD по цене")
            return None
        
        # ATR для стопов
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Генерация сигнала с учетом regime score multiplier
        if divergence_type == 'bearish':
            # Медвежья дивергенция: цена вверх, CVD вниз → short
            return self._create_divergence_signal(
                symbol, df, 'short', current_atr, indicators, regime_score_multiplier
            )
        elif divergence_type == 'bullish':
            # Бычья дивергенция: цена вниз, CVD вверх → long
            return self._create_divergence_signal(
                symbol, df, 'long', current_atr, indicators, regime_score_multiplier
            )
        elif divergence_type == 'confirmation_long':
            # Подтверждение пробоя вверх
            return self._create_confirmation_signal(
                symbol, df, 'long', current_atr, indicators, regime_score_multiplier
            )
        elif divergence_type == 'confirmation_short':
            # Подтверждение пробоя вниз
            return self._create_confirmation_signal(
                symbol, df, 'short', current_atr, indicators, regime_score_multiplier
            )
        
        strategy_logger.debug(f"    ❌ Неопределенный тип CVD сигнала")
        return None
    
    def _detect_divergence(self, df: pd.DataFrame, cvd_series: pd.Series, regime_score_multiplier: float = 1.0) -> Optional[str]:
        """
        Определяет дивергенции и подтверждения по CVD
        Правильная логика: сравнивает ДВА последних пика/минимума
        Добавлена volume проверка в точках дивергенции
        """
        # Последние N баров для анализа
        price_tail = df['close'].tail(self.lookback_bars).reset_index(drop=True)
        cvd_tail = cvd_series.tail(self.lookback_bars).reset_index(drop=True)
        volume_tail = df['volume'].tail(self.lookback_bars).reset_index(drop=True)
        
        # Медиана объема для фильтрации
        median_volume = volume_tail.median()
        
        # Находим локальные максимумы и минимумы (с минимальным расстоянием 3 бара)
        price_highs = self._find_local_peaks(price_tail, order=3)
        price_lows = self._find_local_troughs(price_tail, order=3)
        cvd_highs = self._find_local_peaks(cvd_tail, order=3)
        cvd_lows = self._find_local_troughs(cvd_tail, order=3)
        
        # МЕДВЕЖЬЯ ДИВЕРГЕНЦИЯ: цена делает Higher High, но CVD делает Lower High
        if len(price_highs) >= 2:
            # Берем 2 последних пика цены
            last_price_high_idx = price_highs[-1]
            prev_price_high_idx = price_highs[-2]
            
            last_price_high = price_tail[last_price_high_idx]
            prev_price_high = price_tail[prev_price_high_idx]
            
            # Volume проверка в точке дивергенции
            last_volume = volume_tail[last_price_high_idx]
            if last_volume < median_volume:
                strategy_logger.debug(f"    ⚠️ Объем в точке дивергенции низкий: {last_volume:.0f} < median {median_volume:.0f}")
                # Не возвращаем None, но снижаем вероятность прохождения threshold
            
            # Проверяем что цена делает Higher High
            if last_price_high > prev_price_high:
                # Получаем CVD в этих точках
                last_cvd_at_price_high = cvd_tail[last_price_high_idx]
                prev_cvd_at_price_high = cvd_tail[prev_price_high_idx]
                
                # Проверяем что CVD делает Lower High (дивергенция!)
                if last_cvd_at_price_high < prev_cvd_at_price_high:
                    cvd_drop = (prev_cvd_at_price_high - last_cvd_at_price_high) / (abs(prev_cvd_at_price_high) + 1e-8)
                    if cvd_drop > self.divergence_threshold and last_volume >= median_volume:
                        strategy_logger.debug(f"    ✅ Медвежья дивергенция: HH цены {prev_price_high:.4f} → {last_price_high:.4f}, но LH CVD {prev_cvd_at_price_high:.2f} → {last_cvd_at_price_high:.2f}, volume {last_volume:.0f} >= median")
                        return 'bearish'
                    elif cvd_drop > self.divergence_threshold:
                        strategy_logger.debug(f"    ❌ Медвежья дивергенция найдена, но volume низкий: {last_volume:.0f} < {median_volume:.0f}")
                        return None
        
        # БЫЧЬЯ ДИВЕРГЕНЦИЯ: цена делает Lower Low, но CVD делает Higher Low
        if len(price_lows) >= 2:
            # Берем 2 последних минимума цены
            last_price_low_idx = price_lows[-1]
            prev_price_low_idx = price_lows[-2]
            
            last_price_low = price_tail[last_price_low_idx]
            prev_price_low = price_tail[prev_price_low_idx]
            
            # Volume проверка в точке дивергенции
            last_volume = volume_tail[last_price_low_idx]
            if last_volume < median_volume:
                strategy_logger.debug(f"    ⚠️ Объем в точке дивергенции низкий: {last_volume:.0f} < median {median_volume:.0f}")
            
            # Проверяем что цена делает Lower Low
            if last_price_low < prev_price_low:
                # Получаем CVD в этих точках
                last_cvd_at_price_low = cvd_tail[last_price_low_idx]
                prev_cvd_at_price_low = cvd_tail[prev_price_low_idx]
                
                # Проверяем что CVD делает Higher Low (дивергенция!)
                if last_cvd_at_price_low > prev_cvd_at_price_low:
                    cvd_rise = (last_cvd_at_price_low - prev_cvd_at_price_low) / (abs(prev_cvd_at_price_low) + 1e-8)
                    if cvd_rise > self.divergence_threshold and last_volume >= median_volume:
                        strategy_logger.debug(f"    ✅ Бычья дивергенция: LL цены {prev_price_low:.4f} → {last_price_low:.4f}, но HL CVD {prev_cvd_at_price_low:.2f} → {last_cvd_at_price_low:.2f}, volume {last_volume:.0f} >= median")
                        return 'bullish'
                    elif cvd_rise > self.divergence_threshold:
                        strategy_logger.debug(f"    ❌ Бычья дивергенция найдена, но volume низкий: {last_volume:.0f} < {median_volume:.0f}")
                        return None
        
        # ПОДТВЕРЖДЕНИЕ ПРОБОЯ: CVD в направлении движения
        # Если цена пробивает вверх И CVD также растет
        recent_high = df['high'].tail(30).iloc[:-3].max()
        current_close = df['close'].iloc[-1]
        if current_close > recent_high and cvd_tail.iloc[-1] > cvd_tail.iloc[-5]:
            return 'confirmation_long'
        
        # Если цена пробивает вниз И CVD также падает
        recent_low = df['low'].tail(30).iloc[:-3].min()
        if current_close < recent_low and cvd_tail.iloc[-1] < cvd_tail.iloc[-5]:
            return 'confirmation_short'
        
        return None
    
    def _find_local_peaks(self, series: pd.Series, order: int = 3) -> list:
        """
        Найти локальные максимумы (пики)
        order = минимальное расстояние между пиками
        """
        peaks = []
        for i in range(order, len(series) - order):
            # Проверяем что точка выше соседей
            if all(series[i] >= series[i-j] for j in range(1, order+1)) and \
               all(series[i] >= series[i+j] for j in range(1, order+1)):
                peaks.append(i)
        return peaks
    
    def _find_local_troughs(self, series: pd.Series, order: int = 3) -> list:
        """
        Найти локальные минимумы (впадины)
        order = минимальное расстояние между минимумами
        """
        troughs = []
        for i in range(order, len(series) - order):
            # Проверяем что точка ниже соседей
            if all(series[i] <= series[i-j] for j in range(1, order+1)) and \
               all(series[i] <= series[i+j] for j in range(1, order+1)):
                troughs.append(i)
        return troughs
    
    def _create_divergence_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                  atr: float, indicators: Dict, regime_score_multiplier: float = 1.0) -> Signal:
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
                strategy_name=self.name,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                base_score=2.5 * regime_score_multiplier,
                metadata={
                    'type': 'cvd_divergence',
                    'divergence': 'bullish',
                    'regime_multiplier': regime_score_multiplier
                }
            )
        else:
            entry = current_close
            stop_loss = current_high + 0.3 * atr
            take_profit_1 = entry - 1.0 * atr
            take_profit_2 = entry - 2.0 * atr
            
            return Signal(
                symbol=symbol,
                strategy_name=self.name,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                base_score=2.5 * regime_score_multiplier,
                metadata={
                    'type': 'cvd_divergence',
                    'divergence': 'bearish',
                    'regime_multiplier': regime_score_multiplier
                }
            )
    
    def _create_confirmation_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                   atr: float, indicators: Dict, regime_score_multiplier: float = 1.0) -> Signal:
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
                strategy_name=self.name,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                base_score=2.0 * regime_score_multiplier,
                metadata={
                    'type': 'cvd_confirmation',
                    'confirmation': 'breakout_up',
                    'regime_multiplier': regime_score_multiplier
                }
            )
        else:
            entry = current_close
            stop_loss = entry + 0.5 * atr
            take_profit_1 = entry - 1.5 * atr
            take_profit_2 = entry - 3.0 * atr
            
            return Signal(
                symbol=symbol,
                strategy_name=self.name,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                base_score=2.0 * regime_score_multiplier,
                metadata={
                    'type': 'cvd_confirmation',
                    'confirmation': 'breakout_down',
                    'regime_multiplier': regime_score_multiplier
                }
            )
