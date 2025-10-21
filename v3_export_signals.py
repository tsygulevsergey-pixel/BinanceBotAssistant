#!/usr/bin/env python3
"""
V3 S/R Signal Export - экспорт всех сигналов в JSON
"""

import sqlite3
import json
import os

# Путь к БД относительно корня проекта
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "trading_bot.db")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "v3_signals_export.json")

def export_to_json():
    """Export all V3 S/R signals to JSON file"""
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        print(f"БД: {DB_PATH}")
        
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

if __name__ == "__main__":
    export_to_json()
