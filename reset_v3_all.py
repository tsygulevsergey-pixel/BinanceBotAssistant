"""
Reset ALL V3 S/R Data - Complete Clean Slate

This script deletes ALL V3 S/R data including active signals.
Use this for a complete fresh start after fixing bugs.
"""

import sqlite3
import os

DB_PATH = 'trading_bot.db'

def reset_all_v3():
    """Delete ALL V3 S/R data - complete reset"""
    
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
            print("   No V3 data to delete.")
            return
        
        # Count current signals
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals")
        total_signals = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals WHERE status = 'ACTIVE'")
        active_signals = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signals WHERE status IN ('CLOSED', 'CANCELLED')")
        closed_signals = cursor.fetchone()[0]
        
        # Count other data
        cursor.execute("SELECT COUNT(*) FROM v3_sr_zone_events")
        zone_events = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v3_sr_signal_locks")
        locks = cursor.fetchone()[0]
        
        print("=" * 60)
        print("🧹 COMPLETE V3 S/R DATA RESET")
        print("=" * 60)
        print()
        print("📊 CURRENT DATA:")
        print(f"   Total signals: {total_signals}")
        print(f"   ├─ Active: {active_signals}")
        print(f"   └─ Closed: {closed_signals}")
        print(f"   Zone events: {zone_events}")
        print(f"   Signal locks: {locks}")
        print()
        
        if total_signals == 0:
            print("✅ No V3 data to delete!")
            return
        
        # Show statistics
        cursor.execute("""
            SELECT 
                setup_type,
                COUNT(*) as count,
                ROUND(AVG(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100, 1) as win_rate,
                ROUND(AVG(pnl_percent), 2) as avg_pnl
            FROM v3_sr_signals 
            WHERE status IN ('CLOSED', 'CANCELLED') AND pnl IS NOT NULL
            GROUP BY setup_type
        """)
        
        stats = cursor.fetchall()
        if stats:
            print("📈 OLD STATISTICS (created with bugs):")
            for setup, count, wr, pnl in stats:
                print(f"   {setup}: {count} signals | WR: {wr}% | Avg PnL: {pnl}%")
            print()
        
        print("⚠️  ⚠️  ⚠️  WARNING  ⚠️  ⚠️  ⚠️")
        print()
        print("This will DELETE ALL V3 S/R data:")
        print(f"   ❌ {total_signals} signals (including {active_signals} ACTIVE positions!)")
        print(f"   ❌ {zone_events} zone events")
        print(f"   ❌ {locks} signal locks")
        print(f"   ❌ ALL V3 statistics and history")
        print()
        print("This will KEEP:")
        print(f"   ✅ All candle data (no need to reload)")
        print(f"   ✅ Other strategy signals")
        print()
        print("After this:")
        print(f"   🆕 V3 will start fresh with FIXED logic:")
        print(f"      • TP1 ≠ TP2 (different targets)")
        print(f"      • SL in correct side")
        print(f"      • TP beyond entry (not in dead zone)")
        print(f"      • All 200+ symbols working")
        print()
        
        response = input("Are you ABSOLUTELY SURE? Type 'DELETE ALL' to confirm: ")
        
        if response != 'DELETE ALL':
            print("❌ Cancelled")
            return
        
        # Delete everything
        print("\n🧹 Deleting V3 data...")
        
        cursor.execute("DELETE FROM v3_sr_signals")
        signals_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM v3_sr_zone_events")
        events_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM v3_sr_signal_locks")
        locks_deleted = cursor.rowcount
        
        conn.commit()
        
        # Verify candles are intact
        cursor.execute("SELECT COUNT(*) FROM candles")
        candles_count = cursor.fetchone()[0]
        
        print()
        print("=" * 60)
        print("✅ ✅ ✅  SUCCESS!  ✅ ✅ ✅")
        print("=" * 60)
        print()
        print("DELETED:")
        print(f"   ❌ {signals_deleted} V3 signals")
        print(f"   ❌ {events_deleted} zone events")
        print(f"   ❌ {locks_deleted} signal locks")
        print()
        print("PRESERVED:")
        print(f"   ✅ {candles_count:,} candles")
        print()
        print("=" * 60)
        print("🎉 FRESH START!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("   1. Bot is ready with FIXED code")
        print("   2. New signals will use correct logic:")
        print("      ✅ Proper TP placement")
        print("      ✅ Correct SL direction")
        print("      ✅ All symbols working")
        print("   3. Statistics will rebuild from scratch")
        print()
        print("Expected performance with fixes:")
        print("   🎯 Win Rate: 65-75% (target)")
        print("   📈 Profit Factor: 1.8-2.5 (target)")
        print()
        print("👉 Restart the bot to begin fresh:")
        print("   python main.py")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    
    finally:
        conn.close()

if __name__ == '__main__':
    reset_all_v3()
