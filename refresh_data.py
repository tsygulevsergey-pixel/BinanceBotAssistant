"""
Скрипт для обновления данных в БД за последние N дней
Исправляет проблему незакрытых свечей

Запуск:
    python refresh_data.py              # обновить все символы за 10 дней
    python refresh_data.py NMRUSDT      # обновить конкретный символ за 10 дней
    python refresh_data.py NMRUSDT 7    # обновить конкретный символ за 7 дней
"""
import asyncio
import sys
from src.binance.client import BinanceClient
from src.binance.data_loader import DataLoader
from src.utils.config import config
from src.database.db import db
from src.database.models import Candle
from src.utils.logger import logger


async def refresh_data(symbol: str = None, days: int = 10):
    """Обновить данные в БД"""
    
    # Инициализация (BinanceClient берёт ключи из config автоматически)
    binance_client = BinanceClient()
    
    # Создать aiohttp session для запросов
    await binance_client.__aenter__()
    
    try:
        data_loader = DataLoader(binance_client)
        
        print(f"\n{'='*80}")
        print(f"🔄 ОБНОВЛЕНИЕ ДАННЫХ В БД")
        print(f"{'='*80}\n")
        
        if symbol:
            # Обновить один символ
            symbols = [symbol.upper()]
            print(f"📊 Символ: {symbol.upper()}")
        else:
            # Получить все символы из БД
            session = db.get_session()
            try:
                result = session.query(Candle.symbol).distinct().all()
                symbols = [row[0] for row in result]
                print(f"📊 Всего символов в БД: {len(symbols)}")
            finally:
                session.close()
        
        print(f"📅 Обновление за последние {days} дней")
        print(f"\n{'-'*80}\n")
        
        # Обновить данные
        total = len(symbols)
        for idx, sym in enumerate(symbols, 1):
            try:
                # Проверить rate limit перед обновлением
                rate_status = binance_client.get_rate_limit_status()
                usage_percent = (rate_status['current'] / rate_status['limit']) * 100
                
                print(f"[{idx}/{total}] 🔄 {sym}... (Rate: {rate_status['current']}/{rate_status['limit']} = {usage_percent:.1f}%)")
                
                # Если использование > 80%, подождать
                if usage_percent > 80:
                    wait_time = 5
                    print(f"   ⚠️  Rate limit {usage_percent:.1f}% - пауза {wait_time}s...")
                    await asyncio.sleep(wait_time)
                
                await data_loader.refresh_recent_candles(sym, days=days)
                print(f"[{idx}/{total}] ✅ {sym} - ГОТОВО\n")
                
                # Небольшая задержка между символами (0.5s)
                if idx < total:
                    await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"[{idx}/{total}] ❌ {sym} - ОШИБКА: {e}\n")
                logger.error(f"Error refreshing {sym}: {e}")
                
                # Если ошибка rate limit - увеличить задержку
                if "rate limit" in str(e).lower() or "429" in str(e):
                    print(f"   ⚠️  Rate limit error - пауза 10s...")
                    await asyncio.sleep(10)
        
        print(f"\n{'='*80}")
        print(f"✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО")
        print(f"{'='*80}\n")
        
        print("💡 Рекомендация:")
        print("   1. Перезапустите бота для применения обновлённых данных")
        print("   2. Проверьте логи на наличие ошибок")
        print("   3. Запустите check_db_data.py для проверки данных")
        print()
    
    finally:
        # Закрыть сессию Binance
        await binance_client.__aexit__(None, None, None)


async def main():
    """Main entry point"""
    symbol = None
    days = 10
    
    # Парсинг аргументов
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
    
    if len(sys.argv) > 2:
        try:
            days = int(sys.argv[2])
        except ValueError:
            print(f"❌ Неверное количество дней: {sys.argv[2]}")
            print("   Использование: python refresh_data.py [SYMBOL] [DAYS]")
            print("   Пример: python refresh_data.py NMRUSDT 7")
            return
    
    await refresh_data(symbol, days)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Обновление прервано пользователем")
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
