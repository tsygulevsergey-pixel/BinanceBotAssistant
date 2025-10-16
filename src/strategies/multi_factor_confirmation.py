"""
Multi-Factor Confirmation System - ФАЗА 3
Требует множественное подтверждение сигналов для достижения 80%+ Win Rate

6 Факторов Подтверждения:
1. ✅ Strategy Signal (базовый сигнал стратегии) - ОБЯЗАТЕЛЬНО
2. HTF Trend Alignment (Higher Timeframe тренд)
3. Volume Confirmation (повышенный объём)
4. CVD/DOI Confirmation (дельта объёма/OI)
5. Price Action Patterns (Pin Bar, Engulfing)
6. S/R Zone Confluence (цена у важного уровня)

Минимум: 3/6 факторов для принятия сигнала
"""

from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
from dataclasses import dataclass
from src.utils.logger import logger as strategy_logger
from src.indicators.technical import calculate_ema


@dataclass
class ConfirmationFactors:
    """Результат проверки факторов подтверждения"""
    strategy_signal: bool = True  # Всегда True (базовый сигнал)
    htf_alignment: bool = False
    volume_confirmation: bool = False
    cvd_doi_confirmation: bool = False
    price_action_pattern: bool = False
    sr_zone_confluence: bool = False
    
    def count(self) -> int:
        """Количество подтверждённых факторов"""
        return sum([
            self.strategy_signal,
            self.htf_alignment,
            self.volume_confirmation,
            self.cvd_doi_confirmation,
            self.price_action_pattern,
            self.sr_zone_confluence
        ])
    
    def get_confirmed_list(self) -> List[str]:
        """Список подтверждённых факторов"""
        confirmed = []
        if self.strategy_signal:
            confirmed.append("Strategy")
        if self.htf_alignment:
            confirmed.append("HTF")
        if self.volume_confirmation:
            confirmed.append("Volume")
        if self.cvd_doi_confirmation:
            confirmed.append("CVD/DOI")
        if self.price_action_pattern:
            confirmed.append("PriceAction")
        if self.sr_zone_confluence:
            confirmed.append("S/R")
        return confirmed


