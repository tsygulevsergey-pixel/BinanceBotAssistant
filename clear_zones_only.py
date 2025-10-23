"""
Clear V3 S/R Zone Events and Locks (Keep Candles!)

This script clears zone-related tables but keeps all candle data.
Run this BEFORE starting the bot with updated code.
"""

import sqlite3
import os

DB_PATH = 'trading_bot.db'

def clear_zone_tables():
    """Clear only zone-related tables, keep candles"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check what tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%zone%'")
        tables = cursor.fetchall()
        
        print("📋 Zone-related tables found:")
        for table in tables:
            print(f"   - {table[0]}")
        
        # Clear zone events
        cursor.execute("DELETE FROM v3_sr_zone_events")
        events_deleted = cursor.rowcount
        print(f"\n✅ Cleared {events_deleted} zone events from v3_sr_zone_events")
        
        # Clear signal locks
        cursor.execute("DELETE FROM v3_sr_signal_locks")
        locks_deleted = cursor.rowcount
        print(f"✅ Cleared {locks_deleted} signal locks from v3_sr_signal_locks")
        
        # Commit changes
        conn.commit()
        
        # Verify candles are still there
        cursor.execute("SELECT COUNT(*) FROM candles")
        candles_count = cursor.fetchone()[0]
        print(f"\n📊 Candles preserved: {candles_count:,} rows ✅")
        
        print("\n🎉 SUCCESS! Zone tables cleared, candles preserved.")
        print("👉 Now restart the bot with updated code:")
        print("   python main.py")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        conn.rollback()
    
    finally:
        conn.close()

if __name__ == '__main__':
    print("=" * 60)
    print("🧹 CLEAR V3 ZONE TABLES (KEEP CANDLES)")
    print("=" * 60)
    print()
    
    response = input("This will clear zone events and locks. Continue? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        clear_zone_tables()
    else:
        print("❌ Cancelled")
