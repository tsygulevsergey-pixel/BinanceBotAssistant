# 🌐 Telegram Proxy Setup

## Проблема
```
telegram.error.NetworkError: httpx.ReadError
```

Telegram API заблокирован в вашей стране/провайдером.

---

## ✅ РЕШЕНИЯ

### **1. Бесплатный VPN (ПРОСТОЕ)**

Установите **бесплатный VPN** на компьютер:

**Рекомендуемые:**
- **Cloudflare WARP** - https://1.1.1.1/ (бесплатный, быстрый)
- **ProtonVPN** - https://protonvpn.com/ (бесплатный, безлимит)
- **Windscribe** - https://windscribe.com/ (10GB/месяц бесплатно)

**Как использовать:**
1. Установите VPN
2. Подключитесь к серверу (США, Германия, Нидерланды)
3. Запустите бота: `python main.py`

---

### **2. Proxy в .env (ПРОДВИНУТОЕ)**

Если у вас есть HTTP/SOCKS5 proxy сервер:

**Шаг 1: Добавьте в `.env` файл:**

```env
# Telegram Proxy (опционально)
# Формат: http://user:pass@host:port или socks5://user:pass@host:port

TELEGRAM_PROXY_URL=http://proxy.example.com:8080
```

**Примеры proxy:**

```env
# HTTP proxy без авторизации
TELEGRAM_PROXY_URL=http://proxy.example.com:8080

# HTTP proxy с авторизацией
TELEGRAM_PROXY_URL=http://username:password@proxy.example.com:8080

# SOCKS5 proxy
TELEGRAM_PROXY_URL=socks5://127.0.0.1:1080
```

**Шаг 2: Запустите бота**

```bash
python main.py
```

Бот автоматически использует proxy если `TELEGRAM_PROXY_URL` указан.

---

### **3. Бесплатные Proxy Сервисы**

Если нужен бесплатный proxy:

**HTTP Proxy:**
- https://www.freeproxylists.net/
- https://hidemy.name/ru/proxy-list/

**SOCKS5 Proxy:**
- https://www.socks-proxy.net/

⚠️ **Внимание:** Бесплатные proxy могут быть медленными и ненадёжными.

---

## 🧪 ПРОВЕРКА

### **Проверьте доступ к Telegram API:**

```bash
# Windows CMD
ping api.telegram.org

# Если не пингуется - блокировка активна
```

### **Проверьте работу бота:**

После настройки proxy/VPN запустите:

```bash
python main.py
```

Вы должны увидеть:
```
INFO - 🌐 Using proxy for Telegram: http://...
INFO - Telegram bot started with polling
```

---

## ❓ FAQ

**Q: Бот всё ещё не подключается?**
A: 
1. Проверьте правильность proxy URL
2. Убедитесь что proxy работает (пингуется)
3. Попробуйте другой proxy сервер
4. Используйте VPN вместо proxy

**Q: Какой способ лучше?**
A:
- **Простой:** Cloudflare WARP (один клик, бесплатно)
- **Надёжный:** ProtonVPN (безлимит, стабильно)
- **Продвинутый:** Свой proxy сервер (полный контроль)

**Q: Proxy влияет на Binance API?**
A: **НЕТ**, proxy используется только для Telegram. Binance API работает напрямую.

---

## 🛠️ Технические детали

Бот использует `httpx` с proxy support:

```python
# src/telegram/bot.py
if proxy_url:
    http_client = AsyncClient(proxy=proxy_url, timeout=30.0)
    builder.request(telegram.request.HTTPXRequest(client=http_client))
```

Поддерживаемые протоколы:
- HTTP/HTTPS proxy
- SOCKS5 proxy
- SOCKS4 proxy (через socks5h://)

---

## 📞 Поддержка

Если проблема сохраняется:

1. Проверьте логи бота на ошибки
2. Попробуйте другой proxy/VPN
3. Убедитесь что `TELEGRAM_BOT_TOKEN` правильный
4. Проверьте интернет соединение

---

**Готово!** 🎉 Бот теперь работает даже при блокировке Telegram.
