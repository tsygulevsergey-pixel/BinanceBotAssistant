from typing import Dict, Optional
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.config import config
from src.utils.strategy_logger import strategy_logger
from src.indicators.technical import calculate_rsi, calculate_stochastic, calculate_atr
from src.utils.reclaim_checker import check_level_reclaim


class RSIStochMRStrategy(BaseStrategy):
    """
    Стратегия #10: RSI/Stochastic Mean Reversion
    
    Логика по мануалу:
    - RANGE-дни; RSI пороги по перцентилям (p15/p85 на 90d)
    - Стохастик крест обратно
    - Зона = край рейнджа ∩ VWAP/VA
    - Триггер/стоп/тейки: как в VWAP MR
    - Подтверждения: CVD-дивергенция, imbalance flip
    """
    
    def __init__(self):
        strategy_config = config.get('strategies.oscillator_mr', {})
        super().__init__("RSI/Stoch MR", strategy_config)
        
        self.rsi_period = strategy_config.get('rsi_period', 14)
        self.stoch_period = strategy_config.get('stoch_period', 14)
        self.oversold_percentile = strategy_config.get('oversold_percentile', 20)  # p15-20
        self.overbought_percentile = strategy_config.get('overbought_percentile', 80)  # p80-85
        self.lookback = strategy_config.get('lookback', 90)  # 90 дней
        self.reclaim_bars = strategy_config.get('reclaim_bars', 2)  # Hold N bars для reclaim
        self.timeframe = '15m'
    
    def get_timeframe(self) -> str:
        return self.timeframe
    
    def get_category(self) -> str:
        return "mean_reversion"
    
    def check_signal(self, symbol: str, df: pd.DataFrame, 
                     regime: str, bias: str, 
                     indicators: Dict) -> Optional[Signal]:
        
        # Работает только в RANGE режиме
        if regime not in ['RANGE', 'CHOP']:
            strategy_logger.debug(f"    ❌ Режим {regime}, требуется RANGE или CHOP")
            return None
        
        lookback_bars = self.lookback * 24 * 4  # 90 дней * 24 часа * 4 (15m bars)
        if len(df) < lookback_bars:
            strategy_logger.debug(f"    ❌ Недостаточно данных: {len(df)} баров, требуется {lookback_bars}")
            return None
        
        # Рассчитать осцилляторы
        rsi = calculate_rsi(df['close'], period=self.rsi_period)
        stoch_k, stoch_d = calculate_stochastic(
            df['high'], df['low'], df['close'], 
            period=self.stoch_period
        )
        atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
        
        # Адаптивные пороги RSI (перцентили за lookback)
        rsi_history = rsi.tail(lookback_bars)
        rsi_oversold = rsi_history.quantile(self.oversold_percentile / 100.0)
        rsi_overbought = rsi_history.quantile(self.overbought_percentile / 100.0)
        
        # Текущие значения
        current_rsi = rsi.iloc[-1]
        current_stoch_k = stoch_k.iloc[-1]
        current_stoch_d = stoch_d.iloc[-1]
        prev_stoch_k = stoch_k.iloc[-2]
        prev_stoch_d = stoch_d.iloc[-2]
        
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_atr = atr.iloc[-1]
        
        # Получаем VWAP/VA для reclaim проверки (зона = край рейнджа ∩ VWAP/VA)
        from src.indicators.vwap import calculate_daily_vwap
        from src.indicators.volume_profile import calculate_volume_profile
        
        vwap, vwap_upper, vwap_lower = calculate_daily_vwap(df)
        vp_result = calculate_volume_profile(df, num_bins=50)
        val = vp_result['val']
        
        current_vwap = vwap.iloc[-1]
        current_vwap_lower = vwap_lower.iloc[-1]
        
        # LONG: RSI в oversold + stoch крест вверх + RECLAIM механизм
        if current_rsi <= rsi_oversold:
            # Стохастик крест: K пересекает D снизу вверх
            if prev_stoch_k <= prev_stoch_d and current_stoch_k > current_stoch_d:
                
                # RECLAIM: проверяем что цена вернулась в зону (выше VAL или VWAP lower) с удержанием
                val_reclaim = check_level_reclaim(
                    df=df,
                    level=val,
                    direction='long',
                    hold_bars=self.reclaim_bars,
                    tolerance_pct=0.15
                )
                
                vwap_reclaim = check_level_reclaim(
                    df=df,
                    level=current_vwap_lower,
                    direction='long',
                    hold_bars=self.reclaim_bars,
                    tolerance_pct=0.15
                )
                
                # Хотя бы одно подтверждение reclaim
                if not (val_reclaim or vwap_reclaim):
                    strategy_logger.debug(f"    ❌ LONG: нет reclaim подтверждения VAL или VWAP lower")
                    return None
                
                entry = current_close
                stop_loss = current_low - 0.25 * current_atr
                
                # TP1 = средний уровень RSI (50), TP2 = overbought
                # Упрощённо: TP в расчёте от entry
                atr_distance = entry - stop_loss
                tp1 = entry + atr_distance * 1.0
                tp2 = entry + atr_distance * 2.0
                
                base_score = 1.0
                confirmations = []
                
                cvd_change = indicators.get('cvd_change')
                depth_imbalance = indicators.get('depth_imbalance')
                cvd_valid = indicators.get('cvd_valid', False)
                depth_valid = indicators.get('depth_valid', False)
                
                if cvd_valid and cvd_change is not None and cvd_change > 0:
                    base_score += 0.5
                    confirmations.append('cvd_flip_up')
                
                if depth_valid and depth_imbalance is not None and depth_imbalance > 0:
                    base_score += 0.5
                    confirmations.append('bid_pressure')
                
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
                    base_score=base_score,
                    metadata={
                        'rsi': float(current_rsi),
                        'rsi_oversold': float(rsi_oversold),
                        'rsi_overbought': float(rsi_overbought),
                        'stoch_k': float(current_stoch_k),
                        'stoch_d': float(current_stoch_d),
                        'cross_type': 'bullish',
                        'reclaim_bars': self.reclaim_bars,
                        'val_reclaim': val_reclaim,
                        'vwap_reclaim': vwap_reclaim,
                        'confirmations': confirmations,
                        'cvd_change': float(cvd_change) if cvd_change is not None else None,
                        'depth_imbalance': float(depth_imbalance) if depth_imbalance is not None else None
                    }
                )
                return signal
        
        # SHORT: RSI в overbought + stoch крест вниз + RECLAIM механизм
        elif current_rsi >= rsi_overbought:
            # Стохастик крест: K пересекает D сверху вниз
            if prev_stoch_k >= prev_stoch_d and current_stoch_k < current_stoch_d:
                
                # Получаем VAH и VWAP upper для SHORT reclaim
                vah = vp_result['vah']
                current_vwap_upper = vwap_upper.iloc[-1]
                
                # RECLAIM: проверяем что цена вернулась в зону (ниже VAH или VWAP upper) с удержанием
                vah_reclaim = check_level_reclaim(
                    df=df,
                    level=vah,
                    direction='short',
                    hold_bars=self.reclaim_bars,
                    tolerance_pct=0.15
                )
                
                vwap_upper_reclaim = check_level_reclaim(
                    df=df,
                    level=current_vwap_upper,
                    direction='short',
                    hold_bars=self.reclaim_bars,
                    tolerance_pct=0.15
                )
                
                # Хотя бы одно подтверждение reclaim
                if not (vah_reclaim or vwap_upper_reclaim):
                    strategy_logger.debug(f"    ❌ SHORT: нет reclaim подтверждения VAH или VWAP upper")
                    return None
                
                entry = current_close
                stop_loss = current_high + 0.25 * current_atr
                
                atr_distance = stop_loss - entry
                tp1 = entry - atr_distance * 1.0
                tp2 = entry - atr_distance * 2.0
                
                base_score = 1.0
                confirmations = []
                
                cvd_change = indicators.get('cvd_change')
                depth_imbalance = indicators.get('depth_imbalance')
                cvd_valid = indicators.get('cvd_valid', False)
                depth_valid = indicators.get('depth_valid', False)
                
                if cvd_valid and cvd_change is not None and cvd_change < 0:
                    base_score += 0.5
                    confirmations.append('cvd_flip_down')
                
                if depth_valid and depth_imbalance is not None and depth_imbalance < 0:
                    base_score += 0.5
                    confirmations.append('ask_pressure')
                
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
                    base_score=base_score,
                    metadata={
                        'rsi': float(current_rsi),
                        'rsi_oversold': float(rsi_oversold),
                        'rsi_overbought': float(rsi_overbought),
                        'stoch_k': float(current_stoch_k),
                        'stoch_d': float(current_stoch_d),
                        'cross_type': 'bearish',
                        'reclaim_bars': self.reclaim_bars,
                        'vah_reclaim': vah_reclaim,
                        'vwap_upper_reclaim': vwap_upper_reclaim,
                        'confirmations': confirmations,
                        'cvd_change': float(cvd_change) if cvd_change is not None else None,
                        'depth_imbalance': float(depth_imbalance) if depth_imbalance is not None else None
                    }
                )
                return signal
        
        strategy_logger.debug(f"    ❌ RSI не в зоне перекупленности/перепроданности или нет stoch кросса")
        return None
