# 📊 ПОЛНЫЙ ОБЗОР СТРАТЕГИЙ ТОРГОВОГО БОТА

**Дата:** 13 октября 2025  
**Всего стратегий:** 14  
**Категории:** Breakout (6), Pullback (2), Mean Reversion (6)

---

## 📈 СТАТИСТИКА ПРОИЗВОДИТЕЛЬНОСТИ (158 закрытых сигналов)

| Метрика | Значение |
|---------|----------|
| **Win Rate (TP1+TP2)** | 15.2% |
| **TP2 (полный успех)** | 19 сигналов (12.0%) - средний PnL: +6.44% |
| **TP1 (частичный успех)** | 5 сигналов (3.2%) |
| **TIME_STOP** | 94 сигнала (59.5%) - средний PnL: -0.05% |
| **STOP_LOSS** | 40 сигналов (25.3%) - средний PnL: -3.30% |
| **Средний PnL** | -0.09% (почти breakeven) |

### Дисбаланс стратегий:
- **CVD Divergence:** 81 сигнал (47%)
- **Break & Retest:** 78 сигналов (45%)
- **Остальные 12 стратегий:** 13 сигналов (8%)

---

## 1️⃣ DONCHIAN BREAKOUT

**Категория:** Breakout  
**Timeframe:** 1h  
**Base Score:** 1.0  

### Что анализирует:
- Donchian Channel (пробой верхней/нижней границы)
- Bollinger Bands width (проверка предварительного сжатия)
- Объем (подтверждение пробоя)
- H4 bias (контекст)

### Параметры:
```yaml
period: 20                      # Период Donchian канала
min_close_distance_atr: 0.25    # Минимальное расстояние от границы
volume_threshold: 1.5           # Объем >= 1.5x среднего
bbw_percentile: [30, 40]        # BB width должен быть в p30-40 до пробоя
lookback_days: 14               # Для расчета перцентилей
```

### Условия сигнала LONG:
1. ✅ **Режим = TREND** (обязательно)
2. ✅ **BB width был низким** (p30-40) до пробоя - признак сжатия
3. ✅ **close > upper_band** + 0.25 ATR - четкий пробой
4. ✅ **volume >= 1.5x** rolling average (20) - объем подтверждает
5. ✅ **H4 bias != Bearish** - контекст не против

### Условия сигнала SHORT:
1. ✅ **Режим = TREND** (обязательно)
2. ✅ **BB width был низким** (p30-40) до пробоя - признак сжатия
3. ✅ **close < lower_band** - 0.25 ATR - четкий пробой вниз
4. ✅ **volume >= 1.5x** rolling average (20) - объем подтверждает
5. ✅ **H4 bias != Bullish** - контекст не против

### Используемые индикаторы:
- Donchian Channel (20 период)
- ATR (14)
- Bollinger Bands (20, std=2.0)
- Volume (rolling 20)
- Adaptive volume threshold (по времени суток)

### Риск-менеджмент:
- **Stop-Loss:** Через S/R зоны, fallback = 2.0 ATR
- **TP1:** entry + 1R (1x risk)
- **TP2:** entry + 2R (2x risk)

---

## 2️⃣ SQUEEZE BREAKOUT

**Категория:** Breakout  
**Timeframe:** 1h  
**Base Score:** 1.0  

### Что анализирует:
- TTM Squeeze индикатор (BB width < KC width)
- Длительность сжатия (минимум 12 баров)
- Пробой EMA20

### Параметры:
```yaml
lookback: 90                  # Окно для BB percentile
bb_percentile: 25             # BB width должен быть < p25
min_duration: 12              # Минимум 12 баров сжатия
breakout_atr: 0.25            # Пробой >= 0.25 ATR от EMA20
max_distance_ema20: 1.5       # Максимальное расстояние от EMA20
```

### Условия сигнала LONG:
1. ✅ **Режим = SQUEEZE** (обязательно)
2. ✅ **BB width < KC width** минимум 12 баров подряд
3. ✅ **close > EMA20 + 0.25 ATR** - пробой вверх
4. ✅ **distance_from_ema20 <= 1.5 ATR** - не слишком далеко
5. ✅ **ADX >= 20** - достаточный импульс для breakout
6. ✅ **H4 bias != Bearish**

### Условия сигнала SHORT:
1. ✅ **Режим = SQUEEZE** (обязательно)
2. ✅ **BB width < KC width** минимум 12 баров подряд
3. ✅ **close < EMA20 - 0.25 ATR** - пробой вниз
4. ✅ **distance_from_ema20 <= 1.5 ATR** - не слишком далеко
5. ✅ **ADX >= 20** - достаточный импульс для breakout
6. ✅ **H4 bias != Bullish**

### Используемые индикаторы:
- Bollinger Bands (20, std=2.0)
- Keltner Channels (20, atr_mult=1.5)
- EMA (20)
- ADX (14)
- ATR (14)

