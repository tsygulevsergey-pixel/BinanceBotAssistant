"""
Regime-Based Strategy Weighting - ФАЗА 3
Оптимальный выбор стратегий для каждого режима рынка

Логика:
- TREND: Break & Retest (breakout), MA/VWAP Pullback работают лучше
- RANGE: Volume Profile (rejection), Liquidity Sweep (fade) работают лучше
- SQUEEZE: Order Flow (накопление перед breakout) работает лучше

Каждая стратегия получает weight multiplier в зависимости от режима
"""

from typing import Dict, Any
from src.utils.logger import logger


class RegimeStrategyWeights:
    """
    Управление весами стратегий в зависимости от режима рынка
    
    Применяет multiplier к score стратегии в зависимости от соответствия режиму
    """
    
    def __init__(self, config: Any):
        # Веса по умолчанию (если не указано в config)
        default_weights = {
            'TREND': {
                'Break & Retest': 1.5,      # Breakout стратегия - отлично для TREND
                'MA/VWAP Pullback': 1.3,    # Pullback в тренде - хорошо
                'Volume Profile': 0.8,      # Rejection менее надёжен в TREND
                'Liquidity Sweep': 0.9,     # Fade против тренда - рискованно
                'Order Flow': 1.0,          # Нейтрально
            },
            'RANGE': {
                'Break & Retest': 0.8,      # Breakout часто ложный в RANGE
                'MA/VWAP Pullback': 0.9,    # Pullback работает хуже в RANGE
                'Volume Profile': 1.5,      # Rejection от границ - отлично
                'Liquidity Sweep': 1.3,     # Fade sweep - хорошо для RANGE
                'Order Flow': 1.0,          # Нейтрально
            },
            'SQUEEZE': {
                'Break & Retest': 1.2,      # Готовность к breakout
                'MA/VWAP Pullback': 0.9,    # Менее эффективно в сжатии
                'Volume Profile': 1.0,      # Нейтрально
                'Liquidity Sweep': 1.0,     # Нейтрально
                'Order Flow': 1.5,          # Smart money накопление - отлично
            }
        }
        
        # Загружаем веса из config (если есть), иначе используем default
        self.weights = config.get('regime_weights', default_weights)
        
        # Минимальный вес для блокировки стратегии
        self.min_weight_threshold = config.get('regime_weights.min_threshold', 0.5)
        
        logger.info(
            f"📊 Regime Strategy Weights initialized: "
            f"min_threshold={self.min_weight_threshold}"
        )
        
        # Логирование весов для каждого режима
        for regime, strategy_weights in self.weights.items():
            logger.info(f"  {regime}: {strategy_weights}")
    
    def get_weight(self, strategy_name: str, regime: str) -> float:
        """
        Получить weight multiplier для стратегии в текущем режиме
        
        Args:
            strategy_name: Название стратегии
            regime: Текущий режим рынка (TREND/RANGE/SQUEEZE)
        
        Returns:
            Weight multiplier (обычно 0.5-1.5)
        """
        regime_weights = self.weights.get(regime, {})
        weight = regime_weights.get(strategy_name, 1.0)  # Default 1.0 если не указано
        
        return weight
    
    def is_suitable(self, strategy_name: str, regime: str) -> bool:
        """
        Проверить подходит ли стратегия для текущего режима
        
        Args:
            strategy_name: Название стратегии
            regime: Текущий режим рынка
        
        Returns:
            True если вес >= min_weight_threshold
        """
        weight = self.get_weight(strategy_name, regime)
        suitable = weight >= self.min_weight_threshold
        
        if not suitable:
            logger.debug(
                f"    ⚠️ Strategy '{strategy_name}' BLOCKED in {regime} "
                f"(weight {weight} < {self.min_weight_threshold})"
            )
        
        return suitable
    
    def apply_weight(self, strategy_name: str, regime: str, base_score: float) -> float:
        """
        Применить weight multiplier к базовому score
        
        Args:
            strategy_name: Название стратегии
            regime: Текущий режим рынка
            base_score: Базовый score стратегии
        
        Returns:
            Adjusted score с учётом веса
        """
        weight = self.get_weight(strategy_name, regime)
        adjusted_score = base_score * weight
        
        logger.debug(
            f"    📊 Regime Weight: {strategy_name} in {regime}: "
            f"{base_score:.1f} × {weight} = {adjusted_score:.1f}"
        )
        
        return adjusted_score
    
    def get_best_strategies(self, regime: str, top_n: int = 3) -> list[tuple[str, float]]:
        """
        Получить топ-N лучших стратегий для режима
        
        Args:
            regime: Режим рынка
            top_n: Количество топ стратегий
        
        Returns:
            Список (strategy_name, weight) отсортированный по убыванию веса
        """
        regime_weights = self.weights.get(regime, {})
        
        # Сортируем по весу (убывание)
        sorted_strategies = sorted(
            regime_weights.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return sorted_strategies[:top_n]
    
    def get_regime_recommendation(self, regime: str) -> str:
        """
        Получить рекомендацию по лучшим стратегиям для режима
        
        Args:
            regime: Режим рынка
        
        Returns:
            Строка с рекомендацией
        """
        best = self.get_best_strategies(regime, top_n=3)
        
        if not best:
            return f"No strategy weights configured for {regime}"
        
        recommendation = f"Best strategies for {regime}: "
        strategy_list = [f"{name} ({weight}x)" for name, weight in best]
        recommendation += ", ".join(strategy_list)
        
        return recommendation
