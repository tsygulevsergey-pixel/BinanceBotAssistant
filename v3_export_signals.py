#!/usr/bin/env python3
"""
V3 S/R Signal Export Script
Экспортирует топ-10 сигналов с упущенным потенциалом из локальной базы данных
"""

import sqlite3
from datetime import datetime
import pytz

DB_PATH = "trading_bot.db"

def export_signals():
    """Export top signals with missed potential from local database"""
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        print("=" * 100)
        print("🔥 ТОП-10 СИГНАЛОВ V3 S/R С УПУЩЕННЫМ ПОТЕНЦИАЛОМ")
        print("=" * 100)
        print()
        
        query = """
        SELECT 
            signal_id,
            symbol,
            direction,
            setup_type,
            entry_price,
            stop_loss,
            take_profit_1,
            take_profit_2,
            exit_price,
            exit_reason,
            created_at,
            closed_at,
            pnl_percent,
            final_r_multiple,
            mfe_r,
            mae_r,
            confidence,
            tp1_hit,
            tp2_hit
        FROM v3_sr_signals
        WHERE 
            exit_reason IS NOT NULL 
            AND mfe_r IS NOT NULL
            AND final_r_multiple IS NOT NULL
            AND (mfe_r - final_r_multiple) > 0.5
        ORDER BY (mfe_r - final_r_multiple) DESC
        LIMIT 10
        """
        
        cursor.execute(query)
        signals = cursor.fetchall()
        
        if not signals:
            print("⚠️  Сигналы с упущенным потенциалом не найдены в базе данных.")
            print(f"Проверьте что файл {DB_PATH} существует в текущей директории.")
            return
        
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        utc_tz = pytz.UTC
        
        for idx, signal in enumerate(signals, 1):
            # Конвертация времени в киевское
            try:
                if signal['created_at']:
                    created_dt = datetime.fromisoformat(signal['created_at'].replace('Z', '+00:00'))
                    if created_dt.tzinfo is None:
                        created_dt = utc_tz.localize(created_dt)
                    created_kyiv = created_dt.astimezone(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    created_kyiv = "N/A"
                    
                if signal['closed_at']:
                    closed_dt = datetime.fromisoformat(signal['closed_at'].replace('Z', '+00:00'))
                    if closed_dt.tzinfo is None:
                        closed_dt = utc_tz.localize(closed_dt)
                    closed_kyiv = closed_dt.astimezone(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    closed_kyiv = "N/A"
            except:
                created_kyiv = signal['created_at'] if signal['created_at'] else "N/A"
                closed_kyiv = signal['closed_at'] if signal['closed_at'] else "N/A"
            
            # Расчет упущенного потенциала
            mfe_r = signal['mfe_r'] if signal['mfe_r'] else 0
            final_r = signal['final_r_multiple'] if signal['final_r_multiple'] else 0
            missed_r = mfe_r - final_r
            
            # Расчет цены при MFE
            entry = signal['entry_price']
            sl = signal['stop_loss']
            risk = abs(entry - sl) if entry and sl else 0
            
            if signal['direction'] == 'LONG' and risk > 0:
                mfe_price = entry + (mfe_r * risk)
            elif signal['direction'] == 'SHORT' and risk > 0:
                mfe_price = entry - (mfe_r * risk)
            else:
                mfe_price = 0
            
            print(f"{'=' * 100}")
            print(f"#{idx} - {signal['symbol']} {signal['direction']} {signal['setup_type']}")
            print(f"{'=' * 100}")
            print(f"Signal ID: {signal['signal_id']}")
            print()
            print(f"📅 Время входа (Киев):  {created_kyiv}")
            print(f"📅 Время выхода (Киев): {closed_kyiv}")
            print()
            print(f"💰 Entry Price:   {signal['entry_price']:.6f}" if signal['entry_price'] else "💰 Entry Price:   N/A")
            print(f"🛑 Stop Loss:     {signal['stop_loss']:.6f}" if signal['stop_loss'] else "🛑 Stop Loss:     N/A")
            print(f"🎯 Take Profit 1: {signal['take_profit_1']:.6f} (1.0R)" if signal['take_profit_1'] else "🎯 Take Profit 1: N/A")
            print(f"🎯 Take Profit 2: {signal['take_profit_2']:.6f} (1.5R)" if signal['take_profit_2'] else "🎯 Take Profit 2: N/A")
            print()
            print(f"📊 Exit Price:    {signal['exit_price']:.6f}" if signal['exit_price'] else "📊 Exit Price:    N/A")
            print(f"📊 Exit Reason:   {signal['exit_reason']}")
            print()
            
            tp1_status = "✅ YES" if signal['tp1_hit'] else "❌ NO"
            tp2_status = "✅ YES" if signal['tp2_hit'] else "❌ NO"
            print(f"TP1 Hit: {tp1_status} | TP2 Hit: {tp2_status}")
            print()
            
            pnl = signal['pnl_percent'] if signal['pnl_percent'] else 0
            print(f"💵 Final PnL:     {final_r:+.2f}R ({pnl:+.2f}%)")
            print(f"📈 MFE (Max):     {mfe_r:+.2f}R ← Цена достигла этого уровня!")
            
            if mfe_price > 0:
                print(f"📍 Цена при MFE:  {mfe_price:.6f}")
            
            mae_r = signal['mae_r'] if signal['mae_r'] else 0
            print(f"📉 MAE (Min):     {mae_r:+.2f}R")
            print()
            print(f"⚠️  УПУЩЕНО:       {missed_r:.2f}R")
            
            if signal['confidence']:
                print(f"📊 Confidence:    {signal['confidence']:.0f}%")
            
            print()
            
            # Анализ
            if signal['exit_reason'] == 'TP2' and missed_r > 1.0:
                print(f"💡 ПРОБЛЕМА: TP2 зафиксировал на {final_r:.2f}R, но цена дошла до {mfe_r:.2f}R!")
                print(f"   Если бы был только trailing (без TP2), получили бы ~{mfe_r:.2f}R")
            elif signal['exit_reason'] == 'SL' and mfe_r > 0.5:
                print(f"💡 ПРОБЛЕМА: Цена дошла до {mfe_r:.2f}R, но вернулась в SL!")
                print(f"   Нужен агрессивный перевод в BE после MFE > 0.5R")
            elif signal['exit_reason'] == 'TRAIL':
                print(f"💡 INFO: Trailing сработал на {final_r:.2f}R (MFE был {mfe_r:.2f}R)")
                if missed_r > 0.5:
                    print(f"   Возможно увеличить trail_atr_mult для большего захвата")
            
            print()
        
        print(f"{'=' * 100}")
        print(f"📌 SUMMARY:")
        print(f"   Найдено {len(signals)} сигналов с упущенным потенциалом > 0.5R")
        print(f"   База данных: {DB_PATH}")
        print(f"{'=' * 100}")
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"❌ Ошибка базы данных: {e}")
        print(f"Убедитесь что файл {DB_PATH} существует в текущей директории.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print()
    print("V3 S/R Signal Export Tool")
    print("Экспорт сигналов с упущенным потенциалом")
    print()
    export_signals()
    print()
    input("Нажмите Enter для выхода...")