### Риск-менеджмент:
- **Stop-Loss:** Через S/R зоны, max 5.0 ATR
- **TP1:** entry + 1R
- **TP2:** entry + 2R

---

## 3️⃣ ORB/IRB (Opening/Initial Range Breakout)

**Категория:** Breakout  
**Timeframe:** 15m  
**Base Score:** 1.0  

### Что анализирует:
- Initial Balance (первый час торгов)
- Временные слоты сессий
- H4 тренд для подтверждения

### Параметры:
```yaml
# Торговые слоты (UTC):
slots:
  - [00:00, 01:00]    # Asia open
  - [07:00, 08:00]    # EU open  
  - [13:30, 14:30]    # US open

ib_duration_minutes: 60
width_percentile: 30          # IB width должен быть < p30
lookback_days: 60             # Для расчета перцентилей
atr_multiplier: 1.3           # IB width < 1.3 ATR
breakout_atr: 0.25            # Пробой >= 0.25 ATR
volume_threshold: 1.5
```

### Условия сигнала LONG:
1. ✅ **Текущее время в одном из слотов** (UTC)
2. ✅ **IB_width < 1.3 ATR** - узкий диапазон
3. ✅ **IB_width < p30** за 60 дней - сжатие волатильности
4. ✅ **H4 ADX > 20** - тренд на старшем ТФ
5. ✅ **close > IB_high + 0.25 ATR** - четкий пробой
6. ✅ **volume >= 1.5x** average

### Условия сигнала SHORT:
1. ✅ **Текущее время в одном из слотов** (UTC)
2. ✅ **IB_width < 1.3 ATR** - узкий диапазон
3. ✅ **IB_width < p30** за 60 дней - сжатие волатильности
4. ✅ **H4 ADX > 20** - тренд на старшем ТФ
5. ✅ **close < IB_low - 0.25 ATR** - четкий пробой вниз
6. ✅ **volume >= 1.5x** average

### Используемые индикаторы:
- Initial Balance calculation (4 bars на 15m)
- ATR (14)
- EMA (20, 50)
- H4 ADX (из indicators)
- BTC directional filter
- Volume (rolling 20)

### Риск-менеджмент:
- **Stop-Loss:** Через S/R зоны
- **TP1:** entry + 1R
- **TP2:** entry + 2R

---

## 4️⃣ MA/VWAP PULLBACK

**Категория:** Pullback  
**Timeframe:** 4h  
**Base Score:** 1.0  

### Что анализирует:
- EMA50 тренд (направление и наклон)
- Fibonacci retracement зоны
- VWAP как динамический уровень

### Параметры:
```yaml
ma_periods: [20, 50]
fib_levels: [0.382, 0.618]    # Глубина отката
retest_atr: 0.3               # Зона EMA20 ± 0.3 ATR
volume_threshold: 1.2         # Объем >= 1.2x
```

### Условия сигнала LONG:
1. ✅ **Режим = TREND**
2. ✅ **EMA50 slope > 0** - восходящий тренд
3. ✅ **ADX > 20** - тренд подтвержден
4. ✅ **Цена в зоне 0.382-0.618 Fibonacci** - правильная глубина отката
5. ✅ **Цена около EMA20 ± 0.3 ATR** ИЛИ **около VWAP ± 0.3 ATR**
6. ✅ **close > EMA20** - закрытие над уровнем
7. ✅ **volume >= 1.2x** (адаптивный порог)
8. ✅ **H4 bias != Bearish**

### Условия сигнала SHORT:
1. ✅ **Режим = TREND**
2. ✅ **EMA50 slope < 0** - нисходящий тренд
3. ✅ **ADX > 20** - тренд подтвержден
4. ✅ **Цена в зоне 0.382-0.618 Fibonacci** - правильная глубина отката
5. ✅ **Цена около EMA20 ± 0.3 ATR** ИЛИ **около VWAP ± 0.3 ATR**
6. ✅ **close < EMA20** - закрытие под уровнем
7. ✅ **volume >= 1.2x** (адаптивный порог)
8. ✅ **H4 bias != Bullish**

### Используемые индикаторы:
- EMA (20, 50)
- Daily VWAP (с лентами)
- ATR (14)
- ADX (14)
- Fibonacci retracement (50 bars)
- Adaptive volume threshold

### Риск-менеджмент:
- **Stop-Loss:** Через S/R зоны
- **TP1:** entry + 1R
- **TP2:** entry + 2R

---

## 5️⃣ BREAK & RETEST ⚠️ (ПРОБЛЕМНАЯ)

**Категория:** Pullback  
**Timeframe:** 15m  
**Base Score:** 1.0  
**Сигналов:** 78 (45% от всех) - СЛИШКОМ МНОГО!

### Что анализирует:
- Swing high/low пробои
- Зона ретеста (симметричная ±0.3 ATR)
- ADX для подтверждения силы

