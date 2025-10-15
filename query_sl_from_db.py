#!/usr/bin/env python3
"""
Query the SQLite database to find Action Price signals that hit stop-loss.
"""

import sqlite3
from collections import defaultdict

# Connect to database
db_path = 'data/trading_bot.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Available tables:")
for table in tables:
    print(f"  - {table[0]}")

# Check for Action Price signal table
ap_tables = [t[0] for t in tables if 'action' in t[0].lower() or 'price' in t[0].lower()]
print(f"\nAction Price related tables: {ap_tables}")

# Query the action_price_signals table (assuming it exists)
table_name = 'action_price_signals'

# Get table schema
print(f"\n{'='*80}")
print(f"Schema of {table_name}:")
print(f"{'='*80}")
try:
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  {col[1]:<20} {col[2]:<15}")
except sqlite3.OperationalError as e:
    print(f"Error: {e}")
    conn.close()
    exit(1)

# Query all closed signals
print(f"\n{'='*80}")
print(f"EXIT REASON BREAKDOWN:")
print(f"{'='*80}")

cursor.execute(f"""
    SELECT exit_reason, COUNT(*) as count
    FROM {table_name}
    WHERE status IN ('WIN', 'LOSS')
    GROUP BY exit_reason
    ORDER BY count DESC;
""")

exit_reasons = cursor.fetchall()
for reason, count in exit_reasons:
    print(f"  {reason or 'NULL':<20} {count:>3} signals")

# Query stop-loss signals with scores
print(f"\n{'='*80}")
print(f"STOP-LOSS TRADES ANALYSIS:")
print(f"{'='*80}")

cursor.execute(f"""
    SELECT 
        symbol,
        direction,
        confidence_score,
        entry_price,
        stop_loss,
        exit_price,
        exit_reason,
        pnl_percent,
        created_at,
        closed_at
    FROM {table_name}
    WHERE exit_reason = 'SL' OR exit_reason = 'STOP_LOSS'
    ORDER BY confidence_score ASC;
""")

sl_trades = cursor.fetchall()

if sl_trades:
    print(f"\nFound {len(sl_trades)} stop-loss trades\n")
    
    # Calculate statistics
    scores = [float(t[2]) if t[2] is not None else 0 for t in sl_trades]
    pnls = [float(t[7]) if t[7] is not None else 0 for t in sl_trades]
    
    avg_score = sum(scores) / len(scores) if scores else 0
    min_score = min(scores) if scores else 0
    max_score = max(scores) if scores else 0
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0
    
    print(f"Score Statistics:")
    print(f"  Average Score: {avg_score:.1f}")
    print(f"  Min Score:     {min_score:.1f}")
    print(f"  Max Score:     {max_score:.1f}")
    print(f"  Average PnL:   {avg_pnl:.2f}%")
    
    # Score distribution
    print(f"\nScore Distribution:")
    ranges = [(0, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 10)]
    for low, high in ranges:
        count = sum(1 for s in scores if low <= s < high)
        pct = (count / len(scores) * 100) if scores else 0
        print(f"  {low}-{high}: {count:3} trades ({pct:5.1f}%)")
    
    # Detailed list
    print(f"\n{'='*80}")
    print(f"DETAILED STOP-LOSS TRADES:")
    print(f"{'='*80}")
    print(f"{'Score':<7} {'Symbol':<12} {'Dir':<6} {'Entry':<12} {'SL':<12} {'Exit':<12} {'PnL%':<8} {'Created':<20}")
    print("-" * 120)
    
    for trade in sl_trades:
        symbol, direction, score, entry, sl, exit_p, exit_r, pnl, created, closed = trade
        print(f"{score or 0:<7.1f} {symbol:<12} {direction:<6} {entry or 'N/A':<12} "
              f"{sl or 'N/A':<12} {exit_p or 'N/A':<12} {pnl or 0:<8.2f} {created[:16] if created else 'N/A':<20}")
    
    # Insights
    print(f"\n{'='*80}")
    print(f"KEY INSIGHTS:")
    print(f"{'='*80}")
    
    low_score_sl = [t for t in sl_trades if (t[2] or 0) < 4.5]
    high_score_sl = [t for t in sl_trades if (t[2] or 0) >= 4.5]
    
    print(f"Low Score SL (< 4.5):  {len(low_score_sl):3} trades ({len(low_score_sl)/len(sl_trades)*100:.1f}%)")
    print(f"High Score SL (>= 4.5): {len(high_score_sl):3} trades ({len(high_score_sl)/len(sl_trades)*100:.1f}%)")
    
    if low_score_sl:
        avg_low = sum(float(t[2] or 0) for t in low_score_sl) / len(low_score_sl)
        print(f"  → Average score of low-score SL trades: {avg_low:.1f}")
    
    if high_score_sl:
        avg_high = sum(float(t[2] or 0) for t in high_score_sl) / len(high_score_sl)
        print(f"  → Average score of high-score SL trades: {avg_high:.1f}")

else:
    print("\nNo stop-loss trades found in the database.")
    
    # Check what exit_reason values actually exist
    cursor.execute(f"""
        SELECT DISTINCT exit_reason
        FROM {table_name}
        WHERE exit_reason IS NOT NULL;
    """)
    
    reasons = cursor.fetchall()
    print("\nAvailable exit_reason values:")
    for r in reasons:
        print(f"  - {r[0]}")

# Also check for all closed trades to see the overall picture
print(f"\n{'='*80}")
print(f"ALL CLOSED TRADES SUMMARY:")
print(f"{'='*80}")

cursor.execute(f"""
    SELECT 
        exit_reason,
        COUNT(*) as count,
        AVG(confidence_score) as avg_score,
        AVG(pnl_percent) as avg_pnl
    FROM {table_name}
    WHERE status IN ('WIN', 'LOSS')
    GROUP BY exit_reason
    ORDER BY count DESC;
""")

all_closed = cursor.fetchall()
print(f"{'Exit Reason':<20} {'Count':<8} {'Avg Score':<12} {'Avg PnL%':<12}")
print("-" * 60)
for reason, count, avg_sc, avg_pnl in all_closed:
    print(f"{reason or 'NULL':<20} {count:<8} {avg_sc or 0:<12.1f} {avg_pnl or 0:<12.2f}")

conn.close()
print(f"\n{'='*80}")
