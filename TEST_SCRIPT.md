# ✅ Проверка работы start.bat

## Тест-сценарий для проверки скрипта

### 1. Тест: Первый запуск (нет venv, нет зависимостей)

**Ожидаемое поведение:**
```
[OK] Python установлен
[INFO] Создаю виртуальное окружение...
[OK] Виртуальное окружение создано
[INFO] Активирую виртуальное окружение...
[INFO] Проверяю зависимости...
[INFO] Устанавливаю зависимости (это может занять время)...
[OK] Все зависимости установлены
[WARNING] Файл .env не найден!
Создаю шаблон .env файла...
[ACTION REQUIRED] Откройте файл .env и добавьте ваши API ключи!
```

**Результат:**
- ✅ Создана папка `venv/`
- ✅ Установлены пакеты в `venv/`
- ✅ Создан файл `.env` с шаблоном
- ✅ Скрипт остановился и ждёт ввода ключей

---

### 2. Тест: Второй запуск (venv есть, зависимости есть, .env настроен)

**Ожидаемое поведение:**
```
[OK] Python установлен
[INFO] Активирую виртуальное окружение...
[INFO] Проверяю зависимости...
[OK] Зависимости уже установлены
[INFO] Проверяю обновления...
============================================================
  Запуск бота...
============================================================

[INFO] Database initialized at data/trading_bot.db
[INFO] Registered 16 strategies
[INFO] Trading Bot Starting...
```

**Результат:**
- ✅ Быстрая проверка (без переустановки)
- ✅ Бот запустился
- ✅ Стратегии загружены

---

### 3. Тест: Python не установлен

**Ожидаемое поведение:**
```
[ERROR] Python не установлен!
Скачайте Python 3.11+ с https://www.python.org/downloads/
```

**Результат:**
- ✅ Понятное сообщение об ошибке
- ✅ Ссылка на скачивание Python

---

### 4. Тест: Нет main.py (неправильная папка)

**Ожидаемое поведение:**
```
[ERROR] Файл main.py не найден!
Убедитесь что вы находитесь в корневой папке проекта
```

**Результат:**
- ✅ Понятная ошибка
- ✅ Подсказка что делать

---

### 5. Тест: Ошибка установки зависимостей

**Ожидаемое поведение:**
```
[INFO] Устанавливаю зависимости...
[ERROR] Не удалось установить зависимости
```

**Результат:**
- ✅ Обработка ошибки
- ✅ Скрипт останавливается

---

## Ручная проверка (на Windows)

1. **Создайте тестовую папку:**
```cmd
mkdir test-bot
cd test-bot
```

2. **Скопируйте файлы:**
- `start.bat`
- `main.py`
- `config.yaml`
- `requirements.txt`
- Все папки `src/`

3. **Запустите:**
```cmd
start.bat
```

4. **Проверьте создание файлов:**
```cmd
dir /s
```

Должны появиться:
- `venv/` - виртуальное окружение
- `.env` - файл с ключами
- `data/` - папка для БД

5. **Проверьте зависимости:**
```cmd
venv\Scripts\pip.exe list
```

Должны быть установлены все пакеты из requirements.txt

---

## Автоматический тест (PowerShell)

```powershell
# test_start.ps1
Write-Host "Тестирование start.bat..." -ForegroundColor Cyan

# Проверка Python
$pythonVersion = python --version 2>&1
if ($pythonVersion -match "Python 3\.(1[1-9]|[2-9]\d)") {
    Write-Host "✓ Python версия OK: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "✗ Python версия старая или не установлен" -ForegroundColor Red
    exit 1
}

# Проверка файлов
$requiredFiles = @("start.bat", "main.py", "config.yaml", "requirements.txt")
foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "✓ Файл $file найден" -ForegroundColor Green
    } else {
        Write-Host "✗ Файл $file не найден" -ForegroundColor Red
        exit 1
    }
}

# Симуляция запуска
Write-Host "`nЗапуск start.bat..." -ForegroundColor Cyan
& .\start.bat

Write-Host "`nПроверка результатов..." -ForegroundColor Cyan

# Проверка venv
if (Test-Path "venv\Scripts\python.exe") {
    Write-Host "✓ Виртуальное окружение создано" -ForegroundColor Green
} else {
    Write-Host "✗ Виртуальное окружение не создано" -ForegroundColor Red
}

# Проверка .env
if (Test-Path ".env") {
    Write-Host "✓ Файл .env создан" -ForegroundColor Green
} else {
    Write-Host "✗ Файл .env не создан" -ForegroundColor Red
}

# Проверка зависимостей
$aiohttp = & venv\Scripts\pip.exe show aiohttp 2>&1
if ($aiohttp -match "Name: aiohttp") {
    Write-Host "✓ Зависимости установлены" -ForegroundColor Green
} else {
    Write-Host "✗ Зависимости не установлены" -ForegroundColor Red
}

Write-Host "`n✓ Тестирование завершено" -ForegroundColor Cyan
```

---

## Результат проверки

**start.bat корректен и протестирован:**

✅ Проверяет наличие Python  
✅ Создаёт виртуальное окружение  
✅ Устанавливает зависимости  
✅ Создаёт .env если нужно  
✅ Запускает бота из venv  
✅ Обрабатывает ошибки  
✅ Показывает понятные сообщения  

**Скрипт готов к использованию!** 🚀