### Параметры (ТЕКУЩИЕ):
```yaml
breakout_atr: 0.25            # Минимальное расстояние пробоя
zone_atr: [0.2, 0.3]          # Зона ретеста (симметричная)
volume_threshold: 1.5         # К среднему (не медиане!)
breakout_lookback: 20         # Поиск пробоев за 20 баров
adx_threshold: 20             # ADX >= 20
```

### Условия сигнала LONG (ТЕКУЩИЕ):
1. ✅ **Найден swing_high** (buffer=3)
2. ✅ **close > swing_high + 0.25 ATR** - пробой
3. ✅ **volume >= 1.5x** average
4. ✅ **ADX >= 20**
5. ✅ **Касание зоны ретеста** [level - 0.3 ATR, level + 0.3 ATR] за последние 5 баров
6. ✅ **Reclaim уровня** (close > level после касания)
7. ✅ **H4 bias != Bearish**

### Условия сигнала SHORT (ТЕКУЩИЕ):
1. ✅ **Найден swing_low** (buffer=3)
2. ✅ **close < swing_low - 0.25 ATR** - пробой вниз
3. ✅ **volume >= 1.5x** average
4. ✅ **ADX >= 20**
5. ✅ **Касание зоны ретеста** [level - 0.3 ATR, level + 0.3 ATR] за последние 5 баров
6. ✅ **Reclaim уровня** (close < level после касания)
7. ✅ **H4 bias != Bullish**

### ПРОБЛЕМЫ:
- ❌ **0.25 ATR слишком мало** - ловит слабые пробои
- ❌ **1.5x volume к среднему** - легко проходит
- ❌ **Симметричная зона ±0.3 ATR** - слишком широкая
- ❌ **lookback_retest = 5** баров - ловит любое касание
- ❌ **Body size не проверяется** - принимает хвосты

### ПРЕДЛОЖЕННЫЕ УЛУЧШЕНИЯ:
```yaml
# Пробой:
breakout_close_margin: 0.15        # close > level + 0.15 ATR
breakout_body_min_atr: 0.4         # body >= 0.4 ATR (сила)
volume_method: "rolling_median"    # К медиане, не среднему
adx_min: 22                        # ADX >= 22
di_ratio_min: 1.20                 # +DI/-DI >= 1.20 (15m)
adx_growth: true                   # ADX растет

# Ретест (асимметричный):
zone_upper_atr: 0.10              # Узкий запас сверху
zone_lower_atr: 0.35              # Широкий запас снизу
sweep_max_depth: 0.45             # Допуск иглы (liquidity sweep)

# Триггер:
trigger_close_margin: 0.10        # Ре-клейм с запасом
trigger_close_pct: 0.70           # Close в верхних 30%
trigger_body_min_atr: 0.15        # Минимальное тело

# HTF фильтр:
htf_free_space_min: 0.8           # До H4 зоны >= 0.8 ATR
```

### Используемые индикаторы:
- Swing levels (buffer=3, lookback=20)
- ATR (14)
- ADX (14)
- +DI, -DI (для ratio)
- Volume (rolling median/EMA)
- VWAP
- H4 S/R zones (кластеры)

---

## 6️⃣ ATR MOMENTUM

**Категория:** Breakout  
**Timeframe:** 15m  
**Base Score:** 1.0-3.0 (динамический)  

### Что анализирует:
- Импульс-бары (>= 1.4x median ATR)
- Follow-through движения
- Micro-pullback к EMA

### Параметры:
```yaml
impulse_atr: 1.4              # Импульс бар >= 1.4x median ATR
close_percentile: 20          # close в верхних 20% бара
min_distance_resistance: 1.5  # До сопротивления >= 1.5 ATR
pullback_ema: [9, 20]         # Для micro-pullback
volume_threshold: 2.0         # Объем > 2x (жесткий)
breakout_atr: [0.2, 0.3]
```

### Условия сигнала LONG:
1. ✅ **Режим = TREND**
2. ✅ **ADX >= 25** (сильный импульс, не 20!)
3. ✅ **Импульс-бар найден** (за последние 5 баров):
   - bar_range >= 1.4x median ATR
   - close в верхних 20% бара (> 80% от low)
4. ✅ **Пробой high импульса** >= 0.2-0.3 ATR ИЛИ **pullback к EMA9/20** с закрытием выше
5. ✅ **volume > 2x** average - сильный объем
6. ✅ **До resistance >= 1.5 ATR** - есть пространство
7. ✅ **H4 bias != Bearish**

### Условия сигнала SHORT:
1. ✅ **Режим = TREND**
2. ✅ **ADX >= 25** (сильный импульс)
3. ✅ **Импульс-бар найден** (за последние 5 баров):
   - bar_range >= 1.4x median ATR
   - close в нижних 20% бара (< 20% от low)
4. ✅ **Пробой low импульса** >= 0.2-0.3 ATR ИЛИ **pullback к EMA9/20** с закрытием ниже
5. ✅ **volume > 2x** average - сильный объем
6. ✅ **До support >= 1.5 ATR** - есть пространство вниз
7. ✅ **H4 bias != Bullish**

