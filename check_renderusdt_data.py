#!/usr/bin/env python3
"""
Проверка данных RENDERUSDT в БД для анализа проблемы
"""
import sqlite3
import pandas as pd
from datetime import datetime
import pytz

DB_PATH = "data/trading_bot.db"

def check_renderusdt_data():
    conn = sqlite3.connect(DB_PATH)
    
    # Получить свечи RENDERUSDT 15m за 24 Oct 00:00 - 02:00
    query = """
    SELECT 
        open_time,
        open,
        high,
        low,
        close,
        volume
    FROM candles
    WHERE symbol = 'RENDERUSDT'
    AND timeframe = '15m'
    AND open_time >= '2024-10-24 00:00:00'
    AND open_time <= '2024-10-24 02:00:00'
    ORDER BY open_time
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        print("❌ No data found for RENDERUSDT 15m!")
        return
    
    # Рассчитать EMA200 (нужно загрузить больше данных для точного расчета)
    conn = sqlite3.connect(DB_PATH)
    query_full = """
    SELECT 
        open_time,
        close
    FROM candles
    WHERE symbol = 'RENDERUSDT'
    AND timeframe = '15m'
    ORDER BY open_time DESC
    LIMIT 500
    """
    
    df_full = pd.read_sql_query(query_full, conn)
    conn.close()
    
    if len(df_full) < 200:
        print(f"⚠️ Only {len(df_full)} candles available, need at least 200 for EMA200")
        return
    
    # Рассчитать EMA200
    import pandas_ta as ta
    df_full = df_full.sort_values('open_time')
    df_full['ema_200'] = ta.ema(df_full['close'], length=200)
    
    print("=" * 80)
    print("📊 RENDERUSDT 15m Data from DB (24 Oct 2024 00:00-02:00)")
    print("=" * 80)
    print()
    
    # Показать все свечи с EMA200
    df_with_ema = df.merge(
        df_full[['open_time', 'ema_200']], 
        on='open_time', 
        how='left'
    )
    
    for idx, row in df_with_ema.iterrows():
        ot = pd.to_datetime(row['open_time'])
        print(f"🕐 {ot.strftime('%H:%M')} | "
              f"O: {row['open']:.3f} | "
              f"H: {row['high']:.3f} | "
              f"L: {row['low']:.3f} | "
              f"C: {row['close']:.3f} | "
              f"EMA200: {row['ema_200']:.3f if pd.notna(row['ema_200']) else 'N/A'}")
    
    print()
    print("=" * 80)
    print("🔍 Focus on Signal Candles:")
    print("=" * 80)
    
    # Показать свечу индикатора (01:15)
    candle_0115 = df_with_ema[df_with_ema['open_time'].str.contains('01:15')]
    if not candle_0115.empty:
        row = candle_0115.iloc[0]
        print(f"\n🔶 Indicator Candle (01:15):")
        print(f"   O→C: {row['open']:.3f} → {row['close']:.3f}")
        print(f"   H-L: {row['high']:.3f} - {row['low']:.3f}")
        print(f"   EMA200: {row['ema_200']:.3f if pd.notna(row['ema_200']) else 'N/A'}")
    else:
        print("\n❌ Candle 01:15 NOT FOUND in DB!")
    
    # Показать свечу подтверждения (01:30)
    candle_0130 = df_with_ema[df_with_ema['open_time'].str.contains('01:30')]
    if not candle_0130.empty:
        row = candle_0130.iloc[0]
        print(f"\n✅ Confirmation Candle (01:30):")
        print(f"   O→C: {row['open']:.3f} → {row['close']:.3f}")
        print(f"   H-L: {row['high']:.3f} - {row['low']:.3f}")
        print(f"   EMA200: {row['ema_200']:.3f if pd.notna(row['ema_200']) else 'N/A'}")
    else:
        print("\n❌ Candle 01:30 NOT FOUND in DB!")
    
    print()
    print("=" * 80)
    print("📋 Expected from Signal:")
    print("=" * 80)
    print("\n🔶 Indicator (01:15):")
    print("   O→C: 2.443 → 2.449")
    print("   EMA200: 2.447")
    print("\n✅ Confirmation (01:30):")
    print("   H-L: 2.459 - 2.449")
    print("   EMA200: 2.448")
    print()

if __name__ == "__main__":
    check_renderusdt_data()
