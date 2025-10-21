#!/usr/bin/env python3
"""
Скрипт для удаления всех V3 S/R сигналов и блокировок из базы данных
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = "data/trading_bot.db"

def cleanup_v3_data():
    """Удаляет все V3 S/R данные из базы"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ База данных не найдена: {DB_PATH}")
        print(f"   Проверьте путь к БД")
        return
    
    print("=" * 80)
    print("🗑️  CLEANUP V3 S/R DATA")
    print("=" * 80)
    print()
    print(f"📂 База данных: {DB_PATH}")
    print()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("📊 ТЕКУЩЕЕ СОСТОЯНИЕ:")
        print("-" * 80)
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals")
        signals_count = cursor.fetchone()[0]
        print(f"   v3_sr_signals:      {signals_count:,} записей")
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signal_locks")
        locks_count = cursor.fetchone()[0]
        print(f"   v3_sr_signal_locks: {locks_count:,} записей")
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_zone_events")
        events_count = cursor.fetchone()[0]
        print(f"   v3_sr_zone_events:  {events_count:,} записей")
        
        print()
        print("-" * 80)
        print()
        
        total = signals_count + locks_count + events_count
        
        if total == 0:
            print("✅ База уже пустая - нечего удалять!")
            return
        
        print(f"⚠️  БУДЕТ УДАЛЕНО: {total:,} записей")
        print()
        
        confirmation = input("🔴 Вы уверены? Введите 'yes' для подтверждения: ")
        print()
        
        if confirmation.lower() != 'yes':
            print("❌ Отмена операции")
            return
        
        print("🔄 Удаление данных...")
        print()
        
        cursor.execute("DELETE FROM v3_sr_zone_events")
        deleted_events = cursor.rowcount
        print(f"   ✅ v3_sr_zone_events:  удалено {deleted_events:,} записей")
        
        cursor.execute("DELETE FROM v3_sr_signals")
        deleted_signals = cursor.rowcount
        print(f"   ✅ v3_sr_signals:      удалено {deleted_signals:,} записей")
        
        cursor.execute("DELETE FROM v3_sr_signal_locks")
        deleted_locks = cursor.rowcount
        print(f"   ✅ v3_sr_signal_locks: удалено {deleted_locks:,} записей")
        
        conn.commit()
        
        print()
        print("🔧 Оптимизация базы данных...")
        cursor.execute("VACUUM")
        conn.commit()
        
        print()
        print("=" * 80)
        print("✅ ГОТОВО!")
        print("=" * 80)
        print()
        print(f"📊 Всего удалено: {deleted_signals + deleted_locks + deleted_events:,} записей")
        print(f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        print("💡 Теперь можно запустить бота - он начнет с чистого листа")
        print()
        
    except sqlite3.Error as e:
        print(f"❌ ОШИБКА БД: {e}")
        conn.rollback()
        
    finally:
        conn.close()


def show_current_stats():
    """Показывает текущую статистику без удаления"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ База данных не найдена: {DB_PATH}")
        return
    
    print("=" * 80)
    print("📊 V3 S/R СТАТИСТИКА")
    print("=" * 80)
    print()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals")
        signals_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals WHERE exit_type IS NOT NULL")
        closed_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signal_locks")
        locks_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_zone_events")
        events_count = cursor.fetchone()[0]
        
        print(f"📈 Сигналы:")
        print(f"   Всего:    {signals_count:,}")
        print(f"   Закрыто:  {closed_count:,}")
        print(f"   Активных: {signals_count - closed_count:,}")
        print()
        print(f"🔒 Блокировки: {locks_count:,}")
        print(f"📝 События:    {events_count:,}")
        print()
        
    except sqlite3.Error as e:
        print(f"❌ ОШИБКА: {e}")
        
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        show_current_stats()
    else:
        cleanup_v3_data()
