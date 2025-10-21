#!/usr/bin/env python3
"""
V3 S/R Signal Export - экспорт всех сигналов в JSON
"""

import sqlite3
import json
import os

# Путь к БД - ЯВНО прописываем data/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "data", "trading_bot.db")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "v3_signals_export.json")

def export_to_json():
    """Export all V3 S/R signals to JSON file"""
    
    print(f"Script dir: {SCRIPT_DIR}")
    print(f"БД: {DB_PATH}")
    print(f"Проверка существования БД: {os.path.exists(DB_PATH)}")
    print()
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Файл БД не найден: {DB_PATH}")
        print("Проверьте что БД находится в папке data/")
        return
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM v3_sr_signals ORDER BY created_at DESC")
        rows = cursor.fetchall()
        
        if not rows:
            print("⚠️  Нет данных в v3_sr_signals")
            conn.close()
            return
        
        print(f"Найдено: {len(rows)} сигналов")
        
        signals = [dict(row) for row in rows]
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(signals, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"✅ Экспорт: {OUTPUT_FILE}")
        print(f"📊 Записей: {len(signals)}")
        
        closed = sum(1 for s in signals if s.get('closed_at'))
        print(f"Закрыто: {closed}, Активно: {len(signals) - closed}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    export_to_json()