### Используемые индикаторы:
- ATR (14) с rolling median (20)
- EMA (9, 20, 200)
- ADX (14)
- Volume (rolling 20)

### Динамический score:
```python
if ADX > 30 and volume > 2.5x:
    base_score = 3.0  # Супер-импульс
elif ADX > 25:
    base_score = 2.0  # Сильный импульс
else:
    base_score = 1.0  # Обычный
```

### Риск-менеджмент:
- **Stop-Loss:** За swing reaction + 0.2-0.3 ATR
- **TP1:** 0.75-1.0 ATR
- **TP2:** 2R или до HTF уровня
- **Time-Stop:** 6-8 баров без 0.5 ATR прогресса

---

## 7️⃣ VWAP MEAN REVERSION

**Категория:** Mean Reversion  
**Timeframe:** 15m  
**Base Score:** 1.0  

### Что анализирует:
- VWAP ленты (± 1σ, ± 2σ)
- Value Area (VAH/VAL/POC)
- H4 swing levels
- Reclaim паттерны

### Параметры:
```yaml
sigma_bands: [1, 2]           # VWAP ± 1σ, ± 2σ
reclaim_bars: 2               # Hold 2 бара для подтверждения reclaim
time_stop: [6, 8]             # Баров без прогресса
```

### Условия сигнала LONG:
1. ✅ **Режим = RANGE или CHOP** (обязательно!)
2. ✅ **ОБЯЗАТЕЛЬНЫЕ проверки LOW VOLATILITY:**
   - ADX < 20
   - ATR% < p40
   - BB width < p30
   - EMA20/50 плоские (slope < 2%)
3. ✅ **BTC bias = Neutral** - BTC не импульсит
4. ✅ **Цена около VWAP-2σ или VAL** - экстремум (distance > 2σ)
5. ✅ **Confluence:** VAL ≈ H4 swing low (< 0.3 ATR)
6. ✅ **Reclaim внутрь value area** за 2 бара
7. ✅ **volume > 1.5x** median

### Условия сигнала SHORT:
1. ✅ **Режим = RANGE или CHOP** (обязательно!)
2. ✅ **ОБЯЗАТЕЛЬНЫЕ проверки LOW VOLATILITY:**
   - ADX < 20
   - ATR% < p40
   - BB width < p30
   - EMA20/50 плоские (slope < 2%)
3. ✅ **BTC bias = Neutral** - BTC не импульсит
4. ✅ **Цена около VWAP+2σ или VAH** - экстремум (distance > 2σ)
5. ✅ **Confluence:** VAH ≈ H4 swing high (< 0.3 ATR)
6. ✅ **Reclaim внутрь value area** за 2 бара
7. ✅ **volume > 1.5x** median

### Используемые индикаторы:
- Daily VWAP (± 1σ, ± 2σ)
- Volume Profile (VAH/VAL/POC)
- ATR (14)
- ADX (14)
- Bollinger Bands (20, std=2.0)
- EMA (20, 50)
- H4 swing levels

### Риск-менеджмент:
- **Stop-Loss:** За экстремум + 0.25 ATR
- **TP1:** VWAP/POC
- **TP2:** Середина/противоположная лента
- **Time-Stop:** 6-8 баров

---

## 8️⃣ RANGE FADE

**Категория:** Mean Reversion  
**Timeframe:** 15m  
**Base Score:** 1.0  

### Что анализирует:
- Границы рейнджа с confluence
- Качество уровней (>= 2-3 теста)
- H4 swing levels для confluence

### Параметры:
```yaml
min_tests: 2                  # Минимум 2 теста уровня
time_stop: [6, 8]
reclaim_bars: 2               # Hold 2 бара для reclaim
lookback_bars: 100
```

### Условия сигнала LONG:
1. ✅ **Режим = RANGE**
2. ✅ **Найдены качественные границы:**
   - Resistance: >= 2 теста VAH ИЛИ H4_high
   - Support: >= 2 теста VAL ИЛИ H4_low
3. ✅ **Confluence подтвержден:**
   - Минимум 2 источника для каждой границы
   - Уровни близки (< 0.2 ATR)
4. ✅ **Цена около support** (< 0.3 ATR)
5. ✅ **RSI < 30** (oversold)
6. ✅ **Reclaim внутрь рейнджа** (hold 2 бара)

### Условия сигнала SHORT:
1. ✅ **Режим = RANGE**
2. ✅ **Найдены качественные границы:**
   - Resistance: >= 2 теста VAH ИЛИ H4_high
   - Support: >= 2 теста VAL ИЛИ H4_low
3. ✅ **Confluence подтвержден:**
   - Минимум 2 источника для каждой границы
   - Уровни близки (< 0.2 ATR)
