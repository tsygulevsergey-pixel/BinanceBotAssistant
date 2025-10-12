#!/usr/bin/env python3
"""
Скрипт для очистки сигналов из базы данных
Поддерживает обычные стратегии и Action Price
"""
import sqlite3
import sys

DB_PATH = "data/trading_bot.db"

def clear_all_signals():
    """Удалить ВСЕ сигналы из БД (обычные + Action Price)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Подсчитать сигналы перед удалением
    cursor.execute("SELECT COUNT(*) FROM signals")
    main_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM action_price_signals")
    ap_count = cursor.fetchone()[0]
    
    total = main_count + ap_count
    
    print(f"📊 Сигналов в БД:")
    print(f"   • Основные стратегии: {main_count}")
    print(f"   • Action Price: {ap_count}")
    print(f"   • ВСЕГО: {total}")
    
    if total == 0:
        print("✅ База данных уже пуста")
        conn.close()
        return
    
    # Подтверждение
    response = input(f"\n⚠️  Удалить ВСЕ {total} сигналов? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Отменено")
        conn.close()
        return
    
    # Удаление
    cursor.execute("DELETE FROM signals")
    deleted_main = cursor.rowcount
    
    cursor.execute("DELETE FROM action_price_signals")
    deleted_ap = cursor.rowcount
    
    cursor.execute("DELETE FROM signal_locks")
    
    conn.commit()
    
    print(f"\n✅ Удалено:")
    print(f"   • Основные стратегии: {deleted_main}")
    print(f"   • Action Price: {deleted_ap}")
    print(f"   • ВСЕГО: {deleted_main + deleted_ap}")
    print(f"\n🔓 Все символы разблокированы!")
    
    conn.close()

def clear_by_status(status, signal_type='all'):
    """
    Удалить сигналы по статусу
    
    Args:
        status: статус сигнала (WIN/LOSS/TIME_STOP/ACTIVE/PENDING)
        signal_type: 'main' | 'action_price' | 'all'
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    deleted_main = 0
    deleted_ap = 0
    
    # Подсчет
    if signal_type in ['main', 'all']:
        cursor.execute("SELECT COUNT(*) FROM signals WHERE status = ?", (status,))
        main_count = cursor.fetchone()[0]
    else:
        main_count = 0
    
    if signal_type in ['action_price', 'all']:
        cursor.execute("SELECT COUNT(*) FROM action_price_signals WHERE status = ?", (status,))
        ap_count = cursor.fetchone()[0]
    else:
        ap_count = 0
    
    total = main_count + ap_count
    
    print(f"📊 Сигналов со статусом '{status}':")
    if signal_type in ['main', 'all']:
        print(f"   • Основные стратегии: {main_count}")
    if signal_type in ['action_price', 'all']:
        print(f"   • Action Price: {ap_count}")
    print(f"   • ВСЕГО: {total}")
    
    if total == 0:
        print(f"✅ Нет сигналов со статусом '{status}'")
        conn.close()
        return
    
    response = input(f"\n⚠️  Удалить {total} сигналов? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Отменено")
        conn.close()
        return
    
    # Удаление
    if signal_type in ['main', 'all']:
        cursor.execute("DELETE FROM signals WHERE status = ?", (status,))
        deleted_main = cursor.rowcount
    
    if signal_type in ['action_price', 'all']:
        cursor.execute("DELETE FROM action_price_signals WHERE status = ?", (status,))
        deleted_ap = cursor.rowcount
    
    conn.commit()
    
    print(f"\n✅ Удалено:")
    if signal_type in ['main', 'all']:
        print(f"   • Основные стратегии: {deleted_main}")
    if signal_type in ['action_price', 'all']:
        print(f"   • Action Price: {deleted_ap}")
    print(f"   • ВСЕГО: {deleted_main + deleted_ap}")
    
    conn.close()

def clear_action_price_only():
    """Удалить ТОЛЬКО Action Price сигналы"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM action_price_signals")
    count = cursor.fetchone()[0]
    
    print(f"📊 Action Price сигналов: {count}")
    
    if count == 0:
        print("✅ Нет Action Price сигналов")
        conn.close()
        return
    
    response = input(f"\n⚠️  Удалить все {count} Action Price сигналов? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Отменено")
        conn.close()
        return
    
    cursor.execute("DELETE FROM action_price_signals")
    deleted = cursor.rowcount
    conn.commit()
    
    print(f"✅ Удалено Action Price сигналов: {deleted}")
    conn.close()

def show_stats():
    """Показать детальную статистику сигналов"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n📊 СТАТИСТИКА СИГНАЛОВ")
    print("=" * 50)
    
    # Основные стратегии
    cursor.execute("""
        SELECT status, COUNT(*) as count 
        FROM signals 
        GROUP BY status
    """)
    main_stats = cursor.fetchall()
    
    print("\n🔹 Основные стратегии:")
    print("-" * 30)
    main_total = 0
    if main_stats:
        for status, count in main_stats:
            print(f"  {status}: {count}")
            main_total += count
    else:
        print("  (пусто)")
    print("-" * 30)
    print(f"  ВСЕГО: {main_total}")
    
    # Action Price
    cursor.execute("""
        SELECT status, COUNT(*) as count 
        FROM action_price_signals 
        GROUP BY status
    """)
    ap_stats = cursor.fetchall()
    
    print("\n🎯 Action Price:")
    print("-" * 30)
    ap_total = 0
    if ap_stats:
        for status, count in ap_stats:
            print(f"  {status}: {count}")
            ap_total += count
    else:
        print("  (пусто)")
    print("-" * 30)
    print(f"  ВСЕГО: {ap_total}")
    
    # Общий итог
    print("\n" + "=" * 50)
    print(f"📊 ОБЩИЙ ИТОГ: {main_total + ap_total} сигналов")
    print("=" * 50)
    
    conn.close()

if __name__ == "__main__":
    print("🗑️  ОЧИСТКА БАЗЫ ДАННЫХ СИГНАЛОВ")
    print("=" * 50)
    
    show_stats()
    
    print("\n\nВыберите действие:")
    print("1. Удалить ВСЕ сигналы (обычные + Action Price)")
    print("2. Удалить ТОЛЬКО Action Price сигналы")
    print("3. Удалить по статусу - ВСЕ типы (WIN/LOSS/TIME_STOP)")
    print("4. Удалить по статусу - ТОЛЬКО основные стратегии")
    print("5. Удалить по статусу - ТОЛЬКО Action Price")
    print("6. Удалить ACTIVE/PENDING - освободить символы")
    print("7. Показать статистику")
    print("0. Выход")
    
    choice = input("\nВаш выбор: ")
    
    if choice == "1":
        clear_all_signals()
    elif choice == "2":
        clear_action_price_only()
    elif choice == "3":
        status = input("Введите статус (WIN/LOSS/TIME_STOP): ").upper()
        clear_by_status(status, 'all')
    elif choice == "4":
        status = input("Введите статус (WIN/LOSS/TIME_STOP): ").upper()
        clear_by_status(status, 'main')
    elif choice == "5":
        status = input("Введите статус (WIN/LOSS/TIME_STOP): ").upper()
        clear_by_status(status, 'action_price')
    elif choice == "6":
        status = input("Введите статус (ACTIVE/PENDING): ").upper()
        clear_by_status(status, 'all')
    elif choice == "7":
        show_stats()
    elif choice == "0":
        print("👋 Выход")
    else:
        print("❌ Неверный выбор")
