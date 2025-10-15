"""
Скрипт для экспорта сигналов основных стратегий из базы данных
"""
import sqlite3
import json
from datetime import datetime
import os

def export_signals():
    db_path = 'data/trading_bot.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Ошибка: База данных не найдена: {db_path}")
        return
    
    try:
        # Подключаемся к базе
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Получаем все сигналы основных стратегий (не Action Price)
        print("📊 Экспортирую сигналы из базы данных...")
        cursor.execute('''
            SELECT * FROM signals 
            WHERE strategy_name != 'ActionPrice'
            ORDER BY created_at DESC
        ''')
        
        signals = []
        for row in cursor.fetchall():
            signal_dict = dict(row)
            signals.append(signal_dict)
        
        # Сохраняем в JSON файл
        output_file = 'main_strategies_export.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(signals, f, indent=2, ensure_ascii=False, default=str)
        
        print(f'\n✅ Экспортировано {len(signals)} сигналов')
        print(f'📁 Файл сохранён: {output_file}')
        
        # Статистика по стратегиям
        if signals:
            print("\n📈 Статистика по стратегиям:")
            strategies = {}
            for sig in signals:
                strat = sig.get('strategy_name', 'Unknown')
                strategies[strat] = strategies.get(strat, 0) + 1
            
            for strat, count in sorted(strategies.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {strat}: {count} сигналов")
            
            # Период данных
            first_date = signals[-1].get('created_at', 'N/A')
            last_date = signals[0].get('created_at', 'N/A')
            print(f"\n📅 Период данных:")
            print(f"  Первый сигнал: {first_date}")
            print(f"  Последний сигнал: {last_date}")
        else:
            print("\n⚠️ Сигналов не найдено в базе данных")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка при экспорте: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    export_signals()
