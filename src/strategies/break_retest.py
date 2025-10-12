from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_atr, calculate_adx
from src.utils.sr_zones_15m import create_sr_zones, find_nearest_zone, calculate_stop_loss_from_zone


class BreakRetestStrategy(BaseStrategy):
    """
    Стратегия #5: Break & Retest
    
    Логика по мануалу:
    - Пробой с close ≥0.25 ATR и объёмом >1.5–2×
    - Зона ретеста = экстремум±0.2–0.3 ATR ∩ AVWAP(бар пробоя)
    - Триггер: 50% лимитом в зоне, 50% — по подтверждению
    - Стоп: за свинг-реакцией +0.2–0.3 ATR
    - Подтверждения: CVD flip, imbalance flip/refill, OI не падает
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.retest', {})
        super().__init__("Break & Retest", strategy_config)
        
        self.breakout_atr = strategy_config.get('breakout_atr', 0.25)
        self.zone_atr = strategy_config.get('zone_atr', [0.2, 0.3])
        self.volume_threshold = strategy_config.get('volume_threshold', 1.5)
        self.split_ratio = strategy_config.get('split_ratio', 0.5)  # 50/50
        self.timeframe = '15m'
        self.breakout_lookback = 20  # Ищем пробои за последние 20 баров
        self.adx_threshold = config.get('market_detector.trend.adx_threshold', 20)
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "pullback"
    
    def _find_swing_high_low(self, df: pd.DataFrame, end_pos: int, lookback: int = 20, buffer: int = 3) -> Dict:
        """Найти swing high/low с буфером N баров
        Args:
            end_pos: ПОЛОЖИТЕЛЬНЫЙ индекс окончания поиска
        """
        # Проверка границ
        start_pos = max(buffer, end_pos - lookback)
        
        swing_high = None
        swing_high_idx = None
        swing_low = None
        swing_low_idx = None
        
        # Ищем swing high (пик с buffer баров с каждой стороны)
        for i in range(start_pos, end_pos - buffer):
            if i < buffer or i + buffer >= len(df):
                continue
            
            high_val = df['high'].iloc[i]
            is_swing_high = True
            
            # Проверяем, что это локальный максимум
            for j in range(i - buffer, i + buffer + 1):
                if j != i and df['high'].iloc[j] >= high_val:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                swing_high = high_val
                swing_high_idx = i
        
        # Ищем swing low (впадина с buffer баров с каждой стороны)
        for i in range(start_pos, end_pos - buffer):
            if i < buffer or i + buffer >= len(df):
                continue
            
            low_val = df['low'].iloc[i]
            is_swing_low = True
            
            # Проверяем, что это локальный минимум
            for j in range(i - buffer, i + buffer + 1):
                if j != i and df['low'].iloc[j] <= low_val:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                swing_low = low_val
                swing_low_idx = i
        
        return {
            'swing_high': swing_high,
            'swing_high_idx': swing_high_idx,
            'swing_low': swing_low,
            'swing_low_idx': swing_low_idx
        }
    
    def _find_recent_breakout(self, df: pd.DataFrame, atr: pd.Series, vwap: pd.Series, adx: pd.Series) -> Optional[Dict]:
        """Найти недавний пробой с использованием swing levels и ADX фильтром"""
        df_len = len(df)
        
        for i in range(-self.breakout_lookback, -1):  # До -1, чтобы не включать текущий бар
            if abs(i) >= df_len:
                continue
            
            # Конвертируем отрицательный индекс в положительный
            pos_idx = df_len + i
            
            bar_close = df['close'].iloc[i]
            bar_high = df['high'].iloc[i]
            bar_low = df['low'].iloc[i]
            bar_volume = df['volume'].iloc[i]
            bar_atr = atr.iloc[i]
            bar_vwap = vwap.iloc[i] if vwap is not None and i < len(vwap) else None
            bar_adx = adx.iloc[i]
            
            # Найти swing high/low перед этим баром (передаем ПОЛОЖИТЕЛЬНЫЙ индекс!)
            swings = self._find_swing_high_low(df, pos_idx, lookback=20, buffer=3)
            
            if swings['swing_high'] is None and swings['swing_low'] is None:
                continue
            
            # Средний объём
            if i - 20 < -len(df):
                continue
            avg_vol = df['volume'].iloc[i-20:i].mean()
            vol_ratio = bar_volume / avg_vol if avg_vol > 0 else 0
            
            # ADX фильтр: ADX > threshold для валидного breakout
            if bar_adx < self.adx_threshold:
                strategy_logger.debug(f"    ⚠️ Пропуск пробоя на баре {i}: ADX слишком слабый ({bar_adx:.1f} < {self.adx_threshold})")
                continue
            
            # Пробой вверх (через swing high)
            if (swings['swing_high'] is not None and 
                bar_close > swings['swing_high'] and 
                (bar_close - swings['swing_high']) >= self.breakout_atr * bar_atr and
                vol_ratio >= self.volume_threshold):
                strategy_logger.debug(f"    ✅ Пробой LONG найден на баре {i}: ADX={bar_adx:.1f}, volume {vol_ratio:.1f}x")
                return {
                    'direction': 'LONG',
                    'level': swings['swing_high'],
                    'bar_index': i,
                    'atr': bar_atr,
                    'vwap': bar_vwap,
                    'adx': bar_adx
                }
            
            # Пробой вниз (через swing low)
            elif (swings['swing_low'] is not None and 
                  bar_close < swings['swing_low'] and 
                  (swings['swing_low'] - bar_close) >= self.breakout_atr * bar_atr and
                  vol_ratio >= self.volume_threshold):
                strategy_logger.debug(f"    ✅ Пробой SHORT найден на баре {i}: ADX={bar_adx:.1f}, volume {vol_ratio:.1f}x")
                return {
                    'direction': 'SHORT',
                    'level': swings['swing_low'],
                    'bar_index': i,
                    'atr': bar_atr,
                    'vwap': bar_vwap,
                    'adx': bar_adx
                }
        
        return None
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        if len(df) < 50:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется 50")
            return None
        
        # Рассчитать ATR, ADX и VWAP
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        current_atr = atr.iloc[-1]
        
        adx = calculate_adx(df['high'], df['low'], df['close'], period=14)
        current_adx = adx.iloc[-1]
        
        # Получить VWAP из indicators или рассчитать
        vwap = indicators.get('vwap', None)
        
        # Найти недавний пробой с ADX фильтром
        breakout = self._find_recent_breakout(df, atr, vwap, adx)
        if breakout is None:
            strategy_logger.debug(f"    ❌ Нет недавнего пробоя swing level с объемом >{self.volume_threshold}x, расстоянием ≥{self.breakout_atr} ATR и ADX > 20")
            return None
        
        # Логирование найденного пробоя
        strategy_logger.debug(f"    📊 Пробой {breakout['direction']} с ADX={breakout.get('adx', 0):.1f}, уровень {breakout['level']:.4f}")
        
        # Текущие значения
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # Зона ретеста = экстремум ± 0.2-0.3 ATR (используем ATR с момента пробоя!)
        breakout_level = breakout['level']
        breakout_atr = breakout['atr']
        breakout_vwap = breakout.get('vwap')
        
        retest_zone_upper = breakout_level + self.zone_atr[1] * breakout_atr
        retest_zone_lower = breakout_level - self.zone_atr[1] * breakout_atr
        
        # Если есть VWAP, учитываем пересечение (по мануалу)
        if breakout_vwap is not None:
            retest_zone_upper = min(retest_zone_upper, breakout_vwap + 0.1 * breakout_atr)
            retest_zone_lower = max(retest_zone_lower, breakout_vwap - 0.1 * breakout_atr)
        
        # Логирование для debug
        strategy_logger.debug(f"    📊 Пробой найден: {breakout['direction']} на уровне {breakout_level:.4f}, ATR={breakout_atr:.4f}")
        strategy_logger.debug(f"    📊 Зона ретеста: [{retest_zone_lower:.4f}, {retest_zone_upper:.4f}], текущая цена: {current_close:.4f}")
        
        # Проверка касания зоны за последние несколько баров (не только текущий)
        lookback_retest = 5
        touched_zone = False
        reclaimed_level = False
        
        # LONG retest (после пробоя вверх)
        if breakout['direction'] == 'LONG':
            # Проверка: цена касалась зоны ретеста за последние N баров
            for i in range(-lookback_retest, 0):
                if abs(i) >= len(df):
                    continue
                bar_low = df['low'].iloc[i]
                bar_close = df['close'].iloc[i]
                
                # Касание зоны
                if retest_zone_lower <= bar_low <= retest_zone_upper:
                    touched_zone = True
                
                # Рекламирование уровня (close выше уровня пробоя)
                if bar_low <= breakout_level and bar_close > breakout_level:
                    reclaimed_level = True
            
            # Текущий бар также должен быть выше уровня
            if touched_zone and reclaimed_level and current_close > breakout_level:
                    
                    # Фильтр по H4 bias
                    if bias == 'Bearish':
                        strategy_logger.debug(f"    ❌ LONG ретест есть, но H4 bias {bias}")
                        return None
                    
                    entry = current_close
                    
                    # Расчет зон S/R на 15m для точного стопа
                    sr_zones = create_sr_zones(df, current_atr, buffer_mult=0.25)
                    nearest_zone = find_nearest_zone(entry, sr_zones, 'LONG')
                    stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, current_atr, 'LONG', fallback_mult=2.0)
                    
                    # Расчет дистанции и тейков 1R и 2R
                    atr_distance = abs(entry - stop_loss)
                    tp1 = entry + atr_distance * 1.0  # 1R
                    tp2 = entry + atr_distance * 2.0  # 2R
                    
                    signal = Signal(
                        strategy_name=self.name,
                        symbol=symbol,
                        direction='LONG',
                        timestamp=pd.Timestamp.now(),
                        timeframe=self.timeframe,
                        entry_price=float(entry),
                        stop_loss=float(stop_loss),
                        take_profit_1=float(tp1),
                        take_profit_2=float(tp2),
                        regime=regime,
                        bias=bias,
                        base_score=1.0,
                        metadata={
                            'breakout_level': float(breakout_level),
                            'retest_zone_upper': float(retest_zone_upper),
                            'retest_zone_lower': float(retest_zone_lower),
                            'breakout_bar_index': int(breakout['bar_index'])
                        }
                    )
                    return signal
        
        # SHORT retest (после пробоя вниз)
        elif breakout['direction'] == 'SHORT':
            # Проверка: цена касалась зоны ретеста за последние N баров
            for i in range(-lookback_retest, 0):
                if abs(i) >= len(df):
                    continue
                bar_high = df['high'].iloc[i]
                bar_close = df['close'].iloc[i]
                
                # Касание зоны
                if retest_zone_lower <= bar_high <= retest_zone_upper:
                    touched_zone = True
                
                # Рекламирование уровня (close ниже уровня пробоя)
                if bar_high >= breakout_level and bar_close < breakout_level:
                    reclaimed_level = True
            
            # Текущий бар также должен быть ниже уровня
            if touched_zone and reclaimed_level and current_close < breakout_level:
                    
                    if bias == 'Bullish':
                        strategy_logger.debug(f"    ❌ SHORT ретест есть, но H4 bias {bias}")
                        return None
                    
                    entry = current_close
                    
                    # Расчет зон S/R на 15m для точного стопа
                    sr_zones = create_sr_zones(df, current_atr, buffer_mult=0.25)
                    nearest_zone = find_nearest_zone(entry, sr_zones, 'SHORT')
                    stop_loss = calculate_stop_loss_from_zone(entry, nearest_zone, current_atr, 'SHORT', fallback_mult=2.0)
                    
                    # Расчет дистанции и тейков 1R и 2R
                    atr_distance = abs(stop_loss - entry)
                    tp1 = entry - atr_distance * 1.0  # 1R
                    tp2 = entry - atr_distance * 2.0  # 2R
                    
                    signal = Signal(
                        strategy_name=self.name,
                        symbol=symbol,
                        direction='SHORT',
                        timestamp=pd.Timestamp.now(),
                        timeframe=self.timeframe,
                        entry_price=float(entry),
                        stop_loss=float(stop_loss),
                        take_profit_1=float(tp1),
                        take_profit_2=float(tp2),
                        regime=regime,
                        bias=bias,
                        base_score=1.0,
                        metadata={
                            'breakout_level': float(breakout_level),
                            'retest_zone_upper': float(retest_zone_upper),
                            'retest_zone_lower': float(retest_zone_lower),
                            'breakout_bar_index': int(breakout['bar_index'])
                        }
                    )
                    return signal
        
        # Детальное логирование причин отклонения
        if not touched_zone:
            strategy_logger.debug(f"    ❌ Цена НЕ касалась зоны ретеста [{retest_zone_lower:.4f}, {retest_zone_upper:.4f}] за последние {lookback_retest} баров")
        elif not reclaimed_level:
            if breakout['direction'] == 'LONG':
                strategy_logger.debug(f"    ❌ Зона касалась, но НЕТ rejection: нужен close ВЫШЕ {breakout_level:.4f} после касания снизу")
            else:
                strategy_logger.debug(f"    ❌ Зона касалась, но НЕТ rejection: нужен close НИЖЕ {breakout_level:.4f} после касания сверху")
        else:
            strategy_logger.debug(f"    ❌ Текущая цена {current_close:.4f} не {'выше' if breakout['direction'] == 'LONG' else 'ниже'} уровня пробоя {breakout_level:.4f}")
        return None