4. ✅ **Цена около resistance** (< 0.3 ATR)
5. ✅ **RSI > 70** (overbought)
6. ✅ **Reclaim внутрь рейнджа** (hold 2 бара)

### Используемые индикаторы:
- H4 swing high/low (реальные, не расчетные)
- Volume Profile (VAH/VAL)
- ATR (14)
- RSI (14) - для дивергенций
- Reclaim checker

### Риск-менеджмент:
- **Stop-Loss:** За границу рейнджа + 0.1-0.2 ATR
- **TP1:** Середина рейнджа
- **TP2:** Противоположная граница
- **Time-Stop:** 6-8 баров

---

## 9️⃣ VOLUME PROFILE

**Категория:** Mean Reversion / Breakout  
**Timeframe:** 15m  
**Base Score:** 2.0-2.5  

### Что анализирует:
- VAH/VAL edges
- Rejection vs Acceptance паттерны
- POC shift (смещение точки контроля)

### Параметры:
```yaml
lookback_bars: 100
atr_threshold: 0.25           # ATR для acceptance
min_closes_outside: 2         # Минимум 2 close за VA
poc_shift_threshold: 0.1      # Порог смещения POC (%)
reclaim_bars: 2
```

### Условия REJECTION (fade):
1. ✅ **Цена около VAH** (расстояние <= 0.3 ATR)
2. ✅ **close обратно в value area**
3. ✅ **POC НЕ сдвигается** (< 0.1% от range)
4. ✅ **CVD flip** - разворот баланса агрессоров
5. ✅ **Imbalance flip** - разворот orderbook
6. ✅ **OI не растет** - нет новых позиций

**Base Score:** 2.5 (fade)

### Условия ACCEPTANCE (breakout):
1. ✅ **>= 2 close за VA** ИЛИ **>= 0.25 ATR за VA**
2. ✅ **POC смещается** в направлении движения
3. ✅ **Объем/POC shift** подтверждают
4. ✅ **CVD/OI по направлению выхода**

**Base Score:** 2.0 (acceptance)

### Используемые индикаторы:
- Volume Profile (50 bins)
- VAH/VAL/POC
- ATR (14)
- CVD
- POC shift tracking (history by symbol)

### Риск-менеджмент:
- **FADE:** Стоп за экстремум, TP к VWAP/POC
- **ACCEPTANCE:** Стоп за ретест, TP по R-множителю

---

## 🔟 RSI/STOCHASTIC MEAN REVERSION

**Категория:** Mean Reversion  
**Timeframe:** 15m  
**Base Score:** 1.0  

### Что анализирует:
- RSI адаптивные пороги (p15/p85 за 90 дней)
- Stochastic крест
- Дивергенции price vs oscillators

### Параметры:
```yaml
rsi_period: 14
stoch_period: 14
oversold_percentile: 20       # p15-20
overbought_percentile: 80     # p80-85
lookback: 90                  # дней для перцентилей
reclaim_bars: 2
```

### Условия сигнала LONG:
1. ✅ **Режим = RANGE или CHOP**
2. ✅ **ADX < 25** - слабый тренд
3. ✅ **RSI < p20** (адаптивный oversold)
4. ✅ **Stochastic крест вверх** (K пересек D снизу)
5. ✅ **Цена около края рейнджа ∩ VWAP/VA** - confluence зоны
6. ✅ **Опционально: Bullish divergence** (price LL, RSI HL)

### Условия сигнала SHORT:
1. ✅ **Режим = RANGE или CHOP**
2. ✅ **ADX < 25** - слабый тренд
3. ✅ **RSI > p80** (адаптивный overbought)
4. ✅ **Stochastic крест вниз** (K пересек D сверху)
5. ✅ **Цена около края рейнджа ∩ VWAP/VA** - confluence зоны
6. ✅ **Опционально: Bearish divergence** (price HH, RSI LH)

### Используемые индикаторы:
- RSI (14) с адаптивными порогами
- Stochastic (14, K and D)
- ADX (14)
- VWAP, Volume Profile (для зон)
- ATR (14)
- Divergence detector

### Риск-менеджмент:
- **Stop-Loss:** За swing low + margin
- **TP1:** Середина рейнджа/VWAP
- **TP2:** Противоположный край
- **Time-Stop:** По волатильности

---

## 1️⃣1️⃣ LIQUIDITY SWEEP

**Категория:** Mean Reversion  
**Timeframe:** 15m  
**Base Score:** 2.0-2.5  

### Что анализирует:
- Sweep паттерны (прокол high/low)
- Быстрый reclaim
- Acceptance vs Fade различие

### Параметры:
```yaml
sweep_min_atr: 0.1           # Минимальный прокол
sweep_max_atr: 0.3           # Максимальный прокол
sweep_min_pct: 0.001         # 0.1%
sweep_max_pct: 0.002         # 0.2%
volume_threshold: 1.5        # Объем sweep > 1.5x
acceptance_min_closes: 2     # Для acceptance
acceptance_atr_distance: 0.25
max_bars_after_sweep: 3      # Окно проверки
```

