@echo off
chcp 1251 >nul
echo ============================================================
echo   Trading Bot - Автоматический запуск
echo ============================================================
echo.

REM Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не установлен!
    echo Скачайте Python 3.11+ с https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python установлен
echo.

REM Проверка виртуального окружения
if not exist "venv" (
    echo [ИНФО] Создаю виртуальное окружение...
    python -m venv venv
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать виртуальное окружение
        pause
        exit /b 1
    )
    echo [OK] Виртуальное окружение создано
    echo.
)

REM Активация виртуального окружения
echo [ИНФО] Активирую виртуальное окружение...
call venv\Scripts\activate.bat

REM Проверка requirements.txt
if not exist "requirements.txt" (
    echo [ОШИБКА] Файл requirements.txt не найден!
    pause
    exit /b 1
)

REM Проверка установленных пакетов
echo [ИНФО] Проверяю зависимости...
pip show aiohttp >nul 2>&1
if errorlevel 1 (
    echo [ИНФО] Устанавливаю зависимости (это может занять время)...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости
        pause
        exit /b 1
    )
    echo [OK] Все зависимости установлены
) else (
    echo [OK] Зависимости уже установлены
    
    REM Проверяем обновления
    echo [ИНФО] Проверяю обновления...
    pip install -r requirements.txt --quiet --upgrade 2>nul
)
echo.

REM Проверка .env файла
if not exist ".env" (
    echo [ВНИМАНИЕ] Файл .env не найден!
    echo.
    echo Создаю шаблон .env файла...
    (
        echo # Binance API Keys
        echo BINANCE_API_KEY=your_api_key_here
        echo BINANCE_API_SECRET=your_secret_key_here
        echo.
        echo # Telegram Bot
        echo TELEGRAM_BOT_TOKEN=your_telegram_bot_token
        echo TELEGRAM_CHAT_ID=your_chat_id
        echo.
        echo # Session Secret
        echo SESSION_SECRET=random_secret_string_here
    ) > .env
    echo.
    echo [ТРЕБУЕТСЯ ДЕЙСТВИЕ] Откройте файл .env и добавьте ваши API ключи!
    echo.
    pause
)

REM Проверка config.yaml
if not exist "config.yaml" (
    echo [ОШИБКА] Файл config.yaml не найден!
    pause
    exit /b 1
)

REM Создание папки для данных
if not exist "data" mkdir data

REM Проверка main.py
if not exist "main.py" (
    echo [ОШИБКА] Файл main.py не найден!
    echo Убедитесь что вы находитесь в корневой папке проекта
    pause
    exit /b 1
)

echo ============================================================
echo   Запуск бота...
echo ============================================================
echo.

REM Запуск бота
venv\Scripts\python.exe main.py

REM Если бот упал
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Бот завершился с ошибкой
    echo Проверьте логи выше для деталей
    pause
)
