@echo off
echo ============================================================
echo   Trading Bot - Auto Start
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed!
    echo Download Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python is installed
echo.

REM Check virtual environment
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
    echo.
)

REM Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

REM Check requirements.txt
if not exist "requirements.txt" (
    echo [ERROR] File requirements.txt not found!
    pause
    exit /b 1
)

REM Check installed packages
echo [INFO] Checking dependencies...
pip show aiohttp >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing dependencies (this may take a while)...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [OK] All dependencies installed
) else (
    echo [OK] Dependencies already installed
    
    REM Check for updates
    echo [INFO] Checking for updates...
    pip install -r requirements.txt --quiet --upgrade 2>nul
)
echo.

REM Check .env file
if not exist ".env" (
    echo [WARNING] File .env not found!
    echo.
    echo Creating .env template...
    (
        echo # Binance API Keys ^(required for live trading^)
        echo BINANCE_API_KEY=your_api_key_here
        echo BINANCE_API_SECRET=your_secret_key_here
        echo.
        echo # Telegram Bot ^(optional^)
        echo TELEGRAM_BOT_TOKEN=your_telegram_bot_token
        echo TELEGRAM_CHAT_ID=your_chat_id
        echo.
        echo # Session Secret
        echo SESSION_SECRET=random_secret_string_here
    ) > .env
    echo.
    echo [ACTION REQUIRED] Open .env file and add your API keys!
    echo.
    pause
)

REM Check config.yaml
if not exist "config.yaml" (
    echo [ERROR] File config.yaml not found!
    pause
    exit /b 1
)

REM Create data folder
if not exist "data" mkdir data

REM Check main.py
if not exist "main.py" (
    echo [ERROR] File main.py not found!
    echo Make sure you are in the project root folder
    pause
    exit /b 1
)

echo ============================================================
echo   Starting bot...
echo ============================================================
echo.

REM Start bot (using python from venv)
venv\Scripts\python.exe main.py

REM If bot crashed
if errorlevel 1 (
    echo.
    echo [ERROR] Bot terminated with error
    echo Check logs above for details
    pause
)
