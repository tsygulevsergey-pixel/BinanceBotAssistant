"""
Система скоринга сигналов согласно мануалу.

Скоринг сделки (вход при score ≥ +2):
- +1 объём > 1.5× медианы 20 баров
- +1 CVD в сторону (или дивергенция для MR)
- +1 ΔOI ≥ +1…+3% за 30–90 мин
- +1 устойчивый depth-imbalance 10–30с в сторону
- −1 funding-экстрем (z-score > 2.5)
- −2 BTC идёт против (3-bar lookback, 0.3% threshold)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from src.strategies.base_strategy import Signal
from src.utils.logger import logger


class SignalScorer:
    """Система скоринга сигналов"""
    
    def __init__(self, config: Dict):
        self.volume_threshold = config.get('scoring.volume_mult', 1.5)
        self.doi_min_pct = config.get('scoring.doi_min_pct', 1.0)
        self.doi_max_pct = config.get('scoring.doi_max_pct', 3.0)
        self.enter_threshold = config.get('scoring.enter_threshold', 2.0)
        
        # Depth imbalance пороги
        self.imbalance_long_max = config.get('scoring.depth_imbalance_ratio.long_max', 0.90)
        self.imbalance_short_min = config.get('scoring.depth_imbalance_ratio.short_min', 1.10)
        
        # BTC filter TF
        self.btc_filter_tf = config.get('scoring.btc_filter_tf', '1h')
        
    def score_signal(
        self,
        signal: Signal,
        market_data: Dict,
        indicators: Dict,
        btc_data: Optional[pd.DataFrame] = None
    ) -> float:
        """
        Рассчитать финальный score сигнала
        
        Args:
            signal: Сигнал стратегии
            market_data: Рыночные данные (df, volume, etc.)
            indicators: Индикаторы (CVD, OI, imbalance, etc.)
            btc_data: BTC данные для фильтра
            
        Returns:
            Финальный score (float)
        """
        score = signal.base_score  # Начинаем с базового score от стратегии
        components = []  # Детали компонентов
        
        # +1: Объём > 1.5× медианы 20 баров
        volume_bonus = 0.0
        if signal.volume_ratio and signal.volume_ratio >= self.volume_threshold:
            volume_bonus = 1.0
            score += volume_bonus
            components.append(f"Vol: +1.0 (ratio={signal.volume_ratio:.2f})")
        else:
            vol_ratio = signal.volume_ratio or 0.0
            components.append(f"Vol: 0 (ratio={vol_ratio:.2f} < {self.volume_threshold})")
        
        # +1: CVD в сторону (или дивергенция для MR)
        cvd_score = self._score_cvd(signal, indicators)
        score += cvd_score
        cvd_val = indicators.get('cvd', 0.0)
        if cvd_score > 0:
            components.append(f"CVD: +{cvd_score:.1f} ({'bullish' if cvd_val > 0 else 'bearish'})")
        else:
            components.append(f"CVD: 0 (val={cvd_val:.0f})")
        
        # +1: ΔOI ≥ +1…+3% за 30–90 мин
        doi_score = self._score_doi(signal, indicators)
        score += doi_score
        doi_pct = indicators.get('doi_pct', 0.0)
        if doi_score > 0:
            components.append(f"ΔOI: +{doi_score:.1f} ({doi_pct:.2f}%)")
        else:
            components.append(f"ΔOI: 0 ({doi_pct:.2f}%)")
        
        # +1: Устойчивый depth-imbalance 10–30с в сторону
        imbalance_score = self._score_imbalance(signal, indicators)
        score += imbalance_score
        imbalance_ratio = indicators.get('depth_imbalance', 1.0)
        if imbalance_score > 0:
            components.append(f"Imbalance: +{imbalance_score:.1f} (ratio={imbalance_ratio:.2f})")
        else:
            components.append(f"Imbalance: 0 (ratio={imbalance_ratio:.2f})")
        
        # −1: Funding-экстрем
        funding_penalty = self._score_funding_extreme(signal, indicators)
        score += funding_penalty
        if funding_penalty < 0:
            components.append(f"Funding: {funding_penalty:.1f} (extreme)")
        else:
            components.append("Funding: 0")
        
        # −2: BTC идёт против (на H1)
        btc_penalty, btc_change = self._score_btc_filter(signal, btc_data)
        score += btc_penalty
        if btc_penalty < 0 and btc_change is not None:
            components.append(f"BTC: {btc_penalty:.1f} (BTC {'up' if btc_change > 0 else 'down'} {abs(btc_change):.2f}% vs {signal.direction})")
        else:
            if btc_change is not None:
                components.append(f"BTC: 0 ({'up' if btc_change > 0 else 'down'} {abs(btc_change):.2f}%, neutral)")
            else:
                components.append("BTC: 0 (no data)")
        
        # ДОПОЛНИТЕЛЬНЫЕ ПАРАМЕТРЫ для дифференциации:
        
        # +1: Strong ADX (>30) в TREND режиме
        adx_bonus = self._score_adx(signal, indicators)
        score += adx_bonus
        if adx_bonus > 0:
            adx_val = indicators.get('adx', 0)
            components.append(f"ADX: +{adx_bonus:.1f} (strong trend {adx_val:.1f})")
        
        # +0.5: RSI extreme reversal setup
        rsi_bonus = self._score_rsi_extreme(signal, indicators)
        score += rsi_bonus
        if rsi_bonus > 0:
            rsi_val = indicators.get('rsi', 50)
            components.append(f"RSI: +{rsi_bonus:.1f} (extreme {rsi_val:.1f})")
        
        # +1: Market regime alignment (TREND стратегия в TREND режиме)
        regime_bonus = self._score_regime_alignment(signal, indicators)
        score += regime_bonus
        if regime_bonus > 0:
            regime = indicators.get('regime', 'UNKNOWN')
            components.append(f"Regime: +{regime_bonus:.1f} ({regime} aligned)")
        
        # -0.5: High ATR volatility penalty (риск слишком высокий)
        atr_penalty = self._score_atr_volatility(signal, indicators)
        score += atr_penalty
        if atr_penalty < 0:
            components.append(f"ATR: {atr_penalty:.1f} (extreme volatility)")
        
        # Логируем детальный breakdown
        logger.info(
            f"{signal.symbol} {signal.direction} scoring breakdown:\n"
            f"  Base: {signal.base_score:.1f} | " + " | ".join(components) + f"\n"
            f"  Final Score: {score:.1f}"
        )
        
        return score
    
    def _score_cvd(self, signal: Signal, indicators: Dict) -> float:
        """
        Скоринг CVD (Cumulative Volume Delta)
        +1 если CVD в сторону сигнала (или дивергенция для MR)
        """
        cvd = indicators.get('cvd', None)
        if cvd is None:
            return 0.0
        
        # Для MR стратегий проверяем дивергенцию
        if signal.strategy_name in ['VWAP Mean Reversion', 'Range Fade', 'RSI/Stoch MR']:
            # Упрощённо: проверяем flip CVD
            cvd_direction = 'bullish' if cvd > 0 else 'bearish'
            if signal.direction == 'LONG' and cvd_direction == 'bullish':
                logger.debug(f"{signal.symbol} +1 CVD flip bullish (MR)")
                return 1.0
            elif signal.direction == 'SHORT' and cvd_direction == 'bearish':
                logger.debug(f"{signal.symbol} +1 CVD flip bearish (MR)")
                return 1.0
        else:
            # Для трендовых: CVD в сторону
            if signal.direction == 'LONG' and cvd > 0:
                logger.debug(f"{signal.symbol} +1 CVD bullish")
                return 1.0
            elif signal.direction == 'SHORT' and cvd < 0:
                logger.debug(f"{signal.symbol} +1 CVD bearish")
                return 1.0
        
        return 0.0
    
    def _score_doi(self, signal: Signal, indicators: Dict) -> float:
        """
        Скоринг ΔOI (Delta Open Interest)
        +1 если ΔOI ≥ +1…+3% за 30–90 мин
        """
        doi_pct = indicators.get('doi_pct', None)
        if doi_pct is None:
            return 0.0
        
        # Проверка: ΔOI в нужном диапазоне
        if self.doi_min_pct <= abs(doi_pct) <= self.doi_max_pct:
            # Для LONG нужен положительный ΔOI
            if signal.direction == 'LONG' and doi_pct > 0:
                logger.debug(f"{signal.symbol} +1 ΔOI={doi_pct:.2f}%")
                return 1.0
            # Для SHORT тоже положительный (рост интереса)
            elif signal.direction == 'SHORT' and doi_pct > 0:
                logger.debug(f"{signal.symbol} +1 ΔOI={doi_pct:.2f}%")
                return 1.0
        
        return 0.0
    
    def _score_imbalance(self, signal: Signal, indicators: Dict) -> float:
        """
        Скоринг depth-imbalance
        +1 если устойчивый imbalance 10–30с в сторону
        """
        imbalance_ratio = indicators.get('depth_imbalance', None)
        if imbalance_ratio is None:
            return 0.0
        
        # LONG: imbalance должен быть низким (больше bid ликвидности)
        # Ratio = Ask/Bid, если < 0.90 значит bid преобладает
        if signal.direction == 'LONG' and imbalance_ratio <= self.imbalance_long_max:
            logger.debug(f"{signal.symbol} +1 imbalance bullish (ratio={imbalance_ratio:.2f})")
            return 1.0
        
        # SHORT: imbalance высокий (больше ask ликвидности)
        elif signal.direction == 'SHORT' and imbalance_ratio >= self.imbalance_short_min:
            logger.debug(f"{signal.symbol} +1 imbalance bearish (ratio={imbalance_ratio:.2f})")
            return 1.0
        
        return 0.0
    
    def _score_funding_extreme(self, signal: Signal, indicators: Dict) -> float:
        """
        Пенальти за funding экстрем
        −1 если funding rate z-score > 2.5
        """
        penalty = 0.0
        
        # Funding экстрем (z-score > 2.5)
        funding_extreme = indicators.get('funding_extreme', False)
        if funding_extreme:
            logger.debug(f"{signal.symbol} -1 funding extreme")
            penalty -= 1.0
        
        return penalty
    
    def _score_btc_filter(
        self, 
        signal: Signal, 
        btc_data: Optional[pd.DataFrame]
    ) -> tuple[float, Optional[float]]:
        """
        BTC фильтр: −2 если BTC идёт против (на H1)
        Использует btc_filter.get_direction_penalty() с порогом 0.3%
        
        Returns:
            tuple: (penalty, btc_change_pct) - пенальти и % изменения BTC
        """
        if btc_data is None or len(btc_data) < 3:
            return 0.0, None
        
        # Вычисляем изменение BTC за 3 бара
        btc_change_pct = (btc_data['close'].iloc[-1] - btc_data['close'].iloc[-3]) / btc_data['close'].iloc[-3] * 100
        
        # Используем btc_filter для определения направления с порогом
        from src.filters.btc_filter import BTCFilter
        from src.utils.config import config
        
        btc_filter = BTCFilter(config)
        penalty = btc_filter.get_direction_penalty(signal.direction, btc_data)
        
        if penalty < 0:
            logger.debug(f"{signal.symbol} {penalty:.1f} BTC against (signal {signal.direction})")
        
        return penalty, btc_change_pct
    
    def _score_adx(self, signal: Signal, indicators: Dict) -> float:
        """
        Бонус за сильный тренд (ADX > 30) в TREND режиме
        +1 если ADX > 30 и режим TREND
        """
        adx = indicators.get('adx', 0)
        regime = indicators.get('regime', 'UNKNOWN')
        
        # Бонус только для TREND режима с сильным ADX
        if regime == 'TREND' and adx > 30:
            logger.debug(f"{signal.symbol} +1 strong ADX={adx:.1f} in TREND")
            return 1.0
        
        return 0.0
    
    def _score_rsi_extreme(self, signal: Signal, indicators: Dict) -> float:
        """
        Бонус за RSI extreme reversal setup для mean reversion
        +0.5 если RSI < 30 для LONG или RSI > 70 для SHORT
        """
        rsi = indicators.get('rsi', 50)
        
        # Только для mean reversion стратегий
        if signal.strategy_name in ['VWAP Mean Reversion', 'Range Fade', 'RSI/Stoch MR']:
            if signal.direction == 'LONG' and rsi < 30:
                logger.debug(f"{signal.symbol} +0.5 RSI oversold {rsi:.1f}")
                return 0.5
            elif signal.direction == 'SHORT' and rsi > 70:
                logger.debug(f"{signal.symbol} +0.5 RSI overbought {rsi:.1f}")
                return 0.5
        
        return 0.0
    
    def _score_regime_alignment(self, signal: Signal, indicators: Dict) -> float:
        """
        Бонус за alignment стратегии с market regime
        +1 если breakout стратегия в TREND или MR стратегия в RANGE
        """
        regime = indicators.get('regime', 'UNKNOWN')
        
        # Breakout стратегии любят TREND
        breakout_strategies = ['Liquidity Sweep', 'Break & Retest', 'Order Flow', 'Momentum Breakout']
        if signal.strategy_name in breakout_strategies and regime == 'TREND':
            logger.debug(f"{signal.symbol} +1 breakout strategy in TREND")
            return 1.0
        
        # MR стратегии любят RANGE/SQUEEZE
        mr_strategies = ['VWAP Mean Reversion', 'Range Fade', 'RSI/Stoch MR', 'Volume Profile']
        if signal.strategy_name in mr_strategies and regime in ['RANGE', 'SQUEEZE']:
            logger.debug(f"{signal.symbol} +1 MR strategy in {regime}")
            return 1.0
        
        return 0.0
    
    def _score_atr_volatility(self, signal: Signal, indicators: Dict) -> float:
        """
        Пенальти за экстремальную волатильность
        -0.5 если ATR > 2x средней (высокий риск)
        """
        atr = indicators.get('atr', 0)
        atr_avg = indicators.get('atr_avg', atr)  # Средняя ATR за период
        
        # Если ATR более чем в 2 раза выше средней - пенальти
        if atr_avg > 0 and atr > atr_avg * 2.0:
            logger.debug(f"{signal.symbol} -0.5 extreme ATR={atr:.4f} (avg={atr_avg:.4f})")
            return -0.5
        
        return 0.0
    
    def should_enter(self, score: float) -> bool:
        """Проверить, достаточен ли score для входа"""
        return score >= self.enter_threshold
