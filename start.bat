@echo off
chcp 65001 >nul
echo ============================================================
echo   Trading Bot - Автоматический запуск
echo ============================================================
echo.

REM Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не установлен!
    echo Скачайте Python 3.11+ с https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python установлен
echo.

REM Проверка виртуального окружения
if not exist "venv" (
    echo [INFO] Создаю виртуальное окружение...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Не удалось создать виртуальное окружение
        pause
        exit /b 1
    )
    echo [OK] Виртуальное окружение создано
    echo.
)

REM Активация виртуального окружения
echo [INFO] Активирую виртуальное окружение...
call venv\Scripts\activate.bat

REM Проверка requirements.txt
if not exist "requirements.txt" (
    echo [ERROR] Файл requirements.txt не найден!
    pause
    exit /b 1
)

REM Проверка установленных пакетов
echo [INFO] Проверяю зависимости...
pip show aiohttp >nul 2>&1
if errorlevel 1 (
    echo [INFO] Устанавливаю зависимости (это может занять время)...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Не удалось установить зависимости
        pause
        exit /b 1
    )
    echo [OK] Все зависимости установлены
) else (
    echo [OK] Зависимости уже установлены
    
    REM Проверяем, нужно ли обновить
    echo [INFO] Проверяю обновления...
    pip install -r requirements.txt --quiet --upgrade 2>nul
)
echo.

REM Проверка .env файла
if not exist ".env" (
    echo [WARNING] Файл .env не найден!
    echo.
    echo Создаю шаблон .env файла...
    (
        echo # Binance API Keys ^(обязательно для live торговли^)
        echo BINANCE_API_KEY=your_api_key_here
        echo BINANCE_API_SECRET=your_secret_key_here
        echo.
        echo # Telegram Bot ^(опционально^)
        echo TELEGRAM_BOT_TOKEN=your_telegram_bot_token
        echo TELEGRAM_CHAT_ID=your_chat_id
        echo.
        echo # Session Secret
        echo SESSION_SECRET=random_secret_string_here
    ) > .env
    echo.
    echo [ACTION REQUIRED] Откройте файл .env и добавьте ваши API ключи!
    echo.
    pause
)

REM Проверка config.yaml
if not exist "config.yaml" (
    echo [ERROR] Файл config.yaml не найден!
    pause
    exit /b 1
)

REM Создание папки для данных
if not exist "data" mkdir data

echo ============================================================
echo   Запуск бота...
echo ============================================================
echo.

REM Проверка main.py
if not exist "main.py" (
    echo [ERROR] Файл main.py не найден!
    echo Убедитесь что вы находитесь в корневой папке проекта
    pause
    exit /b 1
)

REM Запуск бота (используем python из venv)
venv\Scripts\python.exe main.py

REM Если бот упал
if errorlevel 1 (
    echo.
    echo [ERROR] Бот завершился с ошибкой
    echo Проверьте логи выше для деталей
    pause
)
