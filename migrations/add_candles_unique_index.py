"""
Безопасная миграция: Добавление уникального индекса на свечи
- Проверяет наличие дубликатов
- Удаляет дубликаты (оставляя последнюю запись)
- Создаёт уникальный индекс для предотвращения дубликатов

Запустите этот скрипт ПОСЛЕ остановки бота!
"""
import sqlite3
import os
import sys

def check_duplicates(cursor):
    """Проверяет наличие дубликатов в таблице candles"""
    cursor.execute("""
        SELECT symbol, timeframe, open_time, COUNT(*) as cnt
        FROM candles
        GROUP BY symbol, timeframe, open_time
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 10
    """)
    
    duplicates = cursor.fetchall()
    return duplicates

def count_total_duplicates(cursor):
    """Подсчитывает общее количество дубликатов"""
    cursor.execute("""
        SELECT COUNT(*) as dup_groups, SUM(cnt - 1) as dup_records
        FROM (
            SELECT COUNT(*) as cnt
            FROM candles
            GROUP BY symbol, timeframe, open_time
            HAVING COUNT(*) > 1
        )
    """)
    
    result = cursor.fetchone()
    return result if result else (0, 0)

def remove_duplicates(cursor):
    """Удаляет дубликаты, оставляя запись с максимальным ID (самую свежую)"""
    cursor.execute("""
        DELETE FROM candles
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM candles
            GROUP BY symbol, timeframe, open_time
        )
    """)
    
    return cursor.rowcount

def create_unique_index(cursor):
    """Создаёт уникальный индекс на (symbol, timeframe, open_time)"""
    try:
        # Сначала удаляем старый индекс если он есть
        cursor.execute("DROP INDEX IF EXISTS idx_candles_symbol_timeframe_time")
        
        # Создаём новый уникальный индекс
        cursor.execute("""
            CREATE UNIQUE INDEX idx_candles_symbol_timeframe_time 
            ON candles (symbol, timeframe, open_time)
        """)
        
        return True
    except sqlite3.Error as e:
        print(f"❌ Ошибка при создании индекса: {e}")
        return False

def apply_migration():
    db_path = "data/trading_bot.db"
    
    # Проверяем наличие базы данных
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена: {db_path}")
        print("   Сначала запустите бота хотя бы раз!")
        return False
    
    print("=" * 70)
    print("🔧 МИГРАЦИЯ: Добавление уникального индекса на свечи")
    print("=" * 70)
    print()
    
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        
        # ШАГ 1: Проверяем дубликаты
        print("📊 ШАГ 1: Проверка дубликатов...")
        print()
        
        dup_groups, dup_records = count_total_duplicates(cursor)
        
        if dup_groups == 0:
            print("✅ Дубликатов не найдено! База данных в идеальном состоянии.")
            print()
        else:
            print(f"⚠️  Найдено дубликатов:")
            print(f"   • Групп дубликатов: {dup_groups}")
            print(f"   • Записей для удаления: {dup_records}")
            print()
            
            # Показываем примеры
            duplicates = check_duplicates(cursor)
            print("   Примеры дубликатов (топ-10):")
            for symbol, timeframe, open_time, count in duplicates[:5]:
                print(f"   • {symbol} {timeframe} {open_time}: {count} копий")
            print()
            
            # ШАГ 2: Удаляем дубликаты
            print("🧹 ШАГ 2: Удаление дубликатов...")
            print("   Оставляем только самую свежую запись из каждой группы...")
            print()
            
            deleted_count = remove_duplicates(cursor)
            
            print(f"✅ Удалено записей: {deleted_count}")
            print()
            
            # Проверяем что дубликаты удалены
            dup_groups_after, _ = count_total_duplicates(cursor)
            if dup_groups_after == 0:
                print("✅ Все дубликаты успешно удалены!")
                print()
            else:
                print(f"⚠️  Осталось дубликатов: {dup_groups_after}")
                print("   Повторите миграцию или свяжитесь с поддержкой.")
                return False
        
        # ШАГ 3: Создаём уникальный индекс
        print("🔒 ШАГ 3: Создание уникального индекса...")
        print()
        
        if create_unique_index(cursor):
            print("✅ Уникальный индекс успешно создан!")
            print()
        else:
            print("❌ Не удалось создать уникальный индекс")
            return False
        
        # Сохраняем изменения
        conn.commit()
        
        # Финальная проверка
        print("=" * 70)
        print("✅ МИГРАЦИЯ УСПЕШНО ПРИМЕНЕНА!")
        print("=" * 70)
        print()
        print("Что изменилось:")
        print("  ✓ Удалены дубликаты свечей")
        print("  ✓ Создан уникальный индекс (symbol, timeframe, open_time)")
        print("  ✓ Теперь база данных не позволит сохранить дубликаты")
        print()
        print("Следующий шаг:")
        print("  → Запустите бота - он будет работать БЫСТРЕЕ!")
        print()
        
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Ошибка базы данных: {e}")
        return False
    except Exception as e:
        print(f"❌ Непредвиденная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print()
    print("⚠️  ВАЖНО: Перед запуском убедитесь что бот остановлен!")
    print()
    
    # Спрашиваем подтверждение
    response = input("Продолжить миграцию? (yes/no): ").lower().strip()
    
    if response in ['yes', 'y', 'да', 'д']:
        success = apply_migration()
        sys.exit(0 if success else 1)
    else:
        print("❌ Миграция отменена пользователем")
        sys.exit(1)
