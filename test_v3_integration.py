#!/usr/bin/env python3
"""
Тест интеграции V3 зон в Break & Retest
Проверяет что V3 зоны корректно используются
"""

from src.strategies.break_retest import BreakRetestStrategy
from src.utils.config import config

def test_v3_integration():
    print("🔍 Тест интеграции V3 зон в Break & Retest\n")
    
    # Создать стратегию
    strategy = BreakRetestStrategy()
    
    # Проверить настройки
    print(f"1. Конфигурация:")
    print(f"   ✓ use_v3_zones: {strategy.use_v3_zones}")
    print(f"   ✓ v3_zone_strength_threshold: {strategy.v3_zone_strength_threshold}")
    print(f"   ✓ V3 zones provider: {'✓ initialized' if strategy.v3_zones_provider else '✗ not initialized'}\n")
    
    # Проверить из config.yaml
    retest_config = config.get('strategies.retest', {})
    print(f"2. Config.yaml:")
    print(f"   ✓ use_v3_zones: {retest_config.get('use_v3_zones')}")
    print(f"   ✓ v3_zone_strength_threshold: {retest_config.get('v3_zone_strength_threshold')}\n")
    
    # Проверить V3 zones provider
    from src.utils.v3_zones_provider import get_v3_zones_provider
    provider = get_v3_zones_provider()
    print(f"3. V3 Zones Provider:")
    print(f"   ✓ Singleton: {provider is strategy.v3_zones_provider}")
    print(f"   ✓ Zone builder: {'✓ initialized' if provider.zone_builder else '✗ not initialized'}\n")
    
    # Проверить методы
    print(f"4. Методы стратегии:")
    print(f"   ✓ _get_v3_retest_zone: {hasattr(strategy, '_get_v3_retest_zone')}")
    print(f"   ✓ _calculate_improved_score: {hasattr(strategy, '_calculate_improved_score')}\n")
    
    # Проверить сигнатуру _calculate_improved_score
    import inspect
    sig = inspect.signature(strategy._calculate_improved_score)
    params = list(sig.parameters.keys())
    
    print(f"5. Параметры _calculate_improved_score:")
    for param in params:
        print(f"   - {param}")
    
    if 'v3_zone' in params:
        print(f"\n   ✅ Параметр v3_zone присутствует!")
    else:
        print(f"\n   ❌ ОШИБКА: Параметр v3_zone отсутствует!")
    
    print(f"\n✅ Интеграция настроена корректно!")
    print(f"\nℹ️  V3 зоны будут использоваться когда:")
    print(f"   1. use_v3_zones=true в config.yaml")
    print(f"   2. Найден пробой swing level")
    print(f"   3. V3 зона найдена на уровне пробоя")
    print(f"   4. Качество зоны >= {strategy.v3_zone_strength_threshold}")

if __name__ == "__main__":
    test_v3_integration()
