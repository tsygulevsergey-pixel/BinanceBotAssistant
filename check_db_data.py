"""
Скрипт для проверки данных в БД
Запуск: python check_db_data.py
"""
import sqlite3
from datetime import datetime

# Путь к БД
DB_PATH = 'data/trading_bot.db'

def check_candles_data(symbol='NMRUSDT', timeframe='15m'):
    """Проверка данных свечей в БД"""
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"\n{'='*80}")
    print(f"ПРОВЕРКА ДАННЫХ: {symbol} {timeframe}")
    print(f"{'='*80}\n")
    
    # 1. Количество свечей
    print("1️⃣ КОЛИЧЕСТВО СВЕЧЕЙ:")
    cursor.execute("""
        SELECT COUNT(*) as total_candles 
        FROM candles 
        WHERE symbol = ? AND timeframe = ?
    """, (symbol, timeframe))
    result = cursor.fetchone()
    total_candles = result[0] if result else 0
    print(f"   Всего свечей: {total_candles}")
    
    if total_candles < 200:
        print(f"   ⚠️  ПРЕДУПРЕЖДЕНИЕ: Меньше 200 свечей! EMA200 будет неточной.")
    else:
        print(f"   ✅ Достаточно для EMA200 (минимум 200)")
    
    # 2. Диапазон дат
    print(f"\n2️⃣ ДИАПАЗОН ДАТ:")
    cursor.execute("""
        SELECT 
            MIN(open_time) as oldest_candle,
            MAX(open_time) as newest_candle
        FROM candles 
        WHERE symbol = ? AND timeframe = ?
    """, (symbol, timeframe))
    result = cursor.fetchone()
    
    if result and result[0]:
        oldest = datetime.fromisoformat(result[0].replace('Z', '+00:00'))
        newest = datetime.fromisoformat(result[1].replace('Z', '+00:00'))
        print(f"   Самая старая: {oldest.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Самая новая:  {newest.strftime('%Y-%m-%d %H:%M:%S')}")
        
        days_diff = (newest - oldest).days
        print(f"   Период: {days_diff} дней")
    else:
        print("   ❌ Нет данных!")
        conn.close()
        return
    
    # 3. Проверка на пробелы
    print(f"\n3️⃣ ПРОВЕРКА ПРОБЕЛОВ (пропущенные свечи):")
    
    # Получить все timestamp и проверить разницу
    cursor.execute("""
        SELECT open_time
        FROM candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time
    """, (symbol, timeframe))
    
    timestamps = [row[0] for row in cursor.fetchall()]
    
    gaps_found = 0
    max_gap_minutes = 0
    gap_details = []
    
    for i in range(1, len(timestamps)):
        prev_time = datetime.fromisoformat(timestamps[i-1].replace('Z', '+00:00'))
        curr_time = datetime.fromisoformat(timestamps[i].replace('Z', '+00:00'))
        
        diff_minutes = (curr_time - prev_time).total_seconds() / 60
        
        if diff_minutes > 15:
            gaps_found += 1
            max_gap_minutes = max(max_gap_minutes, diff_minutes)
            
            if len(gap_details) < 5:  # Показать первые 5 пробелов
                gap_details.append({
                    'from': prev_time,
                    'to': curr_time,
                    'minutes': int(diff_minutes),
                    'missing_candles': int((diff_minutes - 15) / 15)
                })
    
    if gaps_found == 0:
        print(f"   ✅ Пробелов не найдено! Данные целостные.")
    else:
        print(f"   ⚠️  Найдено пробелов: {gaps_found}")
        print(f"   Максимальный пробел: {int(max_gap_minutes)} минут ({int(max_gap_minutes/60)} часов)")
        
        if gap_details:
            print(f"\n   Примеры пробелов (первые 5):")
            for idx, gap in enumerate(gap_details, 1):
                print(f"   {idx}. {gap['from'].strftime('%Y-%m-%d %H:%M')} → "
                      f"{gap['to'].strftime('%Y-%m-%d %H:%M')} "
                      f"({gap['minutes']} мин, пропущено {gap['missing_candles']} свечей)")
    
    # 4. Последние 5 свечей
    print(f"\n4️⃣ ПОСЛЕДНИЕ 5 СВЕЧЕЙ:")
    cursor.execute("""
        SELECT open_time, open, high, low, close, volume
        FROM candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time DESC
        LIMIT 5
    """, (symbol, timeframe))
    
    candles = cursor.fetchall()
    print(f"   {'Время':<20} {'Open':<12} {'High':<12} {'Low':<12} {'Close':<12} {'Volume':<15}")
    print(f"   {'-'*83}")
    
    for candle in candles:
        time_str = datetime.fromisoformat(candle[0].replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M')
        print(f"   {time_str:<20} {candle[1]:<12.5f} {candle[2]:<12.5f} {candle[3]:<12.5f} {candle[4]:<12.5f} {candle[5]:<15.2f}")
    
    # 5. Статистика по символам
    print(f"\n5️⃣ СТАТИСТИКА ПО ВСЕМ СИМВОЛАМ ({timeframe}):")
    cursor.execute("""
        SELECT symbol, COUNT(*) as count
        FROM candles
        WHERE timeframe = ?
        GROUP BY symbol
        ORDER BY count DESC
        LIMIT 10
    """, (timeframe,))
    
    symbols = cursor.fetchall()
    print(f"   {'Символ':<15} {'Свечей':<10}")
    print(f"   {'-'*25}")
    for sym in symbols:
        status = '✅' if sym[1] >= 200 else '⚠️'
        print(f"   {sym[0]:<15} {sym[1]:<10} {status}")
    
    conn.close()
    
    print(f"\n{'='*80}\n")
    
    # Итоговый вывод
    print("📊 ИТОГОВАЯ ДИАГНОСТИКА:")
    
    if total_candles < 200:
        print("   ❌ КРИТИЧНО: Недостаточно данных для точного EMA200")
        print("   → Запустите бота для загрузки исторических данных")
    elif gaps_found > 0:
        print("   ⚠️  ВНИМАНИЕ: Есть пробелы в данных - EMA200 может быть неточной")
        print("   → Проверьте логи DataLoader на ошибки загрузки")
    else:
        print("   ✅ Данные в норме! EMA200 должна быть точной")
        print("   → Расхождение с Binance может быть в методе расчета pandas-ta")
    
    print()

if __name__ == '__main__':
    import sys
    
    # Можно передать символ и таймфрейм как аргументы
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'NMRUSDT'
    timeframe = sys.argv[2] if len(sys.argv) > 2 else '15m'
    
    try:
        check_candles_data(symbol, timeframe)
    except sqlite3.OperationalError as e:
        print(f"\n❌ ОШИБКА: Не могу открыть БД '{DB_PATH}'")
        print(f"   {e}")
        print(f"\n💡 Убедитесь что:")
        print(f"   1. Файл БД существует в текущей директории")
        print(f"   2. Путь к БД правильный (сейчас: {DB_PATH})")
        print()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
