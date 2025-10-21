#!/usr/bin/env python3
"""
Анализ РЕАЛЬНЫХ результатов по BTC bias
Связываем JSON параметры с результатами из логов
"""

import json
import re
from pathlib import Path
from collections import defaultdict

def load_json_signals():
    """Загрузить сигналы из JSON"""
    with open('attached_assets/main_strategies_export_1761073131225.json', 'r', encoding='utf-8') as f:
        signals = json.load(f)
    
    for signal in signals:
        if signal.get('meta_data') and isinstance(signal['meta_data'], str):
            try:
                signal['meta_data'] = json.loads(signal['meta_data'])
            except:
                signal['meta_data'] = {}
    
    return signals

def parse_bot_logs():
    """Парсинг результатов из логов бота"""
    log_dir = Path('attached_assets')
    log_files = sorted(log_dir.glob('bot_2025-10-*.log'), 
                      key=lambda x: x.stat().st_mtime, reverse=True)
    
    pattern = re.compile(
        r'Signal closed.*?:\s*(\w+)\s+(LONG|SHORT).*?'
        r'Entry:\s*([\d.]+).*?Exit:\s*([\d.]+).*?'
        r'PnL:\s*([+-]?[\d.]+)%.*?\(([\w_]+)\)',
        re.IGNORECASE
    )
    
    trades = []
    
    for log_file in log_files[:20]:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            for match in pattern.finditer(content):
                symbol = match.group(1)
                direction = match.group(2)
                pnl = float(match.group(5))
                exit_type = match.group(6)
                
                trades.append({
                    'symbol': symbol,
                    'direction': direction,
                    'pnl': pnl,
                    'exit_type': exit_type
                })
        except:
            pass
    
    # Удаляем дубликаты
    unique_trades = []
    seen = set()
    
    for trade in trades:
        key = f"{trade['symbol']}_{trade['direction']}_{trade['pnl']}"
        if key not in seen:
            seen.add(key)
            unique_trades.append(trade)
    
    print(f"✅ Загружено {len(unique_trades)} уникальных сделок из логов")
    
    return unique_trades

def match_signals_with_results(signals, trades):
    """Сопоставить сигналы с результатами"""
    # Создаем индекс сделок
    trades_index = defaultdict(list)
    for trade in trades:
        key = f"{trade['symbol']}_{trade['direction']}"
        trades_index[key].append(trade)
    
    matched = []
    
    for signal in signals:
        key = f"{signal['symbol']}_{signal['direction']}"
        
        # Находим подходящую сделку
        if key in trades_index and len(trades_index[key]) > 0:
            # Берем первую неиспользованную
            trade = trades_index[key].pop(0)
            
            meta = signal.get('meta_data') or {}
            
            matched.append({
                'symbol': signal['symbol'],
                'direction': signal['direction'],
                'score': signal['score'],
                'regime': signal['market_regime'],
                'bias': meta.get('bias', 'unknown'),
                'volume_ratio': meta.get('volume_ratio', 1.0),
                'cvd_direction': meta.get('cvd_direction', ''),
                'strategy_id': signal['strategy_id'],
                'pnl': trade['pnl'],
                'exit_type': trade['exit_type']
            })
    
    print(f"✅ Сопоставлено {len(matched)} сигналов с результатами")
    
    return matched

