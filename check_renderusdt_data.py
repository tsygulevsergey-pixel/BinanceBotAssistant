#!/usr/bin/env python3
"""
Проверка данных RENDERUSDT в БД для анализа проблемы
"""
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import os

DB_PATH = "data/trading_bot.db"

def check_renderusdt_data():
    # Проверить существование БД
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at: {DB_PATH}")
        print(f"   Current directory: {os.getcwd()}")
        print(f"   Please check if bot is running from correct directory!")
        return
    
    print(f"✅ Database found: {DB_PATH}")
    print(f"   Size: {os.path.getsize(DB_PATH) / (1024*1024):.1f} MB")
    print()
    
    conn = sqlite3.connect(DB_PATH)
    
    # Сначала проверить есть ли ВООБЩЕ данные по RENDERUSDT
    check_query = """
    SELECT 
        timeframe,
        COUNT(*) as count,
        MIN(open_time) as first_candle,
        MAX(open_time) as last_candle
    FROM candles
    WHERE symbol = 'RENDERUSDT'
    GROUP BY timeframe
    ORDER BY timeframe
    """
    
    check_df = pd.read_sql_query(check_query, conn)
    
    if check_df.empty:
        print("❌ No RENDERUSDT data found in database at all!")
        conn.close()
        return
    
    print("📊 RENDERUSDT data summary:")
    print(check_df.to_string(index=False))
    print()
    
    # Получить последние 20 свечей 15m
    query_recent = """
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
    ORDER BY open_time DESC
    LIMIT 20
    """
    
    df_recent = pd.read_sql_query(query_recent, conn)
    
    if df_recent.empty:
        print("❌ No 15m data found for RENDERUSDT!")
        conn.close()
        return
    
    # Загрузить последние 500 свечей для расчета EMA200
    query_500 = """
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
    ORDER BY open_time DESC
    LIMIT 500
    """
    
    df_500 = pd.read_sql_query(query_500, conn)
    
    if len(df_500) >= 200:
        # Сортировать по времени (от старых к новым для правильного расчета EMA)
        df_500 = df_500.sort_values('open_time').reset_index(drop=True)
        
        # Рассчитать EMA200
        try:
            import pandas_ta as ta
            df_500['ema_200'] = ta.ema(df_500['close'], length=200)
            
            print(f"✅ Calculated EMA200 for {len(df_500)} candles")
            print()
            
            # Показать последние 20 свечей с EMA200
            print("📊 Last 20 candles (15m) with EMA200:")
            for idx, row in df_500.tail(20).iterrows():
                ema_str = f"{row['ema_200']:.3f}" if pd.notna(row['ema_200']) else "N/A"
                print(f"   {row['open_time']} | O:{row['open']:.3f} H:{row['high']:.3f} L:{row['low']:.3f} C:{row['close']:.3f} | EMA200: {ema_str}")
            print()
            
            # Показать EMA200 для нужных свечей
            print("=" * 80)
            print("🔍 EMA200 Analysis for Signal Candles:")
            print("=" * 80)
            
            # Свеча 22:15 UTC (01:15 local)
            candle_2215 = df_500[df_500['open_time'].str.contains('22:15')]
            if not candle_2215.empty:
                row = candle_2215.iloc[0]
                print(f"\n🔶 Indicator Candle (23 Oct 22:15 UTC = 24 Oct 01:15 local):")
                print(f"   O→C: {row['open']:.3f} → {row['close']:.3f}")
                print(f"   H-L: {row['high']:.3f} - {row['low']:.3f}")
                print(f"   EMA200: {row['ema_200']:.3f if pd.notna(row['ema_200']) else 'N/A'}")
                print(f"\n   📋 Expected from Signal:")
                print(f"   O→C: 2.443 → 2.449")
                print(f"   EMA200: 2.447")
                print(f"\n   {'✅ MATCH' if abs(row['ema_200'] - 2.447) < 0.001 else '❌ MISMATCH'}")
            
            # Свеча 22:30 UTC (01:30 local)
            candle_2230 = df_500[df_500['open_time'].str.contains('22:30')]
            if not candle_2230.empty:
                row = candle_2230.iloc[0]
                print(f"\n✅ Confirmation Candle (23 Oct 22:30 UTC = 24 Oct 01:30 local):")
                print(f"   O→C: {row['open']:.3f} → {row['close']:.3f}")
                print(f"   H-L: {row['high']:.3f} - {row['low']:.3f}")
                print(f"   EMA200: {row['ema_200']:.3f if pd.notna(row['ema_200']) else 'N/A'}")
                print(f"\n   📋 Expected from Signal:")
                print(f"   H-L: 2.459 - 2.449")
                print(f"   EMA200: 2.448")
                print(f"\n   {'✅ MATCH' if abs(row['ema_200'] - 2.448) < 0.001 else '❌ MISMATCH'}")
            
            print("\n" + "=" * 80)
            
        except ImportError:
            print("⚠️ pandas_ta not installed, cannot calculate EMA200")
            print("   Install with: pip install pandas-ta")
            print()
            
            print("📊 Last 20 candles (15m) without EMA200:")
            for idx, row in df_recent.iterrows():
                print(f"   {row['open_time']} | O:{row['open']:.3f} H:{row['high']:.3f} L:{row['low']:.3f} C:{row['close']:.3f}")
            print()
    else:
        print(f"⚠️ Only {len(df_500)} candles available, need at least 200 for EMA200")
        print()
        
        print("📊 Last 20 candles (15m):")
        for idx, row in df_recent.iterrows():
            print(f"   {row['open_time']} | O:{row['open']:.3f} H:{row['high']:.3f} L:{row['low']:.3f} C:{row['close']:.3f}")
        print()
    
    # Теперь получить свечи за 24 Oct 00:00 - 02:00 (2025 год!)
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
    AND open_time >= '2025-10-24 00:00:00'
    AND open_time <= '2025-10-24 02:00:00'
    ORDER BY open_time
    """
    
    df = pd.read_sql_query(query, conn)
    
    if df.empty:
        print("❌ No data found for RENDERUSDT 15m on 2025-10-24 00:00-02:00!")
        print("   Trying to find data around that date...")
        
        # Попробовать найти данные рядом
        query_around = """
        SELECT 
            open_time,
            open,
            high,
            low,
            close
        FROM candles
        WHERE symbol = 'RENDERUSDT'
        AND timeframe = '15m'
        AND open_time >= '2025-10-23 00:00:00'
        AND open_time <= '2025-10-25 00:00:00'
        ORDER BY open_time
        """
        df_around = pd.read_sql_query(query_around, conn)
        
        if not df_around.empty:
            print(f"\n✅ Found {len(df_around)} candles around Oct 23-25:")
            for idx, row in df_around.head(10).iterrows():
                print(f"   {row['open_time']} | C:{row['close']:.3f}")
        
        conn.close()
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
