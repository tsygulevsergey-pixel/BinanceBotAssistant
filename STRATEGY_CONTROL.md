# 🎛️ УПРАВЛЕНИЕ СТРАТЕГИЯМИ

## ✅ Включение/Выключение стратегий через config.yaml

Теперь вы можете **легко включать и выключать** любую стратегию без изменения кода!

### 📝 Как это работает:

1. Откройте `config.yaml`
2. Найдите нужную стратегию в секции `strategies:`
3. Измените `enabled: true` на `enabled: false` (или наоборот)
4. Перезапустите бота

### 💡 Пример:

```yaml
strategies:
  # Выключить CVD Divergence (слишком много сигналов)
  cvd_divergence:
    enabled: false  # ← ВЫКЛЮЧЕНО
    lookback_bars: 20
    divergence_threshold: 0.3
  
  # Выключить Break & Retest (слишком много сигналов)
  retest:
    enabled: false  # ← ВЫКЛЮЧЕНО
    breakout_atr: 0.25
    zone_atr: [0.2, 0.3]
  
  # Оставить Donchian Breakout включенной
  donchian:
    enabled: true  # ← ВКЛЮЧЕНО
    period: 20
    timeframe: "1h"
```

---

## 📊 Доступные стратегии:

| # | Название | Config Key | По умолчанию |
|---|----------|-----------|--------------|
| 1 | Donchian Breakout | `donchian` | ✅ enabled |
| 2 | Squeeze Breakout | `squeeze` | ✅ enabled |
| 3 | ORB/IRB | `orb` | ✅ enabled |
| 4 | MA/VWAP Pullback | `pullback` | ✅ enabled |
| 5 | Break & Retest | `retest` | ✅ enabled |
| 6 | ATR Momentum | `momentum` | ✅ enabled |
| 7 | VWAP Mean Reversion | `vwap_mr` | ✅ enabled |
| 8 | Range Fade | `range_fade` | ✅ enabled |
| 9 | Volume Profile | `volume_profile` | ✅ enabled |
| 10 | RSI/Stochastic MR | `oscillator_mr` | ✅ enabled |
| 11 | Liquidity Sweep | `liquidity_sweep` | ✅ enabled |
| 12 | Order Flow | `order_flow` | ✅ enabled |
| 13 | CVD Divergence | `cvd_divergence` | ✅ enabled |
| 14 | Time of Day | `time_of_day` | ✅ enabled |
| 15 | Funding Arbitrage | `funding` | ❌ disabled |

---

## 🎯 Сценарии использования:

### Сценарий 1: Отключить доминирующие стратегии

**Проблема:** CVD Divergence (81 сигнал) и Break & Retest (78 сигналов) дают 92% сигналов

**Решение:**
```yaml
strategies:
  cvd_divergence:
    enabled: false  # Временно отключить
  
  retest:
    enabled: false  # Временно отключить
```

**Результат:** Другие 12 стратегий получат шанс работать!

---

### Сценарий 2: Тестирование одной стратегии

**Цель:** Проверить производительность только Donchian Breakout

**Решение:** Выключить ВСЕ кроме одной:
```yaml
strategies:
  donchian:
    enabled: true  # ← Только эта включена
  
  squeeze:
    enabled: false
  
  orb:
    enabled: false
  
  # ... и так далее для всех остальных
```

**Результат:** Чистая статистика по одной стратегии!

---

### Сценарий 3: Постепенное включение после балансировки

**План:** Внедрять улучшенные стратегии поэтапно

**Фаза 1** (неделя 1):
```yaml
strategies:
  donchian:
    enabled: true  # Новые параметры
  squeeze:
    enabled: true  # Новые параметры
  
  # Остальные выключены
  retest:
    enabled: false
  cvd_divergence:
    enabled: false
```

**Фаза 2** (неделя 2):
```yaml
  retest:
    enabled: true  # Включить улучшенную версию
```

**Результат:** Контролируемое внедрение изменений!

---

## 📈 Просмотр статуса стратегий

При запуске бота в логах будет:

```
📊 Всего стратегий: 14
✅ Включено: 10
❌ Выключено: 4

🟢 Активные стратегии:
  - Donchian Breakout
  - Squeeze Breakout
  - ORB/IRB
  - MA/VWAP Pullback
  - ATR Momentum
  - VWAP Mean Reversion
  - Range Fade
  - Volume Profile
  - RSI/Stochastic MR
  - Time of Day

🔴 Выключенные стратегии:
  - Break & Retest
  - Liquidity Sweep
  - Order Flow
  - CVD Divergence
```

---

## ⚠️ Важные замечания:

1. **Бот не сломается** если все стратегии выключены - просто не будет сигналов
2. **Изменения применяются** только после перезапуска бота
3. **Action Price система** работает отдельно (свой флаг `action_price.enabled`)
4. **По умолчанию все включены** - если флаг `enabled` отсутствует, стратегия работает

---

## 🔧 Быстрые команды:

### Отключить проблемные стратегии (CVD + Break & Retest):
```bash
# В config.yaml найти и заменить:
cvd_divergence:
  enabled: false

retest:
  enabled: false
```

### Включить только breakout стратегии:
```bash
# Включить: donchian, squeeze, orb, momentum
# Выключить: все остальные
```

### Включить только mean reversion стратегии:
```bash
# Включить: vwap_mr, range_fade, volume_profile, oscillator_mr
# Выключить: все остальные
```

---

## 📞 Поддержка:

Если что-то не работает:
1. Проверьте синтаксис YAML (отступы = пробелы, не табы)
2. Убедитесь что `enabled:` на одном уровне с другими параметрами стратегии
3. Перезапустите бота после изменений
4. Проверьте логи на наличие ошибок при старте

---

**Дата создания:** 13 октября 2025  
**Версия:** 1.0