def analyze_by_bias_and_direction(matched):
    """Анализ по bias и направлению"""
    print("\n" + "="*80)
    print("📊 РЕЗУЛЬТАТЫ ПО BTC BIAS И НАПРАВЛЕНИЮ")
    print("="*80)
    
    # Группировка
    groups = {
        'LONG_bearish': [],
        'LONG_neutral': [],
        'LONG_bullish': [],
        'SHORT_bearish': [],
        'SHORT_neutral': [],
        'SHORT_bullish': []
    }
    
    for item in matched:
        key = f"{item['direction']}_{item['bias']}"
        if key in groups:
            groups[key].append(item)
    
    # Анализ каждой группы
    print(f"\n{'Группа':<25} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'Total PnL':<12} {'Оценка'}")
    print("-"*85)
    
    results = {}
    
    for group_name, items in groups.items():
        if not items:
            continue
        
        wins = [i for i in items if i['pnl'] > 0]
        wr = (len(wins) / len(items) * 100) if items else 0
        avg_pnl = sum(i['pnl'] for i in items) / len(items)
        total_pnl = sum(i['pnl'] for i in items)
        
        # Определяем конфликт
        direction, bias = group_name.split('_')
        is_conflict = (direction == 'LONG' and bias == 'bearish') or \
                     (direction == 'SHORT' and bias == 'bullish')
        
        if is_conflict:
            rating = f"❌ КОНФЛИКТ" if avg_pnl < 0 else f"✅ РАБОТАЕТ!"
        else:
            rating = "✅ ПО ТРЕНДУ" if avg_pnl > 0 else "❌"
        
        results[group_name] = {
            'count': len(items),
            'wr': wr,
            'avg_pnl': avg_pnl,
            'total_pnl': total_pnl,
            'is_conflict': is_conflict
        }
        
        print(f"{group_name:<25} {len(items):<10} {wr:<10.1f} {avg_pnl:<+12.2f} {total_pnl:<+12.2f} {rating}")
    
    # Детальный анализ конфликтов
    print(f"\n\n🔍 ДЕТАЛЬНЫЙ АНАЛИЗ КОНФЛИКТОВ")
    print("="*80)
    
    # LONG при bearish
    if groups['LONG_bearish']:
        items = groups['LONG_bearish']
        print(f"\n❌ LONG при BEARISH bias ({len(items)} сделок):")
        
        wins = [i for i in items if i['pnl'] > 0]
        sl_exits = [i for i in items if i['exit_type'] == 'SL']
        tp2_exits = [i for i in items if i['exit_type'] == 'TP2']
        
        print(f"   Win Rate: {len(wins)/len(items)*100:.1f}%")
        print(f"   Avg PnL: {sum(i['pnl'] for i in items)/len(items):+.2f}%")
        print(f"   Total PnL: {sum(i['pnl'] for i in items):+.2f}%")
        print(f"   Выходы: TP2={len(tp2_exits)}, SL={len(sl_exits)}, Другие={len(items)-len(tp2_exits)-len(sl_exits)}")
        
        # Лучшие и худшие
        sorted_items = sorted(items, key=lambda x: x['pnl'], reverse=True)
        print(f"\n   Топ-3 лучших:")
        for i, item in enumerate(sorted_items[:3], 1):
            print(f"      {i}. {item['symbol']} {item['pnl']:+.2f}% ({item['exit_type']})")
        
        print(f"\n   Топ-3 худших:")
        for i, item in enumerate(sorted_items[-3:][::-1], 1):
            print(f"      {i}. {item['symbol']} {item['pnl']:+.2f}% ({item['exit_type']})")
    
    # SHORT при bearish (по тренду)
    if groups['SHORT_bearish']:
        items = groups['SHORT_bearish']
        print(f"\n\n✅ SHORT при BEARISH bias ({len(items)} сделок) - ПО ТРЕНДУ:")
        
        wins = [i for i in items if i['pnl'] > 0]
        sl_exits = [i for i in items if i['exit_type'] == 'SL']
        tp2_exits = [i for i in items if i['exit_type'] == 'TP2']
        
        print(f"   Win Rate: {len(wins)/len(items)*100:.1f}%")
        print(f"   Avg PnL: {sum(i['pnl'] for i in items)/len(items):+.2f}%")
        print(f"   Total PnL: {sum(i['pnl'] for i in items):+.2f}%")
        print(f"   Выходы: TP2={len(tp2_exits)}, SL={len(sl_exits)}, Другие={len(items)-len(tp2_exits)-len(sl_exits)}")
    
    # SHORT при bullish
    if groups['SHORT_bullish']:
        items = groups['SHORT_bullish']
        print(f"\n\n❌ SHORT при BULLISH bias ({len(items)} сделок):")
        
        wins = [i for i in items if i['pnl'] > 0]
        sl_exits = [i for i in items if i['exit_type'] == 'SL']
        tp2_exits = [i for i in items if i['exit_type'] == 'TP2']
        
        print(f"   Win Rate: {len(wins)/len(items)*100:.1f}%")
        print(f"   Avg PnL: {sum(i['pnl'] for i in items)/len(items):+.2f}%")
        print(f"   Total PnL: {sum(i['pnl'] for i in items):+.2f}%")
        print(f"   Выходы: TP2={len(tp2_exits)}, SL={len(sl_exits)}, Другие={len(items)-len(tp2_exits)-len(sl_exits)}")
    
    # LONG при bullish (по тренду)
    if groups['LONG_bullish']:
        items = groups['LONG_bullish']
        print(f"\n\n✅ LONG при BULLISH bias ({len(items)} сделок) - ПО ТРЕНДУ:")
        
        wins = [i for i in items if i['pnl'] > 0]
        sl_exits = [i for i in items if i['exit_type'] == 'SL']
        tp2_exits = [i for i in items if i['exit_type'] == 'TP2']
        
        print(f"   Win Rate: {len(wins)/len(items)*100:.1f}%")
        print(f"   Avg PnL: {sum(i['pnl'] for i in items)/len(items):+.2f}%")
        print(f"   Total PnL: {sum(i['pnl'] for i in items):+.2f}%")
        print(f"   Выходы: TP2={len(tp2_exits)}, SL={len(sl_exits)}, Другие={len(items)-len(tp2_exits)-len(sl_exits)}")
    
    return results

