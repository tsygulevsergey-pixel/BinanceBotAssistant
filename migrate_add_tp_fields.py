#!/usr/bin/env python3
"""
Миграция: Добавление полей для Trailing Stop-Loss
Добавляет поля tp1_hit, tp1_closed_at, exit_type к таблице signals
"""

import sqlite3
from pathlib import Path
from src.utils.config import config

def check_column_exists(cursor, table_name, column_name):
    """Проверить существование колонки в таблице"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def migrate():
    db_path = config.database_path
    
    if not Path(db_path).exists():
        print(f"❌ База данных не найдена: {db_path}")
        return
    
    print(f"🔄 Подключение к базе данных: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем и добавляем поле tp1_hit
        if not check_column_exists(cursor, 'signals', 'tp1_hit'):
            print("  ➕ Добавление поля 'tp1_hit'...")
            cursor.execute("ALTER TABLE signals ADD COLUMN tp1_hit BOOLEAN DEFAULT 0")
            print("  ✅ Поле 'tp1_hit' добавлено (default: False)")
        else:
            print("  ⏭️  Поле 'tp1_hit' уже существует")
        
        # Проверяем и добавляем поле tp1_closed_at
        if not check_column_exists(cursor, 'signals', 'tp1_closed_at'):
            print("  ➕ Добавление поля 'tp1_closed_at'...")
            cursor.execute("ALTER TABLE signals ADD COLUMN tp1_closed_at DATETIME")
            print("  ✅ Поле 'tp1_closed_at' добавлено (default: NULL)")
        else:
            print("  ⏭️  Поле 'tp1_closed_at' уже существует")
        
        # Проверяем и добавляем поле exit_type
        if not check_column_exists(cursor, 'signals', 'exit_type'):
            print("  ➕ Добавление поля 'exit_type'...")
            cursor.execute("ALTER TABLE signals ADD COLUMN exit_type VARCHAR(20)")
            print("  ✅ Поле 'exit_type' добавлено (default: NULL)")
        else:
            print("  ⏭️  Поле 'exit_type' уже существует")
        
        conn.commit()
        print("\n✅ Миграция успешно завершена!")
        print(f"📊 База данных обновлена: {db_path}")
        
        # Показать статистику
        cursor.execute("SELECT COUNT(*) FROM signals")
        total_signals = cursor.fetchone()[0]
        print(f"📈 Всего сигналов в базе: {total_signals}")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Ошибка миграции: {e}")
        raise
    
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("  МИГРАЦИЯ: Добавление полей Trailing Stop-Loss")
    print("=" * 60)
    migrate()
    print("=" * 60)
