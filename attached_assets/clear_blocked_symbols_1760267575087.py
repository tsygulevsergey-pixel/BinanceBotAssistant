#!/usr/bin/env python3
"""
Скрипт для очистки заблокированных символов
Удаляет все активные сигналы из БД, разблокируя символы
"""

import sqlite3
from datetime import datetime

DB_PATH = "data/trading_bot.db"

def clear_active_signals():
    """Очистить все активные сигналы из БД"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Посчитать активные сигналы
        cursor.execute("SELECT COUNT(*) FROM signals WHERE status IN ('ACTIVE', 'PENDING')")
        main_signals = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM action_price_signals WHERE status IN ('ACTIVE', 'PENDING')")
        ap_signals = cursor.fetchone()[0]
        
        total = main_signals + ap_signals
        
        if total == 0:
            print("✅ Нет активных сигналов - все символы уже разблокированы")
            return
        
        print(f"📊 Найдено активных сигналов:")
        print(f"   • Основные стратегии: {main_signals}")
        print(f"   • Action Price: {ap_signals}")
        print(f"   • Всего: {total}")
        
        # Подтверждение
        answer = input("\n❓ Удалить все активные сигналы? (y/n): ")
        if answer.lower() != 'y':
            print("❌ Отменено")
            return
        
        # Удалить активные сигналы
        cursor.execute("DELETE FROM signals WHERE status IN ('ACTIVE', 'PENDING')")
        deleted_main = cursor.rowcount
        
        cursor.execute("DELETE FROM action_price_signals WHERE status IN ('ACTIVE', 'PENDING')")
        deleted_ap = cursor.rowcount
        
        conn.commit()
        
        print(f"\n✅ Удалено:")
        print(f"   • Основные стратегии: {deleted_main}")
        print(f"   • Action Price: {deleted_ap}")
        print(f"   • Всего: {deleted_main + deleted_ap}")
        print("\n🔓 Все символы разблокированы! Перезапустите бота.")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("🧹 Скрипт очистки заблокированных символов\n")
    clear_active_signals()
