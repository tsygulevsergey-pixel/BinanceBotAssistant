"""
Скрипт для исправления exit_type старых breakeven сделок
"""
import sqlite3

# Подключение к базе
conn = sqlite3.connect('./data/trading_bot.db')
cursor = conn.cursor()

# Найти все сделки с exit_type='TP1' и pnl_percent=0
cursor.execute('''
    SELECT id, symbol, direction, exit_type, pnl_percent, exit_price, entry_price
    FROM signals
    WHERE exit_type = 'TP1' 
      AND pnl_percent = 0.0
      AND exit_price = entry_price
''')

old_records = cursor.fetchall()

if not old_records:
    print("✅ Нет записей для исправления")
else:
    print(f"🔍 Найдено {len(old_records)} записей для исправления:\n")
    for record in old_records:
        print(f"  ID {record[0]}: {record[1]} {record[2]} | TP1 → BREAKEVEN")
    
    # Спросить подтверждение
    answer = input(f"\n❓ Исправить эти {len(old_records)} записи? (y/n): ")
    
    if answer.lower() == 'y':
        # Исправить exit_type на BREAKEVEN
        cursor.execute('''
            UPDATE signals
            SET exit_type = 'BREAKEVEN'
            WHERE exit_type = 'TP1' 
              AND pnl_percent = 0.0
              AND exit_price = entry_price
        ''')
        
        conn.commit()
        print(f"\n✅ Исправлено {cursor.rowcount} записей!")
        print("📊 Теперь в статистике будет показываться правильно")
    else:
        print("\n❌ Отменено")

conn.close()
