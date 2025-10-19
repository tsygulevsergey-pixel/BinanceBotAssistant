"""
Migration script to add trailing_peak_price column to action_price_signals table
Run this once to update existing database schema
"""
import sqlite3
import logging

logger = logging.getLogger(__name__)

def migrate():
    """Add trailing_peak_price column to action_price_signals table"""
    try:
        conn = sqlite3.connect('trading_bot.db')
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(action_price_signals)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'trailing_peak_price' in columns:
            print("✅ Column 'trailing_peak_price' already exists")
            return
        
        # Add column
        cursor.execute("""
            ALTER TABLE action_price_signals 
            ADD COLUMN trailing_peak_price REAL
        """)
        
        conn.commit()
        conn.close()
        
        print("✅ Successfully added 'trailing_peak_price' column to action_price_signals table")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    migrate()
