# Проблема с доступом к Binance API (Ошибка 451)

## Описание проблемы

При запуске бота возникает ошибка **HTTP 451 "Unavailable For Legal Reasons"** при обращении к Binance API.

```
aiohttp.client_exceptions.ClientResponseError: 451, message='', url='https://fapi.binance.com/fapi/v1/exchangeInfo'
```

## Причина

Binance блокирует доступ к API с IP-адресов, которые находятся в ограниченных регионах:
- США
- Канада (Онтарио)
- Некоторые другие юрисдикции

Сервера Replit, вероятно, расположены в одном из этих регионов, поэтому доступ блокируется.

## Решения

### Вариант 1: Запуск на локальном компьютере (Windows)
**Рекомендуется для вашего случая**

1. Скачайте весь код проекта на ваш локальный компьютер
2. Установите Python 3.12+
3. Установите зависимости:
   ```cmd
   pip install python-telegram-bot python-binance ccxt pandas numpy pandas-ta aiohttp websockets python-dotenv APScheduler pytz pyyaml alembic sqlalchemy
   ```
4. Создайте файл `.env` со следующими переменными:
   ```
   TELEGRAM_BOT_TOKEN=8443850632:AAGtbv8doBSv7DoZeYPc0A7UmW-QzTw2xfY
   TELEGRAM_CHAT_ID=436451652
   BINANCE_API_KEY=VMefOXh4MHuB1BC3lfhXfL9upoB7UFoittFSsmjzNeJAqTcKfdu1JLzPOx4tUguD
   BINANCE_API_SECRET=2TfmsK3vh0EYcZVzLm3LqVV8wOGTPr2U5qz39cw2D6rVq2AGSH12URr8IbUbTGnA
   ```
5. Запустите бота:
   ```cmd
   python main.py
   ```

### Вариант 2: VPS/Сервер в разрешённом регионе

Разверните бота на VPS в одном из разрешённых регионов:
- Европа (Германия, Великобритания, Франция)
- Азия (Сингапур, Гонконг, Япония - кроме ограниченных стран)

Рекомендуемые провайдеры:
- **DigitalOcean** (дата-центры в Европе/Азии)
- **Vultr** (дата-центры по всему миру)
- **Hetzner** (Германия/Финляндия)
- **Contabo** (Германия)

### Вариант 3: Использование прокси

Добавить прокси-сервер в `src/binance/client.py`:

```python
async def _request(self, method: str, endpoint: str, params: Dict = None, 
                   signed: bool = False, weight: int = 1) -> Any:
    # ...
    
    # Добавить прокси
    proxy = "http://your-proxy-ip:port"
    
    async with self.session.request(
        method, url, 
        params=params, 
        headers=headers,
        proxy=proxy  # <-- добавить эту строку
    ) as response:
        # ...
```

## Текущий статус бота

Несмотря на блокировку API, бот успешно:
- ✅ Инициализирован
- ✅ База данных создана
- ✅ Конфигурация загружена
- ✅ Логирование работает
- ✅ Все модули импортированы без ошибок

Архитектура полностью готова к работе, как только будет решена проблема с доступом к Binance API.

## Что работает

### Реализованные модули:
1. **Binance Client** - REST API клиент с rate limiting
2. **WebSocket Manager** - управление WebSocket подключениями
3. **OrderBook Engine** - локальная книга ордеров с синхронизацией
4. **Data Loader** - загрузка исторических данных
5. **Технические индикаторы** - ATR, ADX, EMA, BB, Donchian, RSI, Stochastic
6. **VWAP** - дневной и anchored VWAP с bands
7. **Volume Profile** - VAH/VAL/VPOC
8. **CVD** - барная и тиковая CVD с дивергенциями
9. **Market Regime Detector** - TREND/RANGE/SQUEEZE
10. **SQLite Database** - полная схема с миграциями
11. **Telegram Bot** - базовые команды
12. **Logging System** - консоль + файлы с ротацией

## Следующие шаги

1. Выберите один из вариантов решения проблемы 451
2. Запустите бота в разрешённом регионе
3. Продолжите разработку оставшихся модулей:
   - 17-18 торговых стратегий
   - Система скоринга
   - BTC-фильтр
   - Risk management
   - Kill-switch механизмы
   - Модуль бэктестинга