class MultiFactorConfirmation:
    """
    Multi-Factor Confirmation System
    
    Проверяет множественные факторы подтверждения для повышения Win Rate
    """
    
    def __init__(self, config: Any):
        # Минимальное количество факторов для принятия сигнала
        self.min_factors = config.get('multi_factor.min_confirmation_factors', 3)
        
        # Пороги для каждого фактора
        self.volume_multiplier = config.get('multi_factor.volume_multiplier', 1.5)
        self.cvd_threshold = config.get('multi_factor.cvd_threshold', 0)  # CVD > 0 для LONG, < 0 для SHORT
        self.sr_zone_atr_distance = config.get('multi_factor.sr_zone_atr_distance', 0.5)  # Расстояние до S/R зоны
        
        strategy_logger.info(
            f"🎯 Multi-Factor Confirmation System initialized: "
            f"min_factors={self.min_factors}, volume_mult={self.volume_multiplier}x"
        )
    
    def check_factors(
        self,
        symbol: str,
        direction: str,
        df: pd.DataFrame,
        df_1h: Optional[pd.DataFrame],
        df_4h: Optional[pd.DataFrame],
        indicators: Dict,
        regime: str
    ) -> Tuple[bool, ConfirmationFactors]:
        """
        Проверяет все факторы подтверждения
        
        Returns:
            (approved, factors): approved=True если достаточно факторов
        """
        factors = ConfirmationFactors()
        
        # ФАКТОР 1: Strategy Signal - всегда True (базовый сигнал уже есть)
        factors.strategy_signal = True
        
        # ФАКТОР 2: HTF Trend Alignment
        factors.htf_alignment = self._check_htf_alignment(direction, df_1h, df_4h, regime)
        
        # ФАКТОР 3: Volume Confirmation
        factors.volume_confirmation = self._check_volume(df, self.volume_multiplier)
        
        # ФАКТОР 4: CVD/DOI Confirmation
        factors.cvd_doi_confirmation = self._check_cvd_doi(direction, indicators)
        
        # ФАКТОР 5: Price Action Patterns
        factors.price_action_pattern = self._check_price_action(direction, df)
        
        # ФАКТОР 6: S/R Zone Confluence
        factors.sr_zone_confluence = self._check_sr_zone(df, indicators)
        
        # Проверка минимального количества
        confirmed_count = factors.count()
        approved = confirmed_count >= self.min_factors
        
        confirmed_list = factors.get_confirmed_list()
        strategy_logger.debug(
            f"    📊 Multi-Factor: {confirmed_count}/{6} confirmed: {', '.join(confirmed_list)} "
            f"→ {'✅ APPROVED' if approved else f'❌ REJECTED (need {self.min_factors})'}"
        )
        
        return (approved, factors)
    
    def _check_htf_alignment(
        self, 
        direction: str, 
        df_1h: Optional[pd.DataFrame],
        df_4h: Optional[pd.DataFrame],
        regime: str
    ) -> bool:
        """
        ФАКТОР 2: Higher Timeframe Trend Alignment
        
        Проверяет совпадение направления сигнала с HTF трендом
        """
        # HTF проверка критична только в TREND режиме
        if regime != 'TREND':
            strategy_logger.debug(f"      HTF: skip (regime={regime}, не TREND)")
            return True  # В non-TREND режимах HTF не критичен
        
        # Проверяем 1H и 4H
        if df_1h is None or len(df_1h) < 50:
            strategy_logger.debug(f"      HTF: нет данных 1H")
            return False
        
        if df_4h is None or len(df_4h) < 50:
            strategy_logger.debug(f"      HTF: нет данных 4H")
            return False
        
        # EMA50 на обоих таймфреймах
        ema50_1h = calculate_ema(pd.Series(df_1h['close']), period=50)
        ema50_4h = calculate_ema(pd.Series(df_4h['close']), period=50)
        
        price_1h = df_1h['close'].iloc[-1]
        price_4h = df_4h['close'].iloc[-1]
        
        if direction == 'LONG':
            # Для LONG нужен uptrend на HTF
            htf_1h_up = price_1h > ema50_1h.iloc[-1]
            htf_4h_up = price_4h > ema50_4h.iloc[-1]
            aligned = htf_1h_up and htf_4h_up
            strategy_logger.debug(
                f"      HTF: 1H={'UP' if htf_1h_up else 'DOWN'}, "
                f"4H={'UP' if htf_4h_up else 'DOWN'} → {'✅' if aligned else '❌'}"
            )
            return aligned
        else:  # SHORT
            # Для SHORT нужен downtrend на HTF
            htf_1h_down = price_1h < ema50_1h.iloc[-1]
            htf_4h_down = price_4h < ema50_4h.iloc[-1]
            aligned = htf_1h_down and htf_4h_down
            strategy_logger.debug(
                f"      HTF: 1H={'DOWN' if htf_1h_down else 'UP'}, "
                f"4H={'DOWN' if htf_4h_down else 'UP'} → {'✅' if aligned else '❌'}"
            )
            return aligned
    
    def _check_volume(self, df: pd.DataFrame, multiplier: float) -> bool:
        """
        ФАКТОР 3: Volume Confirmation
        
        Текущий объём должен быть выше среднего
        """
        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].tail(20).mean()
        
        confirmed = current_volume > multiplier * avg_volume
        ratio = current_volume / avg_volume
        
        strategy_logger.debug(
            f"      Volume: {ratio:.1f}x avg (need >{multiplier}x) → {'✅' if confirmed else '❌'}"
        )
        return confirmed
    
    def _check_cvd_doi(self, direction: str, indicators: Dict) -> bool:
        """
        ФАКТОР 4: CVD/DOI Confirmation
        
        Cumulative Volume Delta и Delta OI должны подтверждать направление
        """
        cvd = indicators.get('cvd', 0)
        doi_pct = indicators.get('doi_pct', 0)
        
        if direction == 'LONG':
            # Для LONG нужен положительный CVD (покупки)
            cvd_ok = cvd > self.cvd_threshold
            doi_ok = doi_pct > 0  # Положительная дельта OI
            confirmed = cvd_ok or doi_ok  # Достаточно одного из двух
            strategy_logger.debug(
                f"      CVD/DOI: CVD={cvd:.1f} {'✅' if cvd_ok else '❌'}, "
                f"DOI={doi_pct:.1f}% {'✅' if doi_ok else '❌'} → {'✅' if confirmed else '❌'}"
            )
            return confirmed
        else:  # SHORT
            # Для SHORT нужен отрицательный CVD (продажи)
            cvd_ok = cvd < -self.cvd_threshold
            doi_ok = doi_pct < 0  # Отрицательная дельта OI
            confirmed = cvd_ok or doi_ok
            strategy_logger.debug(
                f"      CVD/DOI: CVD={cvd:.1f} {'✅' if cvd_ok else '❌'}, "
                f"DOI={doi_pct:.1f}% {'✅' if doi_ok else '❌'} → {'✅' if confirmed else '❌'}"
            )
            return confirmed
    
    def _check_price_action(self, direction: str, df: pd.DataFrame) -> bool:
        """
        ФАКТОР 5: Price Action Patterns
        
        Pin Bar или Engulfing паттерны подтверждают reversal/continuation
        """
        if len(df) < 2:
            return False
        
        # Последняя и предыдущая свечи
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        
        # Pin Bar detection
        body = abs(curr['close'] - curr['open'])
        total_range = curr['high'] - curr['low']
        
        if total_range == 0:
            return False
        
        body_pct = body / total_range
        
        # Pin Bar: маленькое тело (<30% от range) + длинный хвост
        is_pin_bar = body_pct < 0.3
        
        if direction == 'LONG':
            # Bullish Pin Bar: длинный нижний хвост
            lower_wick = curr['open'] - curr['low'] if curr['close'] > curr['open'] else curr['close'] - curr['low']
            lower_wick_pct = lower_wick / total_range
            pin_bar_bullish = is_pin_bar and lower_wick_pct > 0.6
            
            # Bullish Engulfing
            engulfing = (
                prev['close'] < prev['open'] and  # Prev bearish
                curr['close'] > curr['open'] and  # Curr bullish
                curr['close'] > prev['open'] and  # Engulfs prev high
                curr['open'] < prev['close']      # Engulfs prev low
            )
            
            confirmed = pin_bar_bullish or engulfing
            pattern = "PinBar" if pin_bar_bullish else ("Engulfing" if engulfing else "None")
            strategy_logger.debug(f"      PriceAction: {pattern} → {'✅' if confirmed else '❌'}")
            return confirmed
        
        else:  # SHORT
            # Bearish Pin Bar: длинный верхний хвост
            upper_wick = curr['high'] - curr['open'] if curr['close'] < curr['open'] else curr['high'] - curr['close']
            upper_wick_pct = upper_wick / total_range
            pin_bar_bearish = is_pin_bar and upper_wick_pct > 0.6
            
            # Bearish Engulfing
            engulfing = (
                prev['close'] > prev['open'] and  # Prev bullish
                curr['close'] < curr['open'] and  # Curr bearish
                curr['close'] < prev['open'] and  # Engulfs prev low
                curr['open'] > prev['close']      # Engulfs prev high
            )
            
            confirmed = pin_bar_bearish or engulfing
            pattern = "PinBar" if pin_bar_bearish else ("Engulfing" if engulfing else "None")
            strategy_logger.debug(f"      PriceAction: {pattern} → {'✅' if confirmed else '❌'}")
            return confirmed
    
    def _check_sr_zone(self, df: pd.DataFrame, indicators: Dict) -> bool:
        """
        ФАКТОР 6: S/R Zone Confluence
        
        Цена находится рядом с важным уровнем Support/Resistance
        
        Использует POC (Point of Control) из Volume Profile как key level
        """
        current_price = df['close'].iloc[-1]
        
        # Получаем POC из indicators (если есть)
        poc = indicators.get('poc')
        if poc is None:
            strategy_logger.debug(f"      S/R: нет POC данных")
            return False
        
        # Проверяем расстояние до POC
        atr = indicators.get('atr', df['close'].iloc[-1] * 0.01)  # Fallback 1% если нет ATR
        distance_to_poc = abs(current_price - poc)
        distance_in_atr = distance_to_poc / atr
        
        # Confluence если цена близко к POC (в пределах sr_zone_atr_distance ATR)
        confirmed = distance_in_atr <= self.sr_zone_atr_distance
        
        strategy_logger.debug(
            f"      S/R: price={current_price:.2f}, POC={poc:.2f}, "
            f"dist={distance_in_atr:.2f}×ATR (need ≤{self.sr_zone_atr_distance}) → {'✅' if confirmed else '❌'}"
        )
        return confirmed
    
    def calculate_factor_bonus(self, factors: ConfirmationFactors) -> float:
        """
        Рассчитывает score бонус в зависимости от количества факторов
        
        3 факторов = +0.5
        4 факторов = +1.0
        5 факторов = +1.5
        6 факторов = +2.5
        """
        count = factors.count()
        
        if count >= 6:
            return 2.5
        elif count >= 5:
            return 1.5
        elif count >= 4:
            return 1.0
        elif count >= 3:
            return 0.5
        else:
            return 0.0
