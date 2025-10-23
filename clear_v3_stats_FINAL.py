"""
Clear ALL V3 S/R Data - FINAL VERSION

Works on Windows/Linux, finds correct database path.
Deletes ALL V3 signals, events, and locks.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
except ImportError:
    print("❌ SQLAlchemy not installed!")
    print("   Install: pip install sqlalchemy")
    sys.exit(1)

# Try to find database
DB_PATHS = [
    'data/trading_bot.db',  # Default location
    'trading_bot.db',        # Root directory
    '../data/trading_bot.db' # One level up
]

def find_database():
    """Find the database file"""
    for path in DB_PATHS:
        if Path(path).exists():
            return path
    return None

def clear_v3_data():
    """Delete ALL V3 S/R data"""
    
    db_path = find_database()
    
    if not db_path:
        print("=" * 60)
        print("❌ DATABASE NOT FOUND!")
        print("=" * 60)
        print()
        print("Searched in:")
        for path in DB_PATHS:
            print(f"   - {path}")
        print()
        print("Please run this script from your bot directory where")
        print("'data/trading_bot.db' file is located.")
        return
    
    print("=" * 60)
    print("🧹 CLEAR ALL V3 S/R DATA")
    print("=" * 60)
    print()
    print(f"📂 Database: {db_path}")
    print(f"   Size: {Path(db_path).stat().st_size / 1024 / 1024:.1f} MB")
    print()
    
    # Create engine
    engine = create_engine(f'sqlite:///{db_path}', connect_args={'check_same_thread': False})
    SessionLocal = sessionmaker(bind=engine)
    
    with SessionLocal() as session:
        try:
            # Check if V3 tables exist
            result = session.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%v3%'"
            ))
            v3_tables = [row[0] for row in result]
            
            if not v3_tables:
                print("❌ No V3 tables found!")
                print("   V3 has never run on this database.")
                return
            
            print(f"✅ Found {len(v3_tables)} V3 tables:")
            for table in v3_tables:
                print(f"   - {table}")
            print()
            
            # Count current data
            result = session.execute(text("SELECT COUNT(*) FROM v3_sr_signals"))
            total = result.scalar()
            
            result = session.execute(text("SELECT COUNT(*) FROM v3_sr_signals WHERE status = 'ACTIVE'"))
            active = result.scalar()
            
            result = session.execute(text("SELECT COUNT(*) FROM v3_sr_signals WHERE status IN ('CLOSED', 'CANCELLED')"))
            closed = result.scalar()
            
            result = session.execute(text("SELECT COUNT(*) FROM v3_sr_zone_events"))
            events = result.scalar()
            
            result = session.execute(text("SELECT COUNT(*) FROM v3_sr_signal_locks"))
            locks = result.scalar()
            
            print("📊 CURRENT V3 DATA:")
            print(f"   Signals: {total}")
            print(f"   ├─ Active: {active}")
            print(f"   └─ Closed: {closed}")
            print(f"   Zone Events: {events}")
            print(f"   Signal Locks: {locks}")
            print()
            
            if total == 0:
                print("✅ No V3 data to delete!")
                return
            
            # Show statistics before deletion
            if closed > 0:
                result = session.execute(text("""
                    SELECT 
                        setup_type,
                        COUNT(*) as count,
                        ROUND(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
                        ROUND(AVG(pnl_percent), 2) as avg_pnl
                    FROM v3_sr_signals 
                    WHERE status IN ('CLOSED', 'CANCELLED') AND pnl IS NOT NULL
                    GROUP BY setup_type
                """))
                
                stats = result.fetchall()
                if stats:
                    print("📈 OLD STATISTICS (created with bugs):")
                    for setup, count, wr, pnl in stats:
                        print(f"   {setup}: {count} signals | WR: {wr}% | Avg PnL: {pnl}%")
                    print()
            
            print("⚠️  ⚠️  ⚠️  WARNING  ⚠️  ⚠️  ⚠️")
            print()
            print("This will DELETE ALL V3 S/R data:")
            print(f"   ❌ {total} signals (including {active} ACTIVE!)")
            print(f"   ❌ {events} zone events")
            print(f"   ❌ {locks} signal locks")
            print(f"   ❌ ALL V3 statistics and history")
            print()
            print("This will KEEP:")
            print(f"   ✅ All candle data")
            print(f"   ✅ Other strategy signals")
            print()
            print("After deletion, new signals will use FIXED logic:")
            print(f"   ✅ TP1 ≠ TP2 (different targets)")
            print(f"   ✅ SL in correct side")
            print(f"   ✅ TP beyond entry (not in dead zone)")
            print(f"   ✅ All 200+ symbols working")
            print()
            
            response = input("Type 'DELETE ALL' to confirm: ")
            
            if response != 'DELETE ALL':
                print("❌ Cancelled")
                return
            
            # Delete data
            print("\n🧹 Deleting V3 data...")
            
            result = session.execute(text("DELETE FROM v3_sr_signals"))
            signals_deleted = result.rowcount
            
            result = session.execute(text("DELETE FROM v3_sr_zone_events"))
            events_deleted = result.rowcount
            
            result = session.execute(text("DELETE FROM v3_sr_signal_locks"))
            locks_deleted = result.rowcount
            
            session.commit()
            
            # Verify candles intact
            result = session.execute(text("SELECT COUNT(*) FROM candles"))
            candles = result.scalar()
            
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
            print(f"   ✅ {candles:,} candles")
            print()
            print("=" * 60)
            print("🎉 FRESH START!")
            print("=" * 60)
            print()
            print("Next: Restart bot to generate signals with fixed code!")
            print()
            print("Expected performance:")
            print("   🎯 Win Rate: 65-75% (target)")
            print("   📈 Profit Factor: 1.8-2.5 (target)")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            session.rollback()

if __name__ == '__main__':
    clear_v3_data()