def analyze_by_regime(matched):
    """Анализ по режимам"""
    print("\n\n" + "="*80)
    print("🌊 РЕЗУЛЬТАТЫ ПО РЕЖИМАМ")
    print("="*80)
    
    regime_groups = defaultdict(list)
    for item in matched:
        regime_groups[item['regime']].append(item)
    
    print(f"\n{'Режим':<20} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'Total PnL':<12} {'Оценка'}")
    print("-"*80)
    
    for regime, items in sorted(regime_groups.items(), key=lambda x: len(x[1]), reverse=True):
        wins = [i for i in items if i['pnl'] > 0]
        wr = (len(wins) / len(items) * 100) if items else 0
        avg_pnl = sum(i['pnl'] for i in items) / len(items)
        total_pnl = sum(i['pnl'] for i in items)
        
        rating = "✅ ОТЛИЧНО" if wr >= 55 else "⚠️ СРЕДНЕ" if wr >= 45 else "❌ ПЛОХО"
        
        print(f"{regime:<20} {len(items):<10} {wr:<10.1f} {avg_pnl:<+12.2f} {total_pnl:<+12.2f} {rating}")
        
        # Детали по выходам
        sl_count = len([i for i in items if i['exit_type'] == 'SL'])
        tp2_count = len([i for i in items if i['exit_type'] == 'TP2'])
        
        print(f"   Выходы: TP2={tp2_count} ({tp2_count/len(items)*100:.1f}%), SL={sl_count} ({sl_count/len(items)*100:.1f}%)")

def compare_conflicts_vs_aligned(matched):
    """Сравнение конфликтных vs выровненных сделок"""
    print("\n\n" + "="*80)
    print("⚖️ КОНФЛИКТЫ vs ВЫРОВНЕННЫЕ СДЕЛКИ")
    print("="*80)
    
    conflicts = []
    aligned = []
    
    for item in matched:
        is_conflict = (item['direction'] == 'LONG' and item['bias'] == 'bearish') or \
                     (item['direction'] == 'SHORT' and item['bias'] == 'bullish')
        
        if is_conflict:
            conflicts.append(item)
        elif item['bias'] in ['bullish', 'bearish']:  # Только четкий bias
            aligned.append(item)
    
    print(f"\n📊 Сравнение:")
    print(f"\n{'Тип':<30} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'Total PnL':<12}")
    print("-"*75)
    
    # Конфликты
    if conflicts:
        wins = [i for i in conflicts if i['pnl'] > 0]
        wr = (len(wins) / len(conflicts) * 100)
        avg_pnl = sum(i['pnl'] for i in conflicts) / len(conflicts)
        total_pnl = sum(i['pnl'] for i in conflicts)
        
        print(f"{'❌ КОНФЛИКТЫ (против BTC)':<30} {len(conflicts):<10} {wr:<10.1f} {avg_pnl:<+12.2f} {total_pnl:+.2f}%")
        
        sl_rate = len([i for i in conflicts if i['exit_type'] == 'SL']) / len(conflicts) * 100
        print(f"   SL rate: {sl_rate:.1f}%")
    
    # Выровненные
    if aligned:
        wins = [i for i in aligned if i['pnl'] > 0]
        wr = (len(wins) / len(aligned) * 100)
        avg_pnl = sum(i['pnl'] for i in aligned) / len(aligned)
        total_pnl = sum(i['pnl'] for i in aligned)
        
        print(f"{'✅ ВЫРОВНЕННЫЕ (с BTC)':<30} {len(aligned):<10} {wr:<10.1f} {avg_pnl:<+12.2f} {total_pnl:+.2f}%")
        
        sl_rate = len([i for i in aligned if i['exit_type'] == 'SL']) / len(aligned) * 100
        print(f"   SL rate: {sl_rate:.1f}%")
    
    # Разница
    if conflicts and aligned:
        wr_diff = (len([i for i in aligned if i['pnl'] > 0]) / len(aligned) * 100) - \
                  (len([i for i in conflicts if i['pnl'] > 0]) / len(conflicts) * 100)
        
        avg_pnl_diff = (sum(i['pnl'] for i in aligned) / len(aligned)) - \
                       (sum(i['pnl'] for i in conflicts) / len(conflicts))
        
        print(f"\n📈 Разница (Выровненные - Конфликты):")
        print(f"   Win Rate: {wr_diff:+.1f}%")
        print(f"   Avg PnL: {avg_pnl_diff:+.2f}%")

def main():
    print("\n" + "="*80)
    print("📊 АНАЛИЗ РЕАЛЬНЫХ РЕЗУЛЬТАТОВ ПО BTC BIAS")
    print("="*80)
    
    # Загрузка данных
    print("\n🔄 Загрузка данных...")
    signals = load_json_signals()
    print(f"✅ Загружено {len(signals)} сигналов из JSON")
    
    trades = parse_bot_logs()
    
    # Сопоставление
    print("\n🔗 Сопоставление сигналов с результатами...")
    matched = match_signals_with_results(signals, trades)
    
    if not matched:
        print("\n❌ Не удалось сопоставить данные!")
        return
    
    # Анализы
    analyze_by_bias_and_direction(matched)
    analyze_by_regime(matched)
    compare_conflicts_vs_aligned(matched)
    
    print("\n" + "="*80)
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
