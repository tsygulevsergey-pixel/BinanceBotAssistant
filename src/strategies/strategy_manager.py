from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.logger import logger
from src.utils.strategy_logger import strategy_logger
from src.utils.config import config
# ФАЗА 3: Multi-Factor Confirmation & Regime Weighting
from src.strategies.multi_factor_confirmation import MultiFactorConfirmation
from src.strategies.regime_strategy_weights import RegimeStrategyWeights


class StrategyManager:
    """Менеджер для управления всеми стратегиями"""
    
    def __init__(self, binance_client=None):
        self.strategies: List[BaseStrategy] = []
        self.enabled_strategy_ids = config.get('strategies.enabled', [])
        self.binance_client = binance_client
        
        # ФАЗА 3: Инициализация систем подтверждения
        self.multi_factor = MultiFactorConfirmation(config)
        self.regime_weights = RegimeStrategyWeights(config)
        
    def register_strategy(self, strategy: BaseStrategy):
        """Зарегистрировать стратегию"""
        self.strategies.append(strategy)
        logger.info(f"Registered strategy: {strategy.name}")
    
    def register_all(self, strategies: List[BaseStrategy]):
        """Зарегистрировать все стратегии сразу"""
        for strategy in strategies:
            self.register_strategy(strategy)
    
    async def check_all_signals(self, symbol: str, timeframe_data: Dict[str, pd.DataFrame],
                         regime: str, bias: str, indicators: Dict,
                         blocked_symbols_by_strategy: Optional[dict] = None) -> List[Signal]:
        """
        Проверить все стратегии на сигналы
        
        Args:
            symbol: Торговая пара
            timeframe_data: Словарь {timeframe: DataFrame}
            regime: Рыночный режим
            bias: Направление тренда H4
            indicators: Рассчитанные индикаторы
            blocked_symbols_by_strategy: dict[strategy_name, set(symbols)] - заблокированные символы для каждой стратегии
            
        Returns:
            Список сгенерированных сигналов
        """
        signals = []
        checked_count = 0
        skipped_count = 0
        
        if blocked_symbols_by_strategy is None:
            blocked_symbols_by_strategy = {}
        
        for strategy in self.strategies:
            if not strategy.is_enabled():
                strategy_logger.debug(f"  ⏭️  {strategy.name} - отключена")
                skipped_count += 1
                continue
            
            # Проверить блокировку для ЭТОЙ конкретной стратегии
            if strategy.name in blocked_symbols_by_strategy:
                if symbol in blocked_symbols_by_strategy[strategy.name]:
                    strategy_logger.debug(f"  🔒 {strategy.name} - {symbol} заблокирован (есть активный сигнал)")
                    skipped_count += 1
                    continue
            
            # Получить данные для таймфрейма стратегии
            tf = strategy.get_timeframe()
            df = timeframe_data.get(tf)
            
            if df is None or len(df) < 50:
                strategy_logger.debug(f"  ⏭️  {strategy.name} ({tf}) - недостаточно данных")
                skipped_count += 1
                continue
            
            try:
                strategy_logger.debug(f"  🔍 Проверка: {strategy.name} ({tf})")
                checked_count += 1
                
                signal = strategy.check_signal(symbol, df, regime, bias, indicators)
                if signal:
                    # ФАЗА 3: Multi-Factor Confirmation - проверка подтверждающих факторов
                    df_1h = timeframe_data.get('1h')
                    df_4h = timeframe_data.get('4h')
                    approved, factors = self.multi_factor.check_factors(
                        symbol, signal.direction, df, df_1h, df_4h, indicators, regime
                    )
                    
                    if not approved:
                        strategy_logger.info(
                            f"  ❌ {strategy.name} REJECTED by Multi-Factor: "
                            f"{factors.count()}/{6} factors confirmed (need {self.multi_factor.min_factors})"
                        )
                        continue  # Пропустить сигнал
                    
                    # ФАЗА 3: Regime-Based Strategy Weighting - проверка соответствия режиму
                    if not self.regime_weights.is_suitable(strategy.name, regime):
                        strategy_logger.info(
                            f"  ❌ {strategy.name} BLOCKED by Regime Weight: "
                            f"unsuitable for {regime} regime"
                        )
                        continue  # Пропустить сигнал
                    
                    # Применить weight multiplier к score
                    original_score = signal.base_score
                    signal.base_score = self.regime_weights.apply_weight(
                        strategy.name, regime, signal.base_score
                    )
                    
                    # Добавить factor bonus к score
                    factor_bonus = self.multi_factor.calculate_factor_bonus(factors)
                    signal.base_score += factor_bonus
                    
                    # Логирование улучшений score
                    strategy_logger.info(
                        f"  📊 Score Enhancements: base={original_score:.1f} → "
                        f"regime_weighted={signal.base_score-factor_bonus:.1f} → "
                        f"final={signal.base_score:.1f} (factors: {factors.get_confirmed_list()})"
                    )
                    
                    # ВАЖНО: Сначала рассчитать offset'ы от начальной entry_price
                    signal = strategy.calculate_risk_offsets(signal)
                    
                    # Установить entry_type как MARKET
                    signal.entry_type = "MARKET"
                    
                    # Получить актуальную рыночную цену
                    if self.binance_client:
                        try:
                            mark_data = await self.binance_client.get_mark_price(symbol)
                            current_mark_price = float(mark_data.get('markPrice', signal.entry_price))
                            
                            # Обновить entry_price на актуальную mark price
                            strategy_logger.debug(
                                f"    💹 Updated entry: {signal.entry_price:.4f} → {current_mark_price:.4f} "
                                f"(mark price)"
                            )
                            signal.entry_price = current_mark_price
                            
                            # Пересчитать SL/TP с актуальной ценой используя offset'ы
                            if signal.direction == "LONG":
                                signal.stop_loss = current_mark_price - (signal.stop_offset or 0)
                                signal.take_profit_1 = current_mark_price + (signal.tp1_offset or 0)
                                if signal.tp2_offset:
                                    signal.take_profit_2 = current_mark_price + signal.tp2_offset
                            else:  # SHORT
                                signal.stop_loss = current_mark_price + (signal.stop_offset or 0)
                                signal.take_profit_1 = current_mark_price - (signal.tp1_offset or 0)
                                if signal.tp2_offset:
                                    signal.take_profit_2 = current_mark_price - signal.tp2_offset
                        except Exception as e:
                            strategy_logger.warning(f"    ⚠️  Could not get mark price: {e}, using close price")
                    
                    strategy.increment_signal_count()
                    signals.append(signal)
                    logger.info(
                        f"Signal generated: {signal.strategy_name} | "
                        f"{signal.symbol} {signal.direction} | Score: {signal.base_score} | "
                        f"Entry: MARKET"
                    )
                    strategy_logger.info(
                        f"  ✅ {strategy.name} → СИГНАЛ! {signal.direction} | "
                        f"Entry: {signal.entry_price:.4f} | SL: {signal.stop_loss:.4f} | "
                        f"TP1: {signal.take_profit_1:.4f}"
                    )
                else:
                    strategy_logger.debug(f"  ⚪ {strategy.name} → нет сигнала")
            except Exception as e:
                logger.error(f"Error in strategy {strategy.name}: {e}", exc_info=True)
                strategy_logger.error(f"  ❌ {strategy.name} → ОШИБКА: {e}")
        
        strategy_logger.info(f"📈 Итого: проверено {checked_count}, пропущено {skipped_count}, сигналов {len(signals)}")
        
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
    
    def get_strategies_status(self) -> str:
        """Получить статус всех стратегий в читаемом формате"""
        enabled_strategies = []
        disabled_strategies = []
        
        for strategy in self.strategies:
            if strategy.is_enabled():
                enabled_strategies.append(strategy.name)
            else:
                disabled_strategies.append(strategy.name)
        
        status_lines = []
        status_lines.append(f"📊 Всего стратегий: {len(self.strategies)}")
        status_lines.append(f"✅ Включено: {len(enabled_strategies)}")
        status_lines.append(f"❌ Выключено: {len(disabled_strategies)}")
        
        if enabled_strategies:
            status_lines.append(f"\n🟢 Активные стратегии:")
            for name in enabled_strategies:
                status_lines.append(f"  - {name}")
        
        if disabled_strategies:
            status_lines.append(f"\n🔴 Выключенные стратегии:")
            for name in disabled_strategies:
                status_lines.append(f"  - {name}")
        
        return "\n".join(status_lines)
