# 🤖 Trading Bot - Binance USDT-M Futures

Комплексный торговый бот с 16 стратегиями для Binance фьючерсов.

## 🚀 Быстрый старт (3 шага)

### 1️⃣ Подготовка API ключей

1. Зайдите на [Binance](https://www.binance.com) → API Management
2. Создайте API ключ с правами:
   - ✅ Enable Futures
   - ✅ Enable Reading
   - ✅ Enable Spot & Margin Trading (для live торговли)
3. Сохраните API Key и Secret Key

### 2️⃣ Запуск бота

**Windows:**
```
Двойной клик на start.bat
```

**Linux/Mac:**
```bash
./start.sh
```

### 3️⃣ Настройка

При первом запуске откроется файл `.env` - добавьте ваши ключи:

```env
BINANCE_API_KEY=ваш_api_key
BINANCE_API_SECRET=ваш_secret_key
```

Затем в `config.yaml` измените режим:

```yaml
binance:
  signals_only_mode: false  # false = live торговля
  use_testnet: false        # false = реальный Binance
```

**Готово!** Запустите `start.bat` снова.

---

## 📊 Реализованные стратегии (16/18)

### Breakout (Пробой)
1. ✅ **Donchian Breakout** - пробой канала Дончиана
2. ✅ **Squeeze Breakout** - сжатие и расширение волатильности
3. ✅ **ORB/IRB** - пробой начального диапазона

### Pullback (Откат)
4. ✅ **MA/VWAP Pullback** - откат к скользящим средним
5. ✅ **Break & Retest** - пробой и ретест
6. ✅ **ATR Momentum** - моментум стратегия

### Mean Reversion (Возврат к среднему)
7. ✅ **VWAP Mean Reversion** - возврат к VWAP
8. ✅ **Range Fade** - торговля в диапазоне
9. ✅ **Volume Profile** - уровни VAH/VAL
10. ✅ **RSI/Stochastic MR** - перекупленность/перепроданность

### Advanced (Продвинутые)
11. ✅ **Liquidity Sweep** - охота за стопами
12. ✅ **Order Flow** - анализ потока ордеров
13. ✅ **CVD Divergence** - дивергенции объёма
14. ✅ **Time-of-Day** - сессионные паттерны

### Arbitrage (Арбитраж)
19. ✅ **Cash-and-Carry** - арбитраж funding rate (требует данные)
26. ✅ **Market Making** - маркет-мейкинг (требует HFT данные)

---

## ⚙️ Основные настройки (config.yaml)

```yaml
# Режим работы
binance:
  signals_only_mode: false    # false = живая торговля
  use_testnet: false          # false = реальный API

# Отбор пар
universe:
  min_volume_24h: 10000000    # Минимум $10M объёма

# Риск-менеджмент
risk:
  risk_per_trade_R: 0.75      # Риск на сделку
  daily_stop_R: 3.0           # Дневной лимит убытков
  weekly_stop_R: 7.0          # Недельный лимит

# Сигналы
scoring:
  enter_threshold: 2.0        # Порог входа (>=2.0)
  volume_mult: 1.5            # Множитель объёма
```

---

## 📋 Что делает start.bat

### Первый запуск:
```
✓ Проверка Python (нужен 3.11+)
✓ Создание виртуального окружения
✓ Установка зависимостей
✓ Создание .env шаблона
✓ Запуск бота
```

### Последующие запуски:
```
✓ Быстрая проверка зависимостей
✓ Обновление при необходимости
✓ Запуск бота
```

---

## 🔑 Переменные окружения (.env)

```env
# Binance API (обязательно)
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_secret_key_here

# Telegram (опционально)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Session
SESSION_SECRET=random_string
```

---

## 🌍 Важно: Географические ограничения

⚠️ **Binance блокирует доступ из:**
- США
- Канада
- Некоторые другие страны

**Решение:** Используйте VPS в Европе или Азии (DigitalOcean, AWS, Vultr)

---

## 📈 Как работает бот

1. **Загружает данные** - 60-90 дней истории для 487 пар
2. **Анализирует рынок** - каждые 60 секунд
3. **Детектирует режим** - TREND/RANGE/SQUEEZE
4. **Запускает стратегии** - все 16 одновременно
5. **Скоринг сигналов** - только при score ≥ +2.0
6. **Фильтрация BTC** - блокирует противоположные сделки
7. **Отправка уведомлений** - Telegram алерты

---

## 🐛 Решение проблем

### Python не установлен
```
Скачайте с https://www.python.org/downloads/
Нужна версия 3.11 или выше
```

### Ошибка HTTP 451
```
Binance заблокировал доступ из вашей страны
Решение: используйте VPN или VPS
```

### Нет сигналов
```
Это нормально! Бот ждёт подходящих условий
Порог входа: score >= 2.0
```

### Ошибки импорта
```
pip install -r requirements.txt --force-reinstall
```

---

## 📁 Структура проекта

```
trading-bot/
├── main.py                 # Главный файл
├── config.yaml            # Настройки
├── start.bat              # Запуск (Windows)
├── start.sh               # Запуск (Linux/Mac)
├── requirements.txt       # Зависимости
├── .env                   # API ключи (создастся автоматически)
├── src/                   # Исходный код
│   ├── strategies/       # 16 стратегий
│   ├── binance/          # Binance API
│   ├── scoring/          # Система скоринга
│   ├── filters/          # BTC фильтр
│   └── detectors/        # Детектор режимов
└── data/                  # База данных SQLite
```

---

## 🎯 Telegram команды

После настройки Telegram бота:

```
/start    - Запуск бота
/help     - Помощь
/status   - Статус бота
/strategies - Список стратегий
/report   - Отчёт по сигналам
/export   - Экспорт данных
```

---

## ⚡ Системные требования

- **Python:** 3.11 или выше
- **RAM:** 2GB+ (для 487 пар)
- **Диск:** 500MB+ (база данных)
- **Интернет:** Стабильное соединение
- **ОС:** Windows 10+, Linux, MacOS

---

## 🔒 Безопасность

- ✅ API ключи в .env (не коммитятся в git)
- ✅ Виртуальное окружение изолировано
- ✅ Ограничения IP на Binance (настройте)
- ✅ Только Futures права (не нужен вывод средств)

---

## 📞 Поддержка

При проблемах проверьте:
1. Логи бота (в консоли)
2. Файл .env (правильные ключи?)
3. config.yaml (режим signals_only_mode?)
4. Доступ к Binance (VPN?)

---

## 🚀 Следующие шаги

1. ✅ Запустите бота с `start.bat`
2. ✅ Добавьте API ключи в `.env`
3. ✅ Настройте `config.yaml`
4. ✅ Начните с малых позиций!
5. ✅ Мониторьте через Telegram

**Удачной торговли!** 📈
