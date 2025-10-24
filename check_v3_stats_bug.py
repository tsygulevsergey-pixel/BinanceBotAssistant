#!/usr/bin/env python3
"""
Проверка бага в V3 S/R статистике
"""
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import pytz

DB_PATH = "data/trading_bot.db"

def check_v3_stats():
    conn = sqlite3.connect(DB_PATH)
    
    # Последние 7 дней
    start_time = datetime.now(pytz.UTC) - timedelta(days=7)
    
    # Все закрытые сигналы
    query = """
    SELECT 
        id,
        symbol,
        direction,
        setup_type,
        entry_price,
        stop_loss,
        exit_price,
        exit_reason,
        pnl_percent,
        tp1_hit,
        tp2_hit,
        moved_to_be,
        created_at,
        closed_at
    FROM v3_sr_signals
    WHERE status = 'CLOSED'
    AND created_at >= ?
    ORDER BY closed_at DESC
    """
    
    df = pd.read_sql_query(query, conn, params=(start_time.isoformat(),))
    conn.close()
    
    if df.empty:
        print("❌ No closed V3 signals found in last 7 days!")
        return
    
    print(f"📊 Found {len(df)} closed V3 signals in last 7 days\n")
    print("=" * 120)
    
    # Показать каждый сигнал
    for idx, row in df.iterrows():
        win_loss = "✅ WIN" if row['pnl_percent'] and row['pnl_percent'] > 0 else "❌ LOSS"
        
        print(f"\n🔷 Signal #{row['id']}: {row['symbol']} {row['direction']} {row['setup_type']}")
        print(f"   Entry: {row['entry_price']:.4f} → Exit: {row['exit_price']:.4f} (SL: {row['stop_loss']:.4f})")
        print(f"   Exit Reason: {row['exit_reason']}")
        print(f"   PnL: {row['pnl_percent']:.2f}% → {win_loss}")
        print(f"   TP1 Hit: {row['tp1_hit']} | TP2 Hit: {row['tp2_hit']} | Moved to BE: {row['moved_to_be']}")
        print(f"   Created: {row['created_at']} | Closed: {row['closed_at']}")
    
    print("\n" + "=" * 120)
    print("\n📊 STATISTICS BREAKDOWN:\n")
    
    # Подсчёт по exit_reason
    exit_reasons = df['exit_reason'].value_counts()
    print("Exit Reasons:")
    for reason, count in exit_reasons.items():
        print(f"  {reason}: {count}")
    
    # Подсчёт побед/поражений
    wins = len(df[df['pnl_percent'] > 0])
    losses = len(df[df['pnl_percent'] <= 0])
    win_rate = wins / len(df) * 100 if len(df) > 0 else 0
    
    print(f"\nWins/Losses:")
    print(f"  Wins (PnL > 0): {wins}")
    print(f"  Losses (PnL <= 0): {losses}")
    print(f"  Win Rate: {win_rate:.1f}%")
    
    # TP1/TP2 флаги
    tp1_count = len(df[df['tp1_hit'] == 1])
    tp2_count = len(df[df['tp2_hit'] == 1])
    moved_be_count = len(df[df['moved_to_be'] == 1])
    
    print(f"\nFlags:")
    print(f"  TP1 Hit (flag): {tp1_count}")
    print(f"  TP2 Hit (flag): {tp2_count}")
    print(f"  Moved to BE (flag): {moved_be_count}")
    
    # CRITICAL: Проверить противоречия
    print("\n" + "=" * 120)
    print("🔍 CHECKING FOR CONTRADICTIONS:\n")
    
    # Противоречие #1: SL exit с положительным PnL
    sl_with_positive_pnl = df[(df['exit_reason'] == 'SL') & (df['pnl_percent'] > 0)]
    if not sl_with_positive_pnl.empty:
        print(f"❌ BUG #1: {len(sl_with_positive_pnl)} signals with exit_reason='SL' but POSITIVE PnL:")
        for idx, row in sl_with_positive_pnl.iterrows():
            print(f"   Signal #{row['id']}: {row['symbol']} | PnL: {row['pnl_percent']:.2f}% | Moved to BE: {row['moved_to_be']}")
    else:
        print("✅ No SL exits with positive PnL")
    
    # Противоречие #2: moved_to_be=True но exit_reason='SL'
    be_with_sl_reason = df[(df['moved_to_be'] == 1) & (df['exit_reason'] == 'SL')]
    if not be_with_sl_reason.empty:
        print(f"\n❌ BUG #2: {len(be_with_sl_reason)} signals with moved_to_be=True but exit_reason='SL' (should be 'BE'):")
        for idx, row in be_with_sl_reason.iterrows():
            print(f"   Signal #{row['id']}: {row['symbol']} | PnL: {row['pnl_percent']:.2f}%")
    else:
        print("\n✅ No moved_to_be=True signals with exit_reason='SL'")
    
    # Противоречие #3: TP1 hit но не moved_to_be
    tp1_no_be = df[(df['tp1_hit'] == 1) & (df['moved_to_be'] == 0)]
    if not tp1_no_be.empty:
        print(f"\n⚠️ WARNING: {len(tp1_no_be)} signals with TP1 hit but moved_to_be=False:")
        for idx, row in tp1_no_be.iterrows():
            print(f"   Signal #{row['id']}: {row['symbol']}")
    else:
        print("\n✅ All TP1 hits have moved_to_be=True")
    
    print("\n" + "=" * 120)

if __name__ == '__main__':
    check_v3_stats()
