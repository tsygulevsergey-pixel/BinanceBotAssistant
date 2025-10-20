from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr
from src.indicators.volume_profile import calculate_volume_profile
from src.utils.reclaim_checker import check_value_area_reclaim
from src.utils.sr_zones_15m import create_sr_zones, find_nearest_zone, calculate_stop_loss_from_zone


class VolumeProfileStrategy(BaseStrategy):
    """
    Стратегия #9: Volume Profile (VAH/VPOC/VAL)
    
    Логика:
    - У края value различаем rejection (fade) vs acceptance (продолжение)
    - REJECTION: close обратно в value, POC не сдвигается, CVD flip, imbalance flip, OI не растёт
    - ACCEPTANCE: ≥2 close за VA или ≥0.25 ATR, объём/POC смещаются, CVD/OI по выходу
    
    Триггеры:
    - Fade: как mean reversion (стоп за экстремум, TP к VWAP/POC)
    - Acceptance: как breakout (стоп за ретест, TP по R-множителю)
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.volume_profile', {})
        super().__init__("Volume Profile", strategy_config)
        
        self.timeframe = '15m'  # Основной таймфрейм
        self.lookback_bars = 100
        self.atr_threshold = 0.25  # ATR для acceptance
        self.min_closes_outside = 2  # Минимум 2 close за VA для acceptance
        self.poc_shift_threshold = 0.1  # Порог смещения POC (% от range)
        self.reclaim_bars = strategy_config.get('reclaim_bars', 2)  # Hold N bars для reclaim
        self.poc_history = {}  # История POC по символам для отслеживания shift
        
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"  # Базово MR, но может быть breakout при acceptance
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < self.lookback_bars:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется {self.lookback_bars}")
            return None
        
        # Рассчитать Volume Profile
        vp_result = calculate_volume_profile(df, num_bins=50)
        vah = vp_result['vah']
        val = vp_result['val']
        poc = vp_result['poc']
        
        # ATR для измерений
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        # Текущая цена и история
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # PRO 2024-2025: Расширена зона до 1.0 ATR для большего охвата (было 0.5)
        near_vah = abs(current_close - vah) <= 1.0 * current_atr
        near_val = abs(current_close - val) <= 1.0 * current_atr
        
        if not (near_vah or near_val):
            strategy_logger.debug(f"    ❌ Цена не около VAH/VAL (расстояние > 1.0 ATR)")
            return None
        
        # Определяем: rejection или acceptance
        signal_type = self._detect_rejection_or_acceptance(
            symbol, df, vah, val, poc, current_atr, indicators
        )
        
        if signal_type is None:
            strategy_logger.debug(f"    ❌ Нет четкого rejection или acceptance паттерна")
            return None
        
        # ФАЗА 2: POC Magnet Filter для RANGE режимов
        # В RANGE/SQUEEZE цена стремится к POC - если далеко, rejection может не сработать
        if 'rejection' in signal_type:
            if regime in ['RANGE', 'SQUEEZE']:
                distance_from_poc = abs(current_close - poc)
                poc_magnet_threshold = 1.5 * current_atr
                
                if distance_from_poc > poc_magnet_threshold:
                    strategy_logger.debug(f"    ❌ POC Magnet Filter: цена далеко от POC ({distance_from_poc:.4f} > {poc_magnet_threshold:.4f}) в {regime} режиме")
                    strategy_logger.debug(f"       Rejection пропущен - цена может вернуться к POC вместо отскока от VAH/VAL")
                    return None
                else:
                    strategy_logger.debug(f"    ✅ POC Magnet Filter: цена близко к POC ({distance_from_poc:.4f} <= {poc_magnet_threshold:.4f})")
        
        # Генерация сигнала в зависимости от типа
        if signal_type == 'rejection_long':
            # FADE SHORT: rejection от VAH, ожидаем возврат вниз
            return self._create_rejection_signal(
                symbol, df, 'short', vah, poc, current_atr, indicators
            )
        elif signal_type == 'rejection_short':
            # FADE LONG: rejection от VAL, ожидаем возврат вверх
            return self._create_rejection_signal(
                symbol, df, 'long', val, poc, current_atr, indicators
            )
        elif signal_type == 'acceptance_long':
            # BREAKOUT LONG: acceptance выше VAH
            return self._create_acceptance_signal(
                symbol, df, 'long', vah, current_atr, indicators
            )
        elif signal_type == 'acceptance_short':
            # BREAKOUT SHORT: acceptance ниже VAL
            return self._create_acceptance_signal(
                symbol, df, 'short', val, current_atr, indicators
            )
        
        strategy_logger.debug(f"    ❌ Неопределенный тип сигнала")
        return None
    
    def _check_poc_shift(self, symbol: str, current_poc: float, price_range: float) -> dict:
        """
        Проверяет, сдвинулся ли POC
        Возвращает: {'shifted': bool, 'direction': str, 'shift_pct': float}
        """
        if symbol not in self.poc_history:
            # Первый раз для этого символа - сохраняем и возвращаем "не сдвинулся"
            self.poc_history[symbol] = current_poc
            return {'shifted': False, 'direction': 'none', 'shift_pct': 0.0}
        
        prev_poc = self.poc_history[symbol]
        poc_diff = current_poc - prev_poc
        shift_pct = abs(poc_diff) / price_range if price_range > 0 else 0
        
        # Обновляем историю
        self.poc_history[symbol] = current_poc
        
        # Порог смещения (по умолчанию 0.1 = 10% от range)
        if shift_pct >= self.poc_shift_threshold:
            direction = 'up' if poc_diff > 0 else 'down'
            return {'shifted': True, 'direction': direction, 'shift_pct': shift_pct}
        else:
            return {'shifted': False, 'direction': 'none', 'shift_pct': shift_pct}
    
    def _detect_rejection_or_acceptance(self, symbol: str, df: pd.DataFrame, vah: float, val: float, 
                                        poc: float, atr: float, indicators: Dict) -> Optional[str]:
        """
        Определяет rejection vs acceptance с POC shift detection и volume spike проверкой
        """
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        current_volume = df['volume'].iloc[-1]
        
        # Volume spike проверка: медиана за последние 50 баров
        median_volume = df['volume'].tail(50).median()
        volume_ratio = current_volume / median_volume if median_volume > 0 else 0
        has_volume_spike = volume_ratio >= 1.5
        
        # CVD из своего timeframe, fallback к верхнеуровневому или 0
        cvd = indicators.get(self.timeframe, {}).get('cvd', indicators.get('cvd', 0))
        
        # Безопасное извлечение скаляра из CVD (если Series)
        if isinstance(cvd, pd.Series):
            cvd_value = cvd.iloc[-1] if len(cvd) > 0 else 0
        else:
            cvd_value = cvd
        
        depth_imbalance = indicators.get('depth_imbalance', 1.0)
        doi_pct = indicators.get('doi_pct', 0)
        
        # История closes за последние 3 бара
        recent_closes = df['close'].tail(3).values
        
        # Проверка POC shift
        price_range = vah - val if vah > val else atr * 2  # Range для расчета shift %
        poc_shift = self._check_poc_shift(symbol, poc, price_range)
        
        # --- ПРОВЕРКА ACCEPTANCE ---
        # Acceptance требует: volume > 1.5× median + POC shift
        # Без volume spike = только rejection signals
        
        # Acceptance выше VAH
        if current_close > vah:
            closes_above = sum(c > vah for c in recent_closes)
            distance_above = current_close - vah
            
            # ≥2 close за VA ИЛИ ≥0.25 ATR
            if closes_above >= self.min_closes_outside or distance_above >= self.atr_threshold * atr:
                # Проверка volume spike
                if not has_volume_spike:
                    strategy_logger.debug(f"    ❌ Acceptance LONG отклонен: нет volume spike (volume {volume_ratio:.2f}x < 1.5x median)")
                    # Без volume spike - только rejection signals, не acceptance
                # ФАЗА 2: Усиленное подтверждение - требуем CVD И Volume Delta в одном направлении
                elif cvd_value > 0 and doi_pct > 1.0 and poc_shift['shifted'] and poc_shift['direction'] == 'up':
                    strategy_logger.debug(f"    ✅ Acceptance LONG: POC shift {poc_shift['direction']} {poc_shift['shift_pct']:.1%}, CVD {cvd_value:.2f}, DOI {doi_pct:.1f}%, volume {volume_ratio:.2f}x")
                    return 'acceptance_long'
                else:
                    cvd_ok = "✅" if cvd_value > 0 else "❌"
                    doi_ok = "✅" if doi_pct > 1.0 else "❌"
                    poc_ok = "✅" if (poc_shift['shifted'] and poc_shift['direction'] == 'up') else "❌"
                    strategy_logger.debug(f"    ❌ Acceptance LONG отклонен: CVD {cvd_ok} ({cvd_value:.2f}), DOI {doi_ok} ({doi_pct:.1f}%), POC shift {poc_ok}")
        
        # Acceptance ниже VAL
        if current_close < val:
            closes_below = sum(c < val for c in recent_closes)
            distance_below = val - current_close
            
            if closes_below >= self.min_closes_outside or distance_below >= self.atr_threshold * atr:
                # Проверка volume spike
                if not has_volume_spike:
                    strategy_logger.debug(f"    ❌ Acceptance SHORT отклонен: нет volume spike (volume {volume_ratio:.2f}x < 1.5x median)")
                    # Без volume spike - только rejection signals
                # ФАЗА 2: Усиленное подтверждение - требуем CVD И Volume Delta в одном направлении
                elif cvd_value < 0 and doi_pct < -1.0 and poc_shift['shifted'] and poc_shift['direction'] == 'down':
                    strategy_logger.debug(f"    ✅ Acceptance SHORT: POC shift {poc_shift['direction']} {poc_shift['shift_pct']:.1%}, CVD {cvd_value:.2f}, DOI {doi_pct:.1f}%, volume {volume_ratio:.2f}x")
                    return 'acceptance_short'
                else:
                    cvd_ok = "✅" if cvd_value < 0 else "❌"
                    doi_ok = "✅" if doi_pct < -1.0 else "❌"
                    poc_ok = "✅" if (poc_shift['shifted'] and poc_shift['direction'] == 'down') else "❌"
                    strategy_logger.debug(f"    ❌ Acceptance SHORT отклонен: CVD {cvd_ok} ({cvd_value:.2f}), DOI {doi_ok} ({doi_pct:.1f}%), POC shift {poc_ok}")
        
        # --- ПРОВЕРКА REJECTION с RECLAIM механизмом ---
        # Rejection от VAH: RECLAIM - цена была выше VAH, вернулась в value area и удержалась
        vah_reclaim = check_value_area_reclaim(
            df=df,
            val=val,
            vah=vah,
            direction='short',  # для rejection от VAH
            hold_bars=self.reclaim_bars
        )
        
        if vah_reclaim:
            # CVD flip (было покупки, стали продажи)
            if cvd_value < 0:
                # Imbalance flip (depth показывает давление вниз)
                if depth_imbalance > 1.1:  # Больше ask = давление продаж
                    # OI не растёт сильно + POC НЕ сдвигается (rejection признак)
                    if doi_pct < 2.0 and not poc_shift['shifted']:
                        strategy_logger.debug(f"    ✅ Rejection LONG: POC не сдвинулся (shift {poc_shift['shift_pct']:.1%}), volume {volume_ratio:.2f}x")
                        return 'rejection_long'  # Rejection вниз = fade short (но вход long при откате)
        
        # Rejection от VAL: RECLAIM - цена была ниже VAL, вернулась в value area и удержалась
        val_reclaim = check_value_area_reclaim(
            df=df,
            val=val,
            vah=vah,
            direction='long',  # для rejection от VAL
            hold_bars=self.reclaim_bars
        )
        
        if val_reclaim:
            # CVD flip вверх
            if cvd_value > 0:
                # Imbalance flip вверх
                if depth_imbalance < 0.9:  # Больше bid = давление покупок
                    # OI не растёт + POC НЕ сдвигается
                    if doi_pct < 2.0 and not poc_shift['shifted']:
                        strategy_logger.debug(f"    ✅ Rejection SHORT: POC не сдвинулся (shift {poc_shift['shift_pct']:.1%}), volume {volume_ratio:.2f}x")
                        return 'rejection_short'  # Rejection вверх = fade long
        
        return None
    
    def _create_rejection_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                 level: float, poc: float, atr: float, 
                                 indicators: Dict) -> Signal:
        """
        Создать сигнал FADE (rejection) - как mean reversion
        """
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        if direction == 'long':
            entry = current_close
            
            # Расчет зон S/R для точного стопа
            sr_zones = create_sr_zones(df, atr, buffer_mult=0.25)
            nearest_zone = find_nearest_zone(entry, sr_zones, 'LONG')
            stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, atr, 'LONG', fallback_mult=2.0, max_distance_atr=5.0)
            
            # Расчет дистанции и тейков 1R и 2R
            atr_distance = abs(entry - stop_loss)
            take_profit_1 = entry + atr_distance * 1.0  # 1R
            take_profit_2 = entry + atr_distance * 2.0  # 2R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(take_profit_1),
                take_profit_2=float(take_profit_2),
                regime='RANGE',
                bias='neutral',
                base_score=2.5,
                metadata={
                    'type': 'rejection_fade',
                    'level': float(level),
                    'poc': float(poc),
                    'reclaim_bars': self.reclaim_bars
                }
            )
        else:
            entry = current_close
            
            # Расчет зон S/R для точного стопа
            sr_zones = create_sr_zones(df, atr, buffer_mult=0.25)
            nearest_zone = find_nearest_zone(entry, sr_zones, 'SHORT')
            stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, atr, 'SHORT', fallback_mult=2.0, max_distance_atr=5.0)
            
            # Расчет дистанции и тейков 1R и 2R
            atr_distance = abs(stop_loss - entry)
            take_profit_1 = entry - atr_distance * 1.0  # 1R
            take_profit_2 = entry - atr_distance * 2.0  # 2R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(take_profit_1),
                take_profit_2=float(take_profit_2),
                regime='RANGE',
                bias='neutral',
                base_score=2.5,
                metadata={
                    'type': 'rejection_fade',
                    'level': float(level),
                    'poc': float(poc),
                    'reclaim_bars': self.reclaim_bars
                }
            )
    
    def _create_acceptance_signal(self, symbol: str, df: pd.DataFrame, direction: str,
                                  level: float, atr: float, indicators: Dict) -> Signal:
        """
        Создать сигнал ACCEPTANCE (breakout) - как трендовая стратегия
        """
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # Получаем POC shift info
        vp_result = calculate_volume_profile(df, num_bins=50)
        poc = vp_result['poc']
        vah = vp_result['vah']
        val = vp_result['val']
        price_range = vah - val if vah > val else atr * 2
        poc_shift = self._check_poc_shift(symbol, poc, price_range)
        
        if direction == 'long':
            entry = current_close
            
            # Расчет зон S/R для точного стопа
            sr_zones = create_sr_zones(df, atr, buffer_mult=0.25)
            nearest_zone = find_nearest_zone(entry, sr_zones, 'LONG')
            stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, atr, 'LONG', fallback_mult=2.0, max_distance_atr=5.0)
            
            # Расчет дистанции и тейков 1R и 2R
            atr_distance = abs(entry - stop_loss)
            take_profit_1 = entry + atr_distance * 1.0  # 1R
            take_profit_2 = entry + atr_distance * 2.0  # 2R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='LONG',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(take_profit_1),
                take_profit_2=float(take_profit_2),
                regime='EXPANSION',
                bias='neutral',
                base_score=2.0,
                metadata={
                    'type': 'acceptance_breakout',
                    'level': float(level),
                    'poc_shifted': poc_shift['shifted'],
                    'poc_shift_direction': poc_shift['direction'],
                    'poc_shift_pct': float(poc_shift['shift_pct'])
                }
            )
        else:
            entry = current_close
            
            # Расчет зон S/R для точного стопа
            sr_zones = create_sr_zones(df, atr, buffer_mult=0.25)
            nearest_zone = find_nearest_zone(entry, sr_zones, 'SHORT')
            stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, atr, 'SHORT', fallback_mult=2.0, max_distance_atr=5.0)
            
            # Расчет дистанции и тейков 1R и 2R
            atr_distance = abs(stop_loss - entry)
            take_profit_1 = entry - atr_distance * 1.0  # 1R
            take_profit_2 = entry - atr_distance * 2.0  # 2R
            
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction='SHORT',
                timestamp=pd.Timestamp.now(),
                timeframe=self.timeframe,
                entry_price=float(entry),
                stop_loss=float(stop_loss),
                take_profit_1=float(take_profit_1),
                take_profit_2=float(take_profit_2),
                regime='EXPANSION',
                bias='neutral',
                base_score=2.0,
                metadata={
                    'type': 'acceptance_breakout',
                    'level': float(level),
                    'poc_shifted': poc_shift['shifted'],
                    'poc_shift_direction': poc_shift['direction'],
                    'poc_shift_pct': float(poc_shift['shift_pct'])
                }
            )
