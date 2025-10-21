#!/usr/bin/env python3
"""
V3 S/R Signal Export - Simple JSON export
Экспортирует ВСЕ сигналы из v3_sr_signals в JSON файл
"""

import sqlite3
import json
from datetime import datetime

DB_PATH = "trading_bot.db"
OUTPUT_FILE = "v3_signals_export.json"

def export_to_json():
    """Export all V3 S/R signals to JSON file"""
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        print("Подключение к базе данных...")
        print(f"Файл БД: {DB_PATH}")
        print()
        
        # Получить все сигналы
        cursor.execute("SELECT * FROM v3_sr_signals ORDER BY created_at DESC")
        rows = cursor.fetchall()
        
        if not rows:
            print("⚠️  Таблица v3_sr_signals пустая или не существует")
            conn.close()
            return
        
        print(f"Найдено сигналов: {len(rows)}")
        print()
        
        # Конвертация в список словарей
        signals = []
        for row in rows:
            signal = dict(row)
            signals.append(signal)
        
        # Сохранение в JSON
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(signals, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"✅ Экспорт завершен!")
        print(f"📁 Файл: {OUTPUT_FILE}")
        print(f"📊 Экспортировано записей: {len(signals)}")
        
        # Статистика
        closed_count = sum(1 for s in signals if s.get('closed_at'))
        active_count = len(signals) - closed_count
        
        print()
        print("Статистика:")
        print(f"  Закрытые: {closed_count}")
        print(f"  Активные: {active_count}")
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"❌ Ошибка БД: {e}")
        print(f"Проверьте что файл {DB_PATH} существует")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("V3 S/R Signal Export → JSON")
    print("=" * 60)
    print()
    export_to_json()
    print()
    input("Нажмите Enter для выхода...")