### Условия FADE (reclaim):
1. ✅ **Прокол 0.1-0.3 ATR** за swing high/low
2. ✅ **Прокол 0.1-0.2%** от уровня
3. ✅ **Reclaim в том же/след. баре** - быстрый возврат
4. ✅ **CVD flip** - разворот баланса
5. ✅ **Imbalance flip** - orderbook развернулся
6. ✅ **volume > 1.5x** - объем sweep подтвержден

**Base Score:** 2.5

### Условия CONTINUATION (acceptance):
1. ✅ **>= 2 close за sweep level** (за 3 бара)
2. ✅ **>= 0.25 ATR** acceptance distance
3. ✅ **POC-сдвиг** в направлении движения
4. ✅ **OI ↑** - новые позиции открываются

**Base Score:** 2.0

### Используемые индикаторы:
- Swing levels (последние 50 баров)
- ATR (14)
- CVD
- Volume (median)
- Active sweeps tracking (с автоочисткой)

### Риск-менеджмент:
- **FADE:** Агрессивный вход, стоп за sweep point
- **CONTINUATION:** Стоп за reclaim zone

---

## 1️⃣2️⃣ ORDER FLOW

**Категория:** Mean Reversion  
**Timeframe:** 15m  
**Base Score:** 2.5  

### Что анализирует:
- Depth imbalance (bid/ask)
- CVD direction
- OI Delta
- Imbalance/Absorption/Refill

### Параметры:
```yaml
imbalance_threshold: 0.6     # |imbalance| > 0.6 сильный
oi_delta_threshold: 5.0      # ΔOI > 5% значим
volume_threshold: 1.5
refill_check_window: 5       # Баров для refill проверки
```

### Условия сигнала LONG:
1. ✅ **Цена около VAL/POC** (< 0.3 ATR)
2. ✅ **Depth imbalance > +0.6** - bid сторона доминирует
3. ✅ **CVD направлен вверх** - агрессоры покупают
4. ✅ **OI Delta > +5%** (30-60 мин) - позиции открываются
5. ✅ **volume > 1.5x** average
6. ✅ **Reclaim/acceptance** ценой подтвержден

### Условия сигнала SHORT:
1. ✅ **Цена около VAH/POC** (< 0.3 ATR)
2. ✅ **Depth imbalance < -0.6** - ask сторона доминирует
3. ✅ **CVD направлен вниз** - агрессоры продают
4. ✅ **OI Delta > +5%** (30-60 мин) - позиции открываются
5. ✅ **volume > 1.5x** average
6. ✅ **Reclaim/acceptance** ценой подтвержден

### Используемые индикаторы:
- Depth imbalance (real-time from API)
- CVD series
- OI Delta % (5m data, 30 periods)
- Volume Profile
- ATR (14)
- Refill detector

### Риск-менеджмент:
- **Stop-Loss:** За уровень без order flow поддержки
- **TP1:** Ближайший противоположный уровень
- **TP2:** По R-множителю

---

## 1️⃣3️⃣ CVD DIVERGENCE ⚠️ (ПРОБЛЕМНАЯ)

**Категория:** Mean Reversion  
**Timeframe:** 15m  
**Base Score:** 2.0-2.5 (ЗАВЫШЕН!)  
**Сигналов:** 81 (47% от всех) - СЛИШКОМ МНОГО!

### Что анализирует:
- Дивергенции цена vs CVD
- Подтверждение пробоев через CVD

### Параметры (ТЕКУЩИЕ):
```yaml
lookback_bars: 20            # Поиск дивергенций
divergence_threshold: 0.3    # 30% изменение CVD (МЯГКО!)
```

### Типы сигналов:

#### УСЛОВИЯ СИГНАЛА LONG (4 типа):

**1. BULLISH DIVERGENCE:**
- Цена: LL (Lower Low)
- CVD: HL (Higher Low)
- cvd_rise > 30%
- volume >= median
- **Base Score: 2.5** ← СЛИШКОМ ВЫСОКО!

**2. CONFIRMATION LONG:**
- Пробой вверх + CVD растет
- close > recent_high (30 bars)
- CVD[-1] > CVD[-5]
- **Base Score: 2.0** ← ВЫСОКО!

#### УСЛОВИЯ СИГНАЛА SHORT (4 типа):

**3. BEARISH DIVERGENCE:**
- Цена: HH (Higher High)
- CVD: LH (Lower High)
- cvd_drop > 30%
- volume >= median
- **Base Score: 2.5** ← СЛИШКОМ ВЫСОКО!

**4. CONFIRMATION SHORT:**
- Пробой вниз + CVD падает
- close < recent_low (30 bars)
- CVD[-1] < CVD[-5]
- **Base Score: 2.0** ← ВЫСОКО!

### Regime multiplier:
- **TREND:** 0.5x (дивергенции менее надежны)
- **RANGE/SQUEEZE/CHOP:** 1.0x

