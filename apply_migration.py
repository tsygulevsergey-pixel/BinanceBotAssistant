"""
Скрипт для применения миграции профессиональных полей к базе данных.
Запустите этот скрипт ПОСЛЕ остановки бота!
"""
import sqlite3
import os
import sys

def apply_migration():
    db_path = "data/trading_bot.db"
    
    # Проверяем наличие базы данных
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена: {db_path}")
        print("   Сначала запустите бота хотя бы раз!")
        return False
    
    print("=" * 60)
    print("🔧 ПРИМЕНЕНИЕ МИГРАЦИИ ПРОФЕССИОНАЛЬНЫХ ПОЛЕЙ")
    print("=" * 60)
    print()
    
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        
        # Проверяем существующие поля
        cursor.execute("PRAGMA table_info(signals)")
        existing_columns = {col[1] for col in cursor.fetchall()}
        
        print(f"📊 Текущее состояние базы: {len(existing_columns)} полей")
        print()
        
        # Список всех новых полей из миграции
        new_fields = [
            ("context_timeframe", "ALTER TABLE signals ADD COLUMN context_timeframe VARCHAR(10)"),
            ("signal_timeframe", "ALTER TABLE signals ADD COLUMN signal_timeframe VARCHAR(10)"),
            ("confirmation_timeframe", "ALTER TABLE signals ADD COLUMN confirmation_timeframe VARCHAR(10)"),
            ("confluence_count", "ALTER TABLE signals ADD COLUMN confluence_count INTEGER DEFAULT 1"),
            ("confluence_strategies", "ALTER TABLE signals ADD COLUMN confluence_strategies TEXT"),
            ("confluence_bonus", "ALTER TABLE signals ADD COLUMN confluence_bonus FLOAT DEFAULT 0.0"),
            ("sl_type", "ALTER TABLE signals ADD COLUMN sl_type VARCHAR(30)"),
            ("sl_level", "ALTER TABLE signals ADD COLUMN sl_level FLOAT"),
            ("sl_offset", "ALTER TABLE signals ADD COLUMN sl_offset FLOAT"),
            ("tp1_type", "ALTER TABLE signals ADD COLUMN tp1_type VARCHAR(30)"),
            ("tp2_type", "ALTER TABLE signals ADD COLUMN tp2_type VARCHAR(30)"),
            ("max_favorable_excursion", "ALTER TABLE signals ADD COLUMN max_favorable_excursion FLOAT"),
            ("max_adverse_excursion", "ALTER TABLE signals ADD COLUMN max_adverse_excursion FLOAT"),
            ("bars_to_tp1", "ALTER TABLE signals ADD COLUMN bars_to_tp1 INTEGER"),
            ("bars_to_exit", "ALTER TABLE signals ADD COLUMN bars_to_exit INTEGER"),
            ("tp1_size", "ALTER TABLE signals ADD COLUMN tp1_size FLOAT DEFAULT 0.30"),
            ("tp2_size", "ALTER TABLE signals ADD COLUMN tp2_size FLOAT DEFAULT 0.40"),
            ("runner_size", "ALTER TABLE signals ADD COLUMN runner_size FLOAT DEFAULT 0.30"),
            ("tp1_pnl_percent", "ALTER TABLE signals ADD COLUMN tp1_pnl_percent FLOAT"),
            ("tp2_hit", "ALTER TABLE signals ADD COLUMN tp2_hit BOOLEAN DEFAULT 0"),
            ("tp2_closed_at", "ALTER TABLE signals ADD COLUMN tp2_closed_at DATETIME"),
            ("tp2_pnl_percent", "ALTER TABLE signals ADD COLUMN tp2_pnl_percent FLOAT"),
            ("trailing_active", "ALTER TABLE signals ADD COLUMN trailing_active BOOLEAN DEFAULT 0"),
            ("trailing_high_water_mark", "ALTER TABLE signals ADD COLUMN trailing_high_water_mark FLOAT"),
            ("runner_exit_price", "ALTER TABLE signals ADD COLUMN runner_exit_price FLOAT"),
            ("runner_pnl_percent", "ALTER TABLE signals ADD COLUMN runner_pnl_percent FLOAT"),
        ]
        
        added_count = 0
        skipped_count = 0
        
        for field_name, sql in new_fields:
            if field_name not in existing_columns:
                try:
                    cursor.execute(sql)
                    added_count += 1
                    print(f"✅ Добавлено поле: {field_name}")
                except sqlite3.OperationalError as e:
                    print(f"❌ Ошибка при добавлении {field_name}: {e}")
            else:
                skipped_count += 1
                print(f"⏭️  Уже существует: {field_name}")
        
        # Создаем индекс для оптимизации запросов
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_regime_confidence ON signals(market_regime, confluence_count)")
            print("\n✅ Создан индекс: idx_regime_confidence")
        except sqlite3.OperationalError as e:
            print(f"\n⚠️  Индекс уже существует или ошибка: {e}")
        
        conn.commit()
        conn.close()
        
        print()
        print("=" * 60)
        print(f"🎉 МИГРАЦИЯ ЗАВЕРШЕНА!")
        print(f"   ✅ Добавлено: {added_count} полей")
        print(f"   ⏭️  Пропущено: {skipped_count} полей (уже существуют)")
        print("=" * 60)
        print()
        print("✨ Теперь можете запускать бота!")
        return True
        
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e).lower():
            print("❌ ОШИБКА: База данных заблокирована!")
            print("   Сначала ОСТАНОВИТЕ бота, затем запустите этот скрипт снова.")
        else:
            print(f"❌ Ошибка: {e}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

if __name__ == "__main__":
    print()
    print("⚠️  ВАЖНО: Перед запуском этого скрипта ОСТАНОВИТЕ бота!")
    print("   (Закройте окно с ботом или нажмите Ctrl+C)")
    print()
    
    input("Нажмите ENTER когда остановите бота... ")
    
    success = apply_migration()
    
    print()
    input("Нажмите ENTER для выхода... ")
    
    sys.exit(0 if success else 1)
