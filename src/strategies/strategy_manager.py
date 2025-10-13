from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime
from src.strategies.base_strategy import BaseStrategy, Signal
from src.utils.logger import logger
from src.utils.strategy_logger import strategy_logger
from src.utils.config import config


class StrategyManager:
    """Менеджер для управления всеми стратегиями"""
    
    def __init__(self, binance_client=None):
        self.strategies: List[BaseStrategy] = []
        self.enabled_strategy_ids = config.get('strategies.enabled', [])
        self.binance_client = binance_client
        
    def register_strategy(self, strategy: BaseStrategy):
        """Зарегистрировать стратегию"""
        self.strategies.append(strategy)
        logger.info(f"Registered strategy: {strategy.name}")
    
    def register_all(self, strategies: List[BaseStrategy]):
        """Зарегистрировать все стратегии сразу"""
        for strategy in strategies:
            self.register_strategy(strategy)
    
    async def check_all_signals(self, symbol: str, timeframe_data: Dict[str, pd.DataFrame],
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
        checked_count = 0
        skipped_count = 0
        
        for strategy in self.strategies:
            if not strategy.is_enabled():
                strategy_logger.debug(f"  ⏭️  {strategy.name} - отключена")
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
                    # ВАЖНО: Сначала рассчитать offset'ы от начальной entry_price
                    signal = strategy.calculate_risk_offsets(signal)
                    
                    # Применить гибридную логику входа на основе категории стратегии
                    entry_type, target_price, timeout = strategy.determine_entry_type(
                        signal.entry_price, df, signal.direction
                    )
                    signal.entry_type = entry_type
                    signal.entry_timeout = timeout
                    
                    # Для MARKET ордеров: получить актуальную рыночную цену
                    if entry_type == "MARKET" and self.binance_client:
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
                    
                    # Для LIMIT orders: сохранить целевую цену и пересчитать SL/TP
                    if entry_type == "LIMIT":
                        signal.target_entry_price = target_price  # Целевая цена с offset
                        current_price = float(df['close'].iloc[-1])
                        
                        # Пересчитать SL/TP от target_entry_price используя offset'ы
                        # Это сохраняет R:R при изменении entry
                        if signal.direction == "LONG":
                            signal.stop_loss = signal.target_entry_price - (signal.stop_offset or 0)
                            signal.take_profit_1 = signal.target_entry_price + (signal.tp1_offset or 0)
                            if signal.tp2_offset:
                                signal.take_profit_2 = signal.target_entry_price + signal.tp2_offset
                        else:  # SHORT
                            signal.stop_loss = signal.target_entry_price + (signal.stop_offset or 0)
                            signal.take_profit_1 = signal.target_entry_price - (signal.tp1_offset or 0)
                            if signal.tp2_offset:
                                signal.take_profit_2 = signal.target_entry_price - signal.tp2_offset
                        
                        signal.entry_price = current_price  # Текущая цена для отображения
                        
                        strategy_logger.info(
                            f"  📍 LIMIT entry: target={signal.target_entry_price:.4f}, "
                            f"current={signal.entry_price:.4f}, SL={signal.stop_loss:.4f}, "
                            f"TP1={signal.take_profit_1:.4f}, timeout={timeout} bars"
                        )
                    
                    strategy.increment_signal_count()
                    signals.append(signal)
                    logger.info(
                        f"Signal generated: {signal.strategy_name} | "
                        f"{signal.symbol} {signal.direction} | Score: {signal.base_score} | "
                        f"Entry: {entry_type}"
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
