#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================================"
echo "  Trading Bot - Автоматический запуск"
echo "============================================================"
echo ""

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} Python не установлен!"
    echo "Установите Python 3.11+ командой:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  MacOS: brew install python@3.11"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Python установлен: $(python3 --version)"
echo ""

# Проверка виртуального окружения
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}[INFO]${NC} Создаю виртуальное окружение..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR]${NC} Не удалось создать виртуальное окружение"
        exit 1
    fi
    echo -e "${GREEN}[OK]${NC} Виртуальное окружение создано"
    echo ""
fi

# Активация виртуального окружения
echo -e "${YELLOW}[INFO]${NC} Активирую виртуальное окружение..."
source venv/bin/activate

# Проверка requirements.txt
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}[ERROR]${NC} Файл requirements.txt не найден!"
    exit 1
fi

# Проверка установленных пакетов
echo -e "${YELLOW}[INFO]${NC} Проверяю зависимости..."
if ! pip show aiohttp &> /dev/null; then
    echo -e "${YELLOW}[INFO]${NC} Устанавливаю зависимости (это может занять время)..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR]${NC} Не удалось установить зависимости"
        exit 1
    fi
    echo -e "${GREEN}[OK]${NC} Все зависимости установлены"
else
    echo -e "${GREEN}[OK]${NC} Зависимости уже установлены"
    
    # Проверяем, нужно ли обновить
    echo -e "${YELLOW}[INFO]${NC} Проверяю обновления..."
    pip install -r requirements.txt --quiet --upgrade 2>/dev/null
fi
echo ""

# Проверка .env файла
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}[WARNING]${NC} Файл .env не найден!"
    echo ""
    echo "Создаю шаблон .env файла..."
    cat > .env << 'EOF'
# Binance API Keys (обязательно для live торговли)
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_secret_key_here

# Telegram Bot (опционально)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Session Secret
SESSION_SECRET=random_secret_string_here
EOF
    echo ""
    echo -e "${YELLOW}[ACTION REQUIRED]${NC} Откройте файл .env и добавьте ваши API ключи!"
    echo ""
    read -p "Нажмите Enter для продолжения..."
fi

# Проверка config.yaml
if [ ! -f "config.yaml" ]; then
    echo -e "${RED}[ERROR]${NC} Файл config.yaml не найден!"
    exit 1
fi

# Создание папки для данных
mkdir -p data

echo "============================================================"
echo "  Запуск бота..."
echo "============================================================"
echo ""

# Проверка main.py
if [ ! -f "main.py" ]; then
    echo -e "${RED}[ERROR]${NC} Файл main.py не найден!"
    echo "Убедитесь что вы находитесь в корневой папке проекта"
    read -p "Нажмите Enter для выхода..."
    exit 1
fi

# Запуск бота (используем python из venv)
venv/bin/python main.py

# Если бот упал
if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}[ERROR]${NC} Бот завершился с ошибкой"
    echo "Проверьте логи выше для деталей"
    read -p "Нажмите Enter для выхода..."
fi
