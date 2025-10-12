# Action Price V2 Unit Tests

## Описание

Набор unit-тестов для проверки компонентов Action Price V2:
- `test_patterns_v2.py` - паттерны (pin-bar, engulfing, fakey, inside-bar, ppr)
- `test_zones_v2.py` - зоны S/R (касания, recency, penalty, strength)
- `test_risk_rr_v2.py` - проверка R:R (V2: до boundary зоны, min_rr=1.2)
- `test_scoring_v2.py` - scoring V2 (нормализация 0-10, threshold 6.5)

## Статус

### ✅ Работают (11/35 тестов)
- **test_scoring_v2.py** - все 11 тестов PASS
  - Компоненты scoring
  - Capping правила
  - Threshold проверки

### ⚠️ Требуют адаптации (24/35 тестов)
- **test_patterns_v2.py** - сигнатуры методов не совпадают
- **test_zones_v2.py** - методы _v2 не существуют
- **test_risk_rr_v2.py** - методы check_rr_v2 не существуют

## Запуск тестов

```bash
# Все тесты
python -m pytest tests/action_price/ -v

# Только работающие (scoring)
python -m pytest tests/action_price/test_scoring_v2.py -v

# Конкретный тест
python -m pytest tests/action_price/test_scoring_v2.py::TestScoringV2::test_score_component_weights -v
```

## TODO

1. **Адаптировать тесты паттернов** к реальным сигнатурам методов:
   - `detect_pin_bar(df)` - без direction параметра
   - `detect_engulfing(df)` - без direction параметра
   - Проверить parent_config передачу

2. **Адаптировать тесты зон** к существующим методам:
   - Найти актуальные методы для touch detection
   - Использовать существующие методы recency
   - Проверить penalty calculation

3. **Адаптировать тесты R:R** к существующим методам:
   - Найти актуальный метод расчёта R:R
   - Проверить V2 логику (до boundary vs center)

## Принципы тестирования V2

1. **Backward Compatibility**: V1 должен работать без изменений
2. **Version Gating**: V2 фичи активируются через `parent_config={'version': 'v2'}`
3. **Isolation**: Каждый тест независим, использует собственные данные
4. **Coverage**: Проверяем базовые кейсы, граничные условия, edge cases

## Примечания

- Тесты используют синтетические данные (pandas DataFrames)
- Scoring тесты - математические, не требуют реальных компонентов
- Для полной интеграции нужно адаптировать API тестов к реальным методам
