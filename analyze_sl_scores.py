#!/usr/bin/env python3
"""
Analyze Action Price signals to identify SL trades and their scores.
"""

import json
import glob
from collections import defaultdict

# Find all JSONL files
jsonl_files = glob.glob('attached_assets/action_price_signals_*.jsonl')

# Storage for analysis
sl_trades = []
all_trades_by_exit = defaultdict(list)
scores_by_exit = defaultdict(list)

# Parse all JSONL files
for file_path in jsonl_files:
    with open(file_path, 'r') as f:
        for line in f:
            try:
                signal = json.loads(line.strip())
                exit_reason = signal.get('exit_reason') or 'UNKNOWN'
                total_score = signal.get('total_score', 0)
                
                # Collect all trades
                all_trades_by_exit[exit_reason].append(signal)
                scores_by_exit[exit_reason].append(total_score)
                
                # Collect SL trades specifically
                if exit_reason == 'SL':
                    sl_trades.append({
                        'symbol': signal.get('symbol'),
                        'direction': signal.get('direction'),
                        'score': total_score,
                        'entry_price': signal.get('entry_price'),
                        'sl_price': signal.get('sl_price'),
                        'pnl_percent': signal.get('total_pnl_percent'),
                        'timestamp': signal.get('timestamp')
                    })
            except json.JSONDecodeError:
                continue

# Print summary statistics
print("=" * 80)
print("ACTION PRICE SIGNAL ANALYSIS - SL TRADES")
print("=" * 80)
print(f"\nTotal signals analyzed: {sum(len(trades) for trades in all_trades_by_exit.values())}")
print(f"\nBreakdown by Exit Reason:")
for exit_reason, trades in sorted(all_trades_by_exit.items()):
    avg_score = sum(scores_by_exit[exit_reason]) / len(scores_by_exit[exit_reason]) if scores_by_exit[exit_reason] else 0
    print(f"  {exit_reason:15} {len(trades):3} signals  (Avg Score: {avg_score:.1f})")

print("\n" + "=" * 80)
print(f"STOP-LOSS TRADES DETAILED ANALYSIS ({len(sl_trades)} trades)")
print("=" * 80)

if sl_trades:
    # Sort by score
    sl_trades_sorted = sorted(sl_trades, key=lambda x: x['score'])
    
    # Calculate statistics
    scores = [t['score'] for t in sl_trades]
    avg_score = sum(scores) / len(scores)
    min_score = min(scores)
    max_score = max(scores)
    
    print(f"\nScore Statistics:")
    print(f"  Average Score: {avg_score:.1f}")
    print(f"  Min Score:     {min_score:.1f}")
    print(f"  Max Score:     {max_score:.1f}")
    
    # Score distribution
    print(f"\nScore Distribution:")
    ranges = [(0, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 10)]
    for low, high in ranges:
        count = sum(1 for s in scores if low <= s < high)
        pct = (count / len(scores) * 100) if scores else 0
        print(f"  {low}-{high}: {count:3} trades ({pct:5.1f}%)")
    
    # Detailed list
    print(f"\nDetailed List of SL Trades (sorted by score):")
    print(f"{'Score':<7} {'Symbol':<12} {'Dir':<5} {'Entry':<12} {'SL':<12} {'PnL%':<8} {'Timestamp'}")
    print("-" * 80)
    
    for trade in sl_trades_sorted:
        print(f"{trade['score']:<7.1f} {trade['symbol']:<12} {trade['direction']:<5} "
              f"{trade['entry_price']:<12} {trade['sl_price']:<12} "
              f"{trade['pnl_percent']:<8.2f} {trade['timestamp']}")
    
    # Identify pattern: low vs high scores
    low_score_sl = [t for t in sl_trades if t['score'] < 4.5]
    high_score_sl = [t for t in sl_trades if t['score'] >= 4.5]
    
    print(f"\n" + "=" * 80)
    print("KEY INSIGHTS:")
    print("=" * 80)
    print(f"Low Score SL (< 4.5):  {len(low_score_sl):3} trades ({len(low_score_sl)/len(sl_trades)*100:.1f}%)")
    print(f"High Score SL (>= 4.5): {len(high_score_sl):3} trades ({len(high_score_sl)/len(sl_trades)*100:.1f}%)")
    
    if low_score_sl:
        avg_low = sum(t['score'] for t in low_score_sl) / len(low_score_sl)
        print(f"  → Average score of low-score SL trades: {avg_low:.1f}")
    
    if high_score_sl:
        avg_high = sum(t['score'] for t in high_score_sl) / len(high_score_sl)
        print(f"  → Average score of high-score SL trades: {avg_high:.1f}")

else:
    print("\nNo SL trades found in the data.")
    print("\nAvailable exit reasons:", list(all_trades_by_exit.keys()))

print("\n" + "=" * 80)
