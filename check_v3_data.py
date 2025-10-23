"""
Check V3 S/R Data in Database

Finds V3 data using correct database path and SQLAlchemy.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_PATH = 'data/trading_bot.db'

def check_v3_data():
    """Check V3 S/R data in database"""
    
    if not Path(DB_PATH).exists():
        print(f"❌ Database not found: {DB_PATH}")
        return
    
    print(f"📂 Database found: {DB_PATH}")
    print(f"   Size: {Path(DB_PATH).stat().st_size / 1024 / 1024:.1f} MB")
    print()
    
    # Create engine
    engine = create_engine(f'sqlite:///{DB_PATH}', connect_args={'check_same_thread': False})
    SessionLocal = sessionmaker(bind=engine)
    
    with SessionLocal() as session:
        try:
            # List all tables
            result = session.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ))
            tables = [row[0] for row in result]
            
            print("📋 All tables in database:")
            for table in tables:
                print(f"   - {table}")
            print()
            
            # Check for V3 tables
            v3_tables = [t for t in tables if 'v3' in t.lower()]
            
            if not v3_tables:
                print("❌ No V3 tables found!")
                print("   This means V3 has never run on this database.")
                return
            
            print(f"✅ Found {len(v3_tables)} V3-related tables:")
            for table in v3_tables:
                print(f"   - {table}")
            print()
            
            # Check v3_sr_signals table
            if 'v3_sr_signals' in tables:
                result = session.execute(text("SELECT COUNT(*) FROM v3_sr_signals"))
                total = result.scalar()
                
                result = session.execute(text("SELECT COUNT(*) FROM v3_sr_signals WHERE status = 'ACTIVE'"))
                active = result.scalar()
                
                result = session.execute(text("SELECT COUNT(*) FROM v3_sr_signals WHERE status IN ('CLOSED', 'CANCELLED')"))
                closed = result.scalar()
                
                print("📊 V3 S/R Signals:")
                print(f"   Total: {total}")
                print(f"   ├─ Active: {active}")
                print(f"   └─ Closed: {closed}")
                print()
                
                if closed > 0:
                    # Show statistics
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
                        print("📈 Performance by Setup:")
                        for setup, count, wr, pnl in stats:
                            print(f"   {setup}: {count} signals | WR: {wr}% | Avg PnL: {pnl}%")
                        print()
                
                # Check other V3 tables
                if 'v3_sr_zone_events' in tables:
                    result = session.execute(text("SELECT COUNT(*) FROM v3_sr_zone_events"))
                    events = result.scalar()
                    print(f"📍 Zone Events: {events}")
                
                if 'v3_sr_signal_locks' in tables:
                    result = session.execute(text("SELECT COUNT(*) FROM v3_sr_signal_locks"))
                    locks = result.scalar()
                    print(f"🔒 Signal Locks: {locks}")
            
            else:
                print("❌ Table 'v3_sr_signals' not found!")
                print("   V3 strategy may not have created signals yet.")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    check_v3_data()
