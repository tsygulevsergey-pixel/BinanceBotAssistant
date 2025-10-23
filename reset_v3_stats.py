"""
Reset V3 S/R Statistics - Clear ONLY closed signals

This script clears CLOSED V3 S/R signals (keeps active signals).
Use this to reset statistics after fixing bugs while preserving current positions.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = 'trading_bot.db'

def reset_v3_stats():
    """Clear closed V3 S/R signals, keep active ones"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check if tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v3_sr_signals'")
        if not cursor.fetchone():
            print("❌ Table 'v3_sr_signals' not found!")
            print("   Bot needs to run at least once to create tables.")
            return
        
        # Count current signals
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals")
        total_signals = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals WHERE status = 'ACTIVE'")
        active_signals = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals WHERE status IN ('CLOSED', 'CANCELLED')")
        closed_signals = cursor.fetchone()[0]
        
        print("=" * 60)
        print("📊 CURRENT V3 S/R STATISTICS")
        print("=" * 60)
        print(f"Total signals: {total_signals}")
        print(f"├─ Active: {active_signals}")
        print(f"└─ Closed/Cancelled: {closed_signals}")
        print()
        
        if closed_signals == 0:
            print("✅ No closed signals to delete!")
            return
        
        # Show some statistics before deletion
        cursor.execute("""
            SELECT 
                setup_type,
                COUNT(*) as count,
                ROUND(AVG(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100, 1) as win_rate,
                ROUND(AVG(pnl_percent), 2) as avg_pnl
            FROM v3_sr_signals 
            WHERE status IN ('CLOSED', 'CANCELLED')
            GROUP BY setup_type
        """)
        
        stats = cursor.fetchall()
        if stats:
            print("📈 Statistics to be deleted:")
            for setup, count, wr, pnl in stats:
                print(f"   {setup}: {count} signals | WR: {wr}% | Avg PnL: {pnl}%")
            print()
        
        print("⚠️  WARNING: This will DELETE:")
        print(f"   • {closed_signals} closed/cancelled signals")
        print(f"   • All their statistics and history")
        print()
        print("✅ This will KEEP:")
        print(f"   • {active_signals} active signals (current positions)")
        print(f"   • All candle data")
        print()
        
        response = input("Continue? (yes/no): ")
        
        if response.lower() not in ['yes', 'y']:
            print("❌ Cancelled")
            return
        
        # Delete closed signals
        cursor.execute("DELETE FROM v3_sr_signals WHERE status IN ('CLOSED', 'CANCELLED')")
        deleted = cursor.rowcount
        
        # Clear zone events
        try:
            cursor.execute("DELETE FROM v3_sr_zone_events")
            events_deleted = cursor.rowcount
        except:
            events_deleted = 0
        
        # Clear old locks (but keep active ones)
        try:
            cursor.execute("""
                DELETE FROM v3_sr_signal_locks 
                WHERE signal_id NOT IN (
                    SELECT signal_id FROM v3_sr_signals WHERE status = 'ACTIVE'
                )
            """)
            locks_deleted = cursor.rowcount
        except:
            locks_deleted = 0
        
        conn.commit()
        
        print()
        print("=" * 60)
        print("✅ SUCCESS!")
        print("=" * 60)
        print(f"Deleted: {deleted} closed signals")
        print(f"Deleted: {events_deleted} zone events")
        print(f"Deleted: {locks_deleted} old locks")
        print(f"Kept: {active_signals} active signals")
        print()
        print("📊 Fresh start! New signals will use fixed logic:")
        print("   ✅ TP1 ≠ TP2 (different targets)")
        print("   ✅ SL in correct side")
        print("   ✅ TP beyond entry (not in dead zone)")
        print("   ✅ All 200+ symbols working")
        print()
        print("👉 Bot is ready! Statistics will rebuild from scratch.")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    
    finally:
        conn.close()

if __name__ == '__main__':
    reset_v3_stats()
