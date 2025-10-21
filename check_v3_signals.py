"""
Diagnostic script to check V3 signals data
"""
from src.database.database import Database
from src.database.models import V3SRSignal
from datetime import datetime, timedelta
import pytz

db = Database()
session = db.get_session()

try:
    # Get closed signals from last 7 days
    start_time = datetime.now(pytz.UTC) - timedelta(days=7)
    
    closed_signals = session.query(V3SRSignal).filter(
        V3SRSignal.status == 'CLOSED',
        V3SRSignal.created_at >= start_time
    ).all()
    
    print(f"\n{'='*80}")
    print(f"V3 S/R Closed Signals Analysis (Last 7 days)")
    print(f"{'='*80}\n")
    
    for idx, sig in enumerate(closed_signals, 1):
        print(f"Signal #{idx}: {sig.symbol} {sig.direction}")
        print(f"  Setup: {sig.setup_type}")
        print(f"  Entry: {sig.entry_price:.4f}")
        print(f"  SL: {sig.stop_loss:.4f}")
        print(f"  TP1: {sig.take_profit_1:.4f}")
        print(f"  TP2: {sig.take_profit_2:.4f}")
        print(f"  Exit Price: {sig.exit_price:.4f if sig.exit_price else 'N/A'}")
        print(f"  Exit Reason: {sig.exit_reason}")
        print(f"  PnL %: {sig.pnl_percent:.2f}%" if sig.pnl_percent else "  PnL %: N/A")
        print(f"  Final R: {sig.final_r_multiple:.2f}R" if sig.final_r_multiple else "  Final R: N/A")
        print(f"  TP1 Hit: {sig.tp1_hit}")
        print(f"  TP2 Hit: {sig.tp2_hit}")
        print(f"  Moved to BE: {sig.moved_to_be}")
        print(f"  TP1 PnL %: {sig.tp1_pnl_percent:.2f}%" if sig.tp1_pnl_percent else "  TP1 PnL %: None")
        print(f"  Duration: {sig.duration_minutes}m" if sig.duration_minutes else "  Duration: N/A")
        
        # Calculate what PnL SHOULD be for SL exit
        if sig.exit_reason == 'SL' and not sig.tp1_hit:
            if sig.direction == 'LONG':
                expected_pnl = ((sig.exit_price - sig.entry_price) / sig.entry_price) * 100
            else:
                expected_pnl = ((sig.entry_price - sig.exit_price) / sig.entry_price) * 100
            
            print(f"  ⚠️ EXPECTED PnL for SL (no TP1): {expected_pnl:.2f}%")
            
            if sig.pnl_percent and abs(sig.pnl_percent - expected_pnl) > 0.01:
                print(f"  ❌ ERROR: PnL mismatch! Recorded: {sig.pnl_percent:.2f}% vs Expected: {expected_pnl:.2f}%")
        
        print()
    
    # Summary
    total = len(closed_signals)
    sl_exits = len([s for s in closed_signals if s.exit_reason == 'SL'])
    tp1_hit_count = len([s for s in closed_signals if s.tp1_hit])
    positive_pnl = len([s for s in closed_signals if s.pnl_percent and s.pnl_percent > 0])
    
    print(f"{'='*80}")
    print(f"Summary:")
    print(f"  Total closed: {total}")
    print(f"  SL exits: {sl_exits}")
    print(f"  TP1 hit count: {tp1_hit_count}")
    print(f"  Positive PnL: {positive_pnl}")
    print(f"{'='*80}\n")

finally:
    session.close()
