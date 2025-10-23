"""
Clear V3 S/R Signal History

This script clears V3 S/R signal history, zone events, and locks.
Useful for starting fresh with updated signal generation logic.
"""

import sqlite3
import os

DB_PATH = 'trading_bot.db'

def clear_v3_signals():
    """Clear all V3 S/R signal-related data"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        tables_to_clear = [
            ('v3_sr_signals', 'V3 S/R Signals'),
            ('v3_sr_zone_events', 'Zone Events'),
            ('v3_sr_signal_locks', 'Signal Locks'),
        ]
        
        total_deleted = 0
        
        print("🧹 Clearing V3 S/R data...\n")
        
        for table_name, description in tables_to_clear:
            try:
                # Check if table exists
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                if not cursor.fetchone():
                    print(f"⚠️  Table '{table_name}' not found (skipping)")
                    continue
                
                # Count rows before delete
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count_before = cursor.fetchone()[0]
                
                # Delete all rows
                cursor.execute(f"DELETE FROM {table_name}")
                deleted = cursor.rowcount
                total_deleted += deleted
                
                print(f"✅ {description}: deleted {deleted:,} rows")
                
            except sqlite3.Error as e:
                print(f"⚠️  {description}: {e}")
        
        # Commit changes
        conn.commit()
        
        # Verify candles are still there
        try:
            cursor.execute("SELECT COUNT(*) FROM candles")
            candles_count = cursor.fetchone()[0]
            print(f"\n📊 Candles preserved: {candles_count:,} rows ✅")
        except:
            print("\n⚠️  Could not verify candles table")
        
        print(f"\n🎉 SUCCESS! Deleted {total_deleted:,} total rows from V3 tables.")
        print("\n👉 Next steps:")
        print("   1. Update your code with the fixed files")
        print("   2. Restart the bot: python main.py")
        print("   3. Fresh signals will be generated with correct logic!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        conn.rollback()
    
    finally:
        conn.close()

if __name__ == '__main__':
    print("=" * 60)
    print("🧹 CLEAR V3 S/R SIGNAL HISTORY")
    print("=" * 60)
    print()
    print("This will delete:")
    print("  • All V3 S/R signals (history)")
    print("  • Zone touch events")
    print("  • Signal locks")
    print()
    print("This will KEEP:")
    print("  • All candle data (OHLCV history)")
    print("  • Other strategy signals")
    print()
    
    response = input("Continue? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        clear_v3_signals()
    else:
        print("❌ Cancelled")