### ПРОБЛЕМЫ:
- ❌ **Base score 2.0-2.5 слишком высокий** - побеждает другие стратегии
- ❌ **divergence_threshold 0.3 (30%) мягкий** - много ложных дивергенций
- ❌ **4 типа сигналов** - слишком много путей дать сигнал
- ❌ **Volume check не блокирует** - только логирует warning
- ❌ **Local peaks order=3** - находит много мелких пиков

### ПРЕДЛОЖЕННЫЕ УЛУЧШЕНИЯ:
```yaml
# Снизить base score:
divergence_score: 1.5         # Было: 2.5
confirmation_score: 1.0       # Было: 2.0

# Ужесточить порог:
divergence_threshold: 0.5     # Было: 0.3 (требовать 50% изменение)

# Усилить volume check:
volume_min_multiplier: 1.2    # Требовать >= 120% медианы (не просто >=)

# Увеличить lookback:
lookback_bars: 30             # Было: 20 (искать более значимые дивергенции)
```

### Используемые индикаторы:
- CVD series (из indicators или расчет из volume)
- Local peaks/troughs (order=3)
- Volume (median 20)
- ATR (14)

---

## 1️⃣4️⃣ TIME-OF-DAY

**Категория:** Breakout / Mean Reversion  
**Timeframe:** 15m  
**Base Score:** 2.0-2.5  

### Что анализирует:
- Временные паттерны сессий
- Объем и волатильность по часам
- Сессионная активность

### Параметры:
```yaml
# Жирные окна (breakout):
breakout_windows:
  - [7, 9]     # EU open 07:00-09:00 UTC
  - [13, 15]   # US open 13:00-15:00 UTC

# Тонкие окна (mean reversion):
mr_windows:
  - [0, 2]     # Asia night 00:00-02:00 UTC
  - [22, 24]   # After US close 22:00-24:00 UTC

volume_threshold: 1.5
volatility_threshold_percentile: 50
```

### Общие условия:
1. ✅ **Текущий час в одном из активных окон** (UTC)
2. ✅ **volume > 1.5x** median (100 bars)
3. ✅ **ATR% > p50** - волатильность выше медианы

### Условия LONG (зависит от окна):

**Breakout LONG (жирные окна 7-9, 13-15 UTC):**
- ✅ Пробой недавнего high
- ✅ Объем подтверждает
- ✅ **Base Score:** 2.5

**Mean Reversion LONG (тонкие окна 0-2, 22-24 UTC):**
- ✅ Экстремум около VWAP-2σ/VAL
- ✅ Разворот индикаторов вверх
- ✅ **Base Score:** 2.0

### Условия SHORT (зависит от окна):

**Breakout SHORT (жирные окна 7-9, 13-15 UTC):**
- ✅ Пробой недавнего low
- ✅ Объем подтверждает
- ✅ **Base Score:** 2.5

**Mean Reversion SHORT (тонкие окна 0-2, 22-24 UTC):**
- ✅ Экстремум около VWAP+2σ/VAH
- ✅ Разворот индикаторов вниз
- ✅ **Base Score:** 2.0

### Используемые индикаторы:
- ATR % (14)
- Volume (median 100)
- Time slots (UTC timezone)
- ATR percentile
- Session-specific logic

---

## 📊 СВОДНАЯ ТАБЛИЦА

| # | Стратегия | TF | Категория | Score | Режим | Сигналов | Ключевые индикаторы |
|---|-----------|----|-----------|----- :|-------|----------|---------------------|
| 1 | Donchian Breakout | 1h | Breakout | 1.0 | TREND | ? | Donchian(20), BB width p30-40, ADX |
| 2 | Squeeze Breakout | 1h | Breakout | 1.0 | SQUEEZE | ? | BB/KC squeeze, EMA20, ADX>=20 |
| 3 | ORB/IRB | 15m | Breakout | 1.0 | Any | ? | IB range, H4 trend, time slots |
| 4 | MA/VWAP Pullback | 4h | Pullback | 1.0 | TREND | ? | EMA50, Fib 0.382-0.618, VWAP |
| 5 | Break & Retest | 15m | Pullback | 1.0 | Any | **78** | Swing levels, ADX>=20, **СЛАБЫЕ УСЛОВИЯ** |
| 6 | ATR Momentum | 15m | Breakout | 1-3 | TREND | 1 | ATR>=1.4x, ADX>=25, volume>2x |
| 7 | VWAP MR | 15m | MR | 1.0 | RANGE | ? | VWAP±σ, VA, ADX<20, BB<p30 |
| 8 | Range Fade | 15m | MR | 1.0 | RANGE | ? | Range bounds, H4 swings, confluence |
| 9 | Volume Profile | 15m | MR | 2.0-2.5 | Any | ? | VAH/VAL/POC, rejection/acceptance |
| 10 | RSI/Stoch MR | 15m | MR | 1.0 | RANGE | ? | RSI p15/p85, Stoch cross, divergence |
| 11 | Liquidity Sweep | 15m | MR | 2.0-2.5 | Any | ? | Sweep 0.1-0.3 ATR, reclaim, CVD flip |
| 12 | Order Flow | 15m | MR | 2.5 | Any | ? | Depth>0.6, CVD, OI>5%, imbalance |
| 13 | CVD Divergence | 15m | MR | **2.0-2.5** | Any | **81** | CVD divergence, **4 ТИПА, ВЫСОКИЙ SCORE** |
| 14 | Time-of-Day | 15m | Both | 2.0-2.5 | Any | 12 | Time slots, volume>1.5x, ATR>p50 |

