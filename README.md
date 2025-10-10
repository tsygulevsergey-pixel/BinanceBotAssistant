# Trading Bot - Binance USDT-M Futures

Торговый бот для Binance USDT-M Futures с публикацией сигналов в Telegram.

## Возможности

- **Подключение к Binance USDT-M Futures**: REST API и WebSocket для получения данных в реальном времени
- **Локальная orderbook engine**: Синхронизация через REST snapshots и WS diff updates
- **Загрузка исторических данных**: Автоматическая загрузка 60-90 дней данных с data.binance.vision
- **Технические индикаторы**: ATR, ADX, EMA, Bollinger Bands, VWAP, CVD, Volume Profile
- **Детектор режимов рынка**: TREND / RANGE / SQUEEZE
- **17-18 торговых стратегий**: Donchian Breakout, Squeeze→Breakout, ORB/IRB, и другие
- **Система скоринга**: Порог ≥+2.0 с учетом объема, CVD, ΔOI, depth imbalance
- **BTC-фильтр**: Блокировка входов против H1 EMA-bias BTCUSDT
- **Risk management**: Расчет стоп-лоссов, тейк-профитов, time-stops
- **Telegram бот**: Публикация сигналов на русском языке с командами управления
- **Kill-switch механизмы**: Автоматическое восстановление при ошибках

## Установка

Все зависимости установлены автоматически через Replit.

## Конфигурация

Основные параметры настраиваются в файле `config.yaml`:
- Пороги скоринга
- Risk limits
- ToD слоты
- Пороги индикаторов
- Rate limit budgets

## Запуск

```bash
python main.py
```

## Команды Telegram

- `/start` - Начало работы с ботом
- `/help` - Справка по командам
- `/strategies` - Список активных стратегий
- `/status` - Состояние бота
- `/latency` - Задержки системы
- `/report` - Статистика сигналов
- `/export` - Экспорт данных
- `/snooze` - Отключить уведомления
- `/digest` - Дайджест за период

## Структура проекта

```
.
├── src/
│   ├── binance/          # Binance API клиент, WebSocket, orderbook
│   ├── indicators/       # Технические индикаторы, VWAP, CVD, Volume Profile
│   ├── detectors/        # Детекторы режимов рынка
│   ├── strategies/       # Торговые стратегии
│   ├── scoring/          # Система скоринга сигналов
│   ├── risk/             # Risk management
│   ├── telegram/         # Telegram бот
│   ├── database/         # SQLite модели и миграции
│   ├── backtest/         # Модуль бэктестинга
│   └── utils/            # Утилиты (config, logger, rate_limiter)
├── data/                 # База данных и кэш
├── logs/                 # Логи
├── config.yaml           # Конфигурация
└── main.py              # Главный файл
```

## Безопасность

- Все секреты (API ключи, токены) хранятся в Replit Secrets
- Никогда не логируются и не выводятся в консоль
- Автоматическая ротация логов с хранением 30 дней

## Лицензия

Proprietary
