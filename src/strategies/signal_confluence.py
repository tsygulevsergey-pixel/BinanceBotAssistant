"""
Signal Confluence System
Когда 2+ стратегий согласны на одном symbol+direction → объединить в усиленный сигнал
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
import json
from src.utils.logger import logger


@dataclass
class Signal:
    """Упрощенный Signal dataclass для confluence"""
    symbol: str
    direction: str
    strategy_name: str
    strategy_id: int
    entry_price: float
    stop_loss: float
    take_profit_1: Optional[float]
    take_profit_2: Optional[float]
    score: float
    timeframe: str
    market_regime: str
    context: Dict


class SignalConfluenceManager:
    """
    Управление confluence сигналов
    
    Логика:
    1. Группировать сигналы по (symbol, direction)
    2. Если 2+ стратегий согласны → объединить
    3. Использовать лучшие уровни SL/TP
    4. Добавить бонус к score
    """
    
    def __init__(self, config: Dict):
        # Бонусы за confluence
        self.double_bonus = config.get('confluence.double_bonus', 1.5)  # +1.5 к score
        self.triple_bonus = config.get('confluence.triple_bonus', 3.0)  # +3.0 к score
        self.quad_bonus = config.get('confluence.quad_bonus', 5.0)     # +5.0 к score
        
        # Минимальный gap между entry ценами для confluence (%)
        self.max_entry_gap_pct = config.get('confluence.max_entry_gap_pct', 0.3)  # 0.3%
        
        logger.info(
            f"Confluence Manager initialized: "
            f"double={self.double_bonus}, triple={self.triple_bonus}, "
            f"max_entry_gap={self.max_entry_gap_pct}%"
        )
    
    def find_confluence(self, signals: List[Signal]) -> List[Signal]:
        """
        Найти и объединить confluence сигналы
        
        Args:
            signals: Список сигналов от разных стратегий
            
        Returns:
            Список сигналов с объединенными confluence
        """
        if len(signals) <= 1:
            return signals
        
        # Группировка по (symbol, direction)
        groups: Dict[tuple, List[Signal]] = {}
        for signal in signals:
            key = (signal.symbol, signal.direction)
            if key not in groups:
                groups[key] = []
            groups[key].append(signal)
        
        # Обработка групп
        result = []
        for key, group in groups.items():
            if len(group) == 1:
                # Одиночный сигнал - без confluence
                result.append(group[0])
            else:
                # Confluence обнаружен!
                confluenced_signal = self._merge_signals(group)
                if confluenced_signal:
                    result.append(confluenced_signal)
                else:
                    # Если merge не удался (слишком большой gap) - берем лучший по score
                    best = max(group, key=lambda s: s.score)
                    result.append(best)
        
        return result
    
    def _merge_signals(self, signals: List[Signal]) -> Optional[Signal]:
        """
        Объединить confluence сигналы в один
        
        Логика:
        1. Проверить что entry цены близко (< max_entry_gap_pct)
        2. Использовать лучший SL (ближайший к entry для защиты)
        3. Использовать лучший TP (самый дальний для profit)
        4. Добавить бонус к score
        5. Сохранить список стратегий в confluence_strategies
        """
        if len(signals) < 2:
            return None
        
        symbol = signals[0].symbol
        direction = signals[0].direction
        
        # 1. Проверить gap между entry ценами
        entry_prices = [s.entry_price for s in signals]
        avg_entry = sum(entry_prices) / len(entry_prices)
        max_gap = max(abs(e - avg_entry) / avg_entry * 100 for e in entry_prices)
        
        if max_gap > self.max_entry_gap_pct:
            logger.debug(
                f"Confluence rejected for {symbol} {direction}: "
                f"entry gap {max_gap:.2f}% > {self.max_entry_gap_pct}%"
            )
            return None
        
        # 2. Выбрать базовый сигнал (с лучшим score)
        base_signal = max(signals, key=lambda s: s.score)
        
        # 3. Вычислить confluence бонус
        confluence_count = len(signals)
        if confluence_count == 2:
            bonus = self.double_bonus
        elif confluence_count == 3:
            bonus = self.triple_bonus
        else:
            bonus = self.quad_bonus
        
        # 4. Выбрать лучшие уровни
        if direction == "LONG":
            # Для LONG: лучший SL = самый высокий (ближе к entry)
            # Лучший TP = самый высокий (больше profit)
            best_sl = max(s.stop_loss for s in signals)
            best_tp1 = max((s.take_profit_1 for s in signals if s.take_profit_1), default=None)
            best_tp2 = max((s.take_profit_2 for s in signals if s.take_profit_2), default=None)
        else:  # SHORT
            # Для SHORT: лучший SL = самый низкий (ближе к entry)
            # Лучший TP = самый низкий (больше profit)
            best_sl = min(s.stop_loss for s in signals)
            best_tp1 = min((s.take_profit_1 for s in signals if s.take_profit_1), default=None)
            best_tp2 = min((s.take_profit_2 for s in signals if s.take_profit_2), default=None)
        
        # 5. Создать объединенный сигнал
        strategy_names = [s.strategy_name for s in signals]
        confluenced_signal = Signal(
            symbol=symbol,
            direction=direction,
            strategy_name=base_signal.strategy_name,  # Главная стратегия
            strategy_id=base_signal.strategy_id,
            entry_price=avg_entry,  # Средняя entry
            stop_loss=best_sl,
            take_profit_1=best_tp1,
            take_profit_2=best_tp2,
            score=base_signal.score + bonus,  # Базовый score + бонус
            timeframe=base_signal.timeframe,
            market_regime=base_signal.market_regime,
            context={
                **base_signal.context,
                'confluence_count': confluence_count,
                'confluence_strategies': json.dumps(strategy_names),
                'confluence_bonus': bonus,
                'original_scores': [s.score for s in signals],
                'entry_gap_pct': max_gap
            }
        )
        
        logger.info(
            f"✨ CONFLUENCE: {symbol} {direction} | "
            f"{confluence_count} strategies agree: {', '.join(strategy_names)} | "
            f"Score: {base_signal.score:.1f} → {confluenced_signal.score:.1f} (+{bonus})"
        )
        
        return confluenced_signal
    
    def get_confluence_stats(self, signals: List[Signal]) -> Dict:
        """Статистика по confluence"""
        total = len(signals)
        single = sum(1 for s in signals if s.context.get('confluence_count', 1) == 1)
        double = sum(1 for s in signals if s.context.get('confluence_count', 1) == 2)
        triple = sum(1 for s in signals if s.context.get('confluence_count', 1) == 3)
        quad_plus = sum(1 for s in signals if s.context.get('confluence_count', 1) >= 4)
        
        return {
            'total_signals': total,
            'single_strategy': single,
            'double_confluence': double,
            'triple_confluence': triple,
            'quad_plus_confluence': quad_plus,
            'confluence_rate': ((total - single) / total * 100) if total > 0 else 0
        }
