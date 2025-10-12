#!/usr/bin/env python3
"""
Скрипт для очистки сигналов из базы данных
"""
import sqlite3
import sys

DB_PATH = "data/trading_bot.db"

def clear_all_signals():
    """Удалить все сигналы из БД"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Подсчитать сигналы перед удалением
    cursor.execute("SELECT COUNT(*) FROM signals")
    count_before = cursor.fetchone()[0]
    print(f"📊 Сигналов в БД: {count_before}")
    
    if count_before == 0:
        print("✅ База данных уже пуста")
        conn.close()
        return
    
    # Подтверждение
    response = input(f"\n⚠️  Удалить все {count_before} сигналов? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Отменено")
        conn.close()
        return
    
    # Удаление
    cursor.execute("DELETE FROM signals")
    conn.commit()
    
    # Проверка
    cursor.execute("SELECT COUNT(*) FROM signals")
    count_after = cursor.fetchone()[0]
    
    print(f"✅ Удалено сигналов: {count_before - count_after}")
    print(f"📊 Сигналов осталось: {count_after}")
    
    conn.close()

def clear_by_status(status):
    """Удалить сигналы по статусу"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM signals WHERE status = ?", (status,))
    count_before = cursor.fetchone()[0]
    print(f"📊 Сигналов со статусом '{status}': {count_before}")
    
    if count_before == 0:
        print(f"✅ Нет сигналов со статусом '{status}'")
        conn.close()
        return
    
    response = input(f"\n⚠️  Удалить {count_before} сигналов со статусом '{status}'? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Отменено")
        conn.close()
        return
    
    cursor.execute("DELETE FROM signals WHERE status = ?", (status,))
    conn.commit()
    
    print(f"✅ Удалено сигналов: {count_before}")
    conn.close()

def show_stats():
    """Показать статистику сигналов"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT status, COUNT(*) as count 
        FROM signals 
        GROUP BY status
    """)
    
    stats = cursor.fetchall()
    
    print("\n📊 Статистика сигналов:")
    print("-" * 30)
    total = 0
    for status, count in stats:
        print(f"  {status}: {count}")
        total += count
    print("-" * 30)
    print(f"  ВСЕГО: {total}")
    
    conn.close()

if __name__ == "__main__":
    print("🗑️  Очистка базы данных сигналов")
    print("=" * 40)
    
    show_stats()
    
    print("\nВыберите действие:")
    print("1. Удалить все сигналы")
    print("2. Удалить по статусу (WIN/LOSS/TIME_STOP)")
    print("3. Удалить ACTIVE/PENDING")
    print("4. Показать статистику")
    print("0. Выход")
    
    choice = input("\nВаш выбор: ")
    
    if choice == "1":
        clear_all_signals()
    elif choice == "2":
        status = input("Введите статус (WIN/LOSS/TIME_STOP): ").upper()
        clear_by_status(status)
    elif choice == "3":
        status = input("Введите статус (ACTIVE/PENDING): ").upper()
        clear_by_status(status)
    elif choice == "4":
        show_stats()
    elif choice == "0":
        print("👋 Выход")
    else:
        print("❌ Неверный выбор")