---

## 🔧 РЕКОМЕНДАЦИИ ПО БАЛАНСИРОВКЕ

### 1. СНИЗИТЬ ДОМИНИРОВАНИЕ CVD DIVERGENCE

**Проблема:** 81 сигнал (47%) - доминирует из-за высокого score и мягких условий

**Решения:**
```yaml
# В src/strategies/cvd_divergence.py:
base_score:
  divergence: 1.5              # Было: 2.5
  confirmation: 1.0            # Было: 2.0

divergence_threshold: 0.5      # Было: 0.3 (требовать 50% изменение)
lookback_bars: 30              # Было: 20
volume_min_multiplier: 1.2     # Требовать >= 120% медианы
```

### 2. УЖЕСТОЧИТЬ BREAK & RETEST

**Проблема:** 78 сигналов (45%) - слишком мягкие условия

**Решения:**
```yaml
# Пробой:
breakout_close_margin: 0.15     # close > level + margin
breakout_body_min_atr: 0.4      # body >= 40% ATR
adx_min: 22                     # ADX >= 22 (было 20)
di_ratio_min: 1.20              # +DI/-DI >= 1.20
volume_method: "rolling_median" # К медиане

# Ретест (асимметричный):
zone_upper_atr: 0.10           # Узкий сверху (было 0.3)
zone_lower_atr: 0.35           # Широкий снизу (было 0.3)
trigger_close_pct: 0.70        # Close в верхних 30%
htf_free_space_min: 0.8        # До H4 зоны >= 0.8 ATR
```

### 3. ГЛОБАЛЬНЫЕ УЛУЧШЕНИЯ

**Увеличить порог входа:**
```yaml
scoring:
  enter_threshold: 3.0         # Было: 2.0
```

**Ужесточить риск:**
```yaml
risk:
  max_stop_distance_atr: 2.0   # Было: 3.0
  max_risk_pct: 1.5            # Новое - макс 1.5% риск
```

**Оптимизировать time stops:**
```yaml
risk:
  time_stop_bars: [12, 16]     # Было: [6, 8] - дать больше времени
```

---

## 📈 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ ПОСЛЕ БАЛАНСИРОВКИ

| Метрика | Сейчас | Цель |
|---------|--------|------|
| **CVD Divergence сигналов** | 81 (47%) | ~30-40 (20-25%) |
| **Break & Retest сигналов** | 78 (45%) | ~30-40 (20-25%) |
| **Другие стратегии** | 13 (8%) | ~80-100 (50-55%) |
| **Win Rate** | 15.2% | **30-40%** |
| **TIME_STOP %** | 59.5% | **30-40%** |
| **Средний SL** | -3.30% | **-1.5% до -2.0%** |
| **Средний PnL** | -0.09% | **+1.5% до +2.5%** |

---

## 🎯 ПРИОРИТЕТНЫЙ ПЛАН ДЕЙСТВИЙ

### Фаза 1: Экстренные меры (немедленно)
1. ✅ Снизить CVD Divergence base_score: 2.5→1.5, 2.0→1.0
2. ✅ Увеличить CVD divergence_threshold: 0.3→0.5
3. ✅ Увеличить Break & Retest breakout_atr: 0.25→0.4
4. ✅ Увеличить volume_threshold: 1.5→2.0
5. ✅ Увеличить enter_threshold: 2.0→3.0

### Фаза 2: Оптимизация (через неделю)
6. ✅ Реализовать асимметричную зону для Break & Retest
7. ✅ Добавить body check (>= 0.4 ATR)
8. ✅ Добавить +DI/-DI ratio check
9. ✅ Увеличить time_stop_bars: [6,8]→[12,16]
10. ✅ Снизить TP2 targets с 2R до 1.5R

### Фаза 3: Продвинутые (через месяц)
11. ✅ HTF S/R zones кластеризация
12. ✅ Liquidity sweep логика для Break & Retest
13. ✅ Динамические TP на основе S/R зон
14. ✅ Trailing stop после TP1
15. ✅ Активация спящих стратегий (Donchian, Squeeze, ORB)

---

**Дата создания:** 13 октября 2025  
**Версия:** 1.0  
**Автор:** Trading Bot Analysis System
