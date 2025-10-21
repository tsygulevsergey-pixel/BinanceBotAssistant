#!/usr/bin/env python3
"""
ПОЛНЫЙ АНАЛИЗ ВСЕХ ФАКТОРОВ
Ищем РЕАЛЬНЫЕ причины SL и низкого WR
"""

import json
import re
from pathlib import Path
from collections import defaultdict
import statistics

def load_matched_data():
    """Загрузить и сопоставить все данные"""
    # Загрузка JSON
    with open('attached_assets/main_strategies_export_1761073131225.json', 'r', encoding='utf-8') as f:
        signals = json.load(f)
    
    for signal in signals:
        if signal.get('meta_data') and isinstance(signal['meta_data'], str):
            try:
                signal['meta_data'] = json.loads(signal['meta_data'])
            except:
                signal['meta_data'] = {}
    
    # Парсинг логов
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
                trades.append({
                    'symbol': match.group(1),
                    'direction': match.group(2),
                    'pnl': float(match.group(5)),
                    'exit_type': match.group(6)
                })
        except:
            pass
    
    # Сопоставление
    trades_index = defaultdict(list)
    for trade in trades:
        key = f"{trade['symbol']}_{trade['direction']}"
        trades_index[key].append(trade)
    
    matched = []
    for signal in signals:
        key = f"{signal['symbol']}_{signal['direction']}"
        
        if key in trades_index and len(trades_index[key]) > 0:
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
                'exit_type': trade['exit_type'],
                'is_win': trade['pnl'] > 0
            })
    
    return matched

def analyze_score_correlation(matched):
    """Анализ Score vs результат"""
    print("\n" + "="*80)
    print("📊 ФАКТОР #1: SCORE vs РЕЗУЛЬТАТ")
    print("="*80)
    
    # Группы по score
    score_groups = {
        '3.0-5.0': [],
        '5.0-7.0': [],
        '7.0-9.0': [],
        '9.0-11.0': [],
        '> 11.0': []
    }
    
    for item in matched:
        score = item['score']
        if score < 5.0:
            score_groups['3.0-5.0'].append(item)
        elif score < 7.0:
            score_groups['5.0-7.0'].append(item)
        elif score < 9.0:
            score_groups['7.0-9.0'].append(item)
        elif score < 11.0:
            score_groups['9.0-11.0'].append(item)
        else:
            score_groups['> 11.0'].append(item)
    
    print(f"\n{'Score':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'SL rate':<12} {'TP2 rate':<12} {'Оценка'}")
    print("-"*90)
    
    for score_range, items in score_groups.items():
        if not items:
            continue
        
        wr = len([i for i in items if i['is_win']]) / len(items) * 100
        avg_pnl = sum(i['pnl'] for i in items) / len(items)
        sl_rate = len([i for i in items if i['exit_type'] == 'SL']) / len(items) * 100
        tp2_rate = len([i for i in items if i['exit_type'] == 'TP2']) / len(items) * 100
        
        rating = "✅" if wr >= 55 else "⚠️" if wr >= 45 else "❌"
        
        print(f"{score_range:<15} {len(items):<10} {wr:<10.1f} {avg_pnl:<+12.2f} {sl_rate:<12.1f} {tp2_rate:<12.1f} {rating}")
    
    # Корреляция
    scores = [i['score'] for i in matched]
    pnls = [i['pnl'] for i in matched]
    
    avg_score_winners = statistics.mean([i['score'] for i in matched if i['is_win']])
    avg_score_losers = statistics.mean([i['score'] for i in matched if not i['is_win']])
    
    print(f"\n📈 Статистика:")
    print(f"   Средний Score победителей: {avg_score_winners:.2f}")
    print(f"   Средний Score проигравших: {avg_score_losers:.2f}")
    print(f"   Разница: {avg_score_winners - avg_score_losers:+.2f}")
    
    # Корреляция с SL
    sl_trades = [i for i in matched if i['exit_type'] == 'SL']
    tp2_trades = [i for i in matched if i['exit_type'] == 'TP2']
    
    if sl_trades and tp2_trades:
        avg_score_sl = statistics.mean([i['score'] for i in sl_trades])
        avg_score_tp2 = statistics.mean([i['score'] for i in tp2_trades])
        
        print(f"\n   Средний Score для SL: {avg_score_sl:.2f}")
        print(f"   Средний Score для TP2: {avg_score_tp2:.2f}")
        print(f"   Разница: {avg_score_tp2 - avg_score_sl:+.2f}")
        
        if avg_score_sl > avg_score_tp2:
            print(f"\n   ⚠️ ПАРАДОКС: SL имеет ВЫШЕ score чем TP2!")

def analyze_volume_correlation(matched):
    """Анализ Volume Ratio vs результат"""
    print("\n" + "="*80)
    print("📊 ФАКТОР #2: VOLUME RATIO vs РЕЗУЛЬТАТ")
    print("="*80)
    
    volume_groups = {
        '< 1.5x': [],
        '1.5-2.0x': [],
        '2.0-3.0x': [],
        '3.0-5.0x': [],
        '> 5.0x': []
    }
    
    for item in matched:
        vol = item['volume_ratio']
        if vol < 1.5:
            volume_groups['< 1.5x'].append(item)
        elif vol < 2.0:
            volume_groups['1.5-2.0x'].append(item)
        elif vol < 3.0:
            volume_groups['2.0-3.0x'].append(item)
        elif vol < 5.0:
            volume_groups['3.0-5.0x'].append(item)
        else:
            volume_groups['> 5.0x'].append(item)
    
    print(f"\n{'Volume':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'SL rate':<12} {'TP2 rate':<12} {'Оценка'}")
    print("-"*90)
    
    for vol_range, items in volume_groups.items():
        if not items:
            continue
        
        wr = len([i for i in items if i['is_win']]) / len(items) * 100
        avg_pnl = sum(i['pnl'] for i in items) / len(items)
        sl_rate = len([i for i in items if i['exit_type'] == 'SL']) / len(items) * 100
        tp2_rate = len([i for i in items if i['exit_type'] == 'TP2']) / len(items) * 100
        
        rating = "✅" if wr >= 55 else "⚠️" if wr >= 45 else "❌"
        
        print(f"{vol_range:<15} {len(items):<10} {wr:<10.1f} {avg_pnl:<+12.2f} {sl_rate:<12.1f} {tp2_rate:<12.1f} {rating}")
    
    # Статистика
    avg_vol_winners = statistics.mean([i['volume_ratio'] for i in matched if i['is_win']])
    avg_vol_losers = statistics.mean([i['volume_ratio'] for i in matched if not i['is_win']])
    
    sl_trades = [i for i in matched if i['exit_type'] == 'SL']
    tp2_trades = [i for i in matched if i['exit_type'] == 'TP2']
    
    avg_vol_sl = statistics.mean([i['volume_ratio'] for i in sl_trades])
    avg_vol_tp2 = statistics.mean([i['volume_ratio'] for i in tp2_trades])
    
    print(f"\n📈 Статистика:")
    print(f"   Средний Volume победителей: {avg_vol_winners:.2f}x")
    print(f"   Средний Volume проигравших: {avg_vol_losers:.2f}x")
    print(f"   Разница: {avg_vol_winners - avg_vol_losers:+.2f}x")
    print(f"\n   Средний Volume для SL: {avg_vol_sl:.2f}x")
    print(f"   Средний Volume для TP2: {avg_vol_tp2:.2f}x")
    print(f"   Разница: {avg_vol_tp2 - avg_vol_sl:+.2f}x")

def analyze_by_strategy(matched):
    """Анализ по стратегиям"""
    print("\n" + "="*80)
    print("📊 ФАКТОР #3: СТРАТЕГИЯ vs РЕЗУЛЬТАТ")
    print("="*80)
    
    strategies_map = {
        949095948: 'Break & Retest',
        2063993909: 'Liquidity Sweep',
        1792560554: 'MA/VWAP Pullback'
    }
    
    strategy_groups = defaultdict(list)
    for item in matched:
        strategy_name = strategies_map.get(item['strategy_id'], f"Unknown_{item['strategy_id']}")
        strategy_groups[strategy_name].append(item)
    
    print(f"\n{'Стратегия':<25} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'SL rate':<12} {'TP2 rate':<12} {'Оценка'}")
    print("-"*95)
    
    for strategy, items in sorted(strategy_groups.items(), key=lambda x: len(x[1]), reverse=True):
        if not items:
            continue
        
        wr = len([i for i in items if i['is_win']]) / len(items) * 100
        avg_pnl = sum(i['pnl'] for i in items) / len(items)
        sl_rate = len([i for i in items if i['exit_type'] == 'SL']) / len(items) * 100
        tp2_rate = len([i for i in items if i['exit_type'] == 'TP2']) / len(items) * 100
        
        rating = "✅" if wr >= 55 else "⚠️" if wr >= 45 else "❌"
        
        print(f"{strategy:<25} {len(items):<10} {wr:<10.1f} {avg_pnl:<+12.2f} {sl_rate:<12.1f} {tp2_rate:<12.1f} {rating}")
        
        # Детали для основной стратегии
        if strategy == 'Break & Retest':
            sl_count = len([i for i in items if i['exit_type'] == 'SL'])
            print(f"\n   📌 Break & Retest детали:")
            print(f"      Всего SL: {sl_count} из {len(items)} ({sl_rate:.1f}%)")
            print(f"      Это {sl_count / 84 * 100:.1f}% от всех 84 SL в системе")

def analyze_by_symbol(matched):
    """Анализ по символам - найти проблемные"""
    print("\n" + "="*80)
    print("📊 ФАКТОР #4: СИМВОЛЫ (ТОП ПРОБЛЕМНЫЕ)")
    print("="*80)
    
    symbol_groups = defaultdict(list)
    for item in matched:
        symbol_groups[item['symbol']].append(item)
    
    # Сортировка по SL rate
    symbol_stats = []
    for symbol, items in symbol_groups.items():
        if len(items) >= 2:  # Минимум 2 сделки
            wr = len([i for i in items if i['is_win']]) / len(items) * 100
            avg_pnl = sum(i['pnl'] for i in items) / len(items)
            sl_rate = len([i for i in items if i['exit_type'] == 'SL']) / len(items) * 100
            
            symbol_stats.append({
                'symbol': symbol,
                'count': len(items),
                'wr': wr,
                'avg_pnl': avg_pnl,
                'sl_rate': sl_rate
            })
    
    # ТОП по SL rate
    print(f"\n🔴 ТОП-15 СИМВОЛОВ С ВЫСОКИМ SL RATE:")
    print(f"\n{'Символ':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'SL rate':<12} {'Оценка'}")
    print("-"*75)
    
    sorted_by_sl = sorted(symbol_stats, key=lambda x: x['sl_rate'], reverse=True)[:15]
    for stat in sorted_by_sl:
        rating = "❌❌" if stat['sl_rate'] >= 60 else "❌" if stat['sl_rate'] >= 40 else "⚠️"
        print(f"{stat['symbol']:<15} {stat['count']:<10} {stat['wr']:<10.1f} {stat['avg_pnl']:<+12.2f} {stat['sl_rate']:<12.1f} {rating}")
    
    # ТОП по низкому WR
    print(f"\n\n🔴 ТОП-15 СИМВОЛОВ С НИЗКИМ WIN RATE:")
    print(f"\n{'Символ':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'SL rate':<12} {'Оценка'}")
    print("-"*75)
    
    sorted_by_wr = sorted(symbol_stats, key=lambda x: x['wr'])[:15]
    for stat in sorted_by_wr:
        rating = "❌❌" if stat['wr'] <= 30 else "❌" if stat['wr'] <= 40 else "⚠️"
        print(f"{stat['symbol']:<15} {stat['count']:<10} {stat['wr']:<10.1f} {stat['avg_pnl']:<+12.2f} {stat['sl_rate']:<12.1f} {rating}")
    
    # Лучшие символы для сравнения
    print(f"\n\n✅ ТОП-10 ЛУЧШИХ СИМВОЛОВ (для сравнения):")
    print(f"\n{'Символ':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL':<12} {'SL rate':<12} {'Оценка'}")
    print("-"*75)
    
    sorted_by_pnl = sorted(symbol_stats, key=lambda x: x['avg_pnl'], reverse=True)[:10]
    for stat in sorted_by_pnl:
        rating = "✅✅" if stat['wr'] >= 70 else "✅"
        print(f"{stat['symbol']:<15} {stat['count']:<10} {stat['wr']:<10.1f} {stat['avg_pnl']:<+12.2f} {stat['sl_rate']:<12.1f} {rating}")

def analyze_exit_types(matched):
    """Детальный анализ типов выходов"""
    print("\n" + "="*80)
    print("📊 АНАЛИЗ ТИПОВ ВЫХОДОВ")
    print("="*80)
    
    exit_groups = defaultdict(list)
    for item in matched:
        exit_groups[item['exit_type']].append(item)
    
    print(f"\n{'Exit Type':<15} {'Количество':<12} {'% от всех':<12} {'Avg PnL':<12} {'Total PnL':<12} {'Оценка'}")
    print("-"*80)
    
    total_trades = len(matched)
    
    for exit_type, items in sorted(exit_groups.items(), key=lambda x: len(x[1]), reverse=True):
        percentage = len(items) / total_trades * 100
        avg_pnl = sum(i['pnl'] for i in items) / len(items)
        total_pnl = sum(i['pnl'] for i in items)
        
        if exit_type == 'TP2':
            rating = "✅✅✅"
        elif exit_type == 'SL':
            rating = "❌❌❌"
        elif exit_type == 'BREAKEVEN':
            rating = "✅"
        else:
            rating = "⚠️"
        
        print(f"{exit_type:<15} {len(items):<12} {percentage:<12.1f} {avg_pnl:<+12.2f} {total_pnl:<+12.2f} {rating}")
    
    # Детали по SL
    if 'SL' in exit_groups:
        sl_items = exit_groups['SL']
        print(f"\n\n🔍 ДЕТАЛЬНЫЙ АНАЛИЗ SL ВЫХОДОВ ({len(sl_items)} сделок):")
        
        # По score
        avg_score = statistics.mean([i['score'] for i in sl_items])
        print(f"\n   Средний Score: {avg_score:.2f}")
        
        # По volume
        avg_vol = statistics.mean([i['volume_ratio'] for i in sl_items])
        print(f"   Средний Volume Ratio: {avg_vol:.2f}x")
        
        # По режимам
        regime_dist = defaultdict(int)
        for item in sl_items:
            regime_dist[item['regime']] += 1
        
        print(f"\n   Распределение по режимам:")
        for regime, count in sorted(regime_dist.items(), key=lambda x: x[1], reverse=True):
            print(f"      {regime}: {count} ({count/len(sl_items)*100:.1f}%)")
        
        # По bias
        bias_dist = defaultdict(int)
        for item in sl_items:
            bias_dist[item['bias']] += 1
        
        print(f"\n   Распределение по bias:")
        for bias, count in sorted(bias_dist.items(), key=lambda x: x[1], reverse=True):
            print(f"      {bias}: {count} ({count/len(sl_items)*100:.1f}%)")
        
        # По стратегиям
        strategies_map = {
            949095948: 'Break & Retest',
            2063993909: 'Liquidity Sweep',
            1792560554: 'MA/VWAP Pullback'
        }
        
        strategy_dist = defaultdict(int)
        for item in sl_items:
            strategy_name = strategies_map.get(item['strategy_id'], 'Unknown')
            strategy_dist[strategy_name] += 1
        
        print(f"\n   Распределение по стратегиям:")
        for strategy, count in sorted(strategy_dist.items(), key=lambda x: x[1], reverse=True):
            print(f"      {strategy}: {count} ({count/len(sl_items)*100:.1f}%)")

def find_correlation_patterns(matched):
    """Поиск паттернов корреляции"""
    print("\n" + "="*80)
    print("🔍 ПОИСК КОРРЕЛЯЦИОННЫХ ПАТТЕРНОВ")
    print("="*80)
    
    # Комбинации факторов для SL
    sl_trades = [i for i in matched if i['exit_type'] == 'SL']
    
    # Паттерн 1: Низкий score + Низкий volume
    pattern1 = [i for i in sl_trades if i['score'] < 6.0 and i['volume_ratio'] < 1.5]
    pattern1_rate = len(pattern1) / len(sl_trades) * 100 if sl_trades else 0
    
    # Паттерн 2: Высокий score + Низкий volume
    pattern2 = [i for i in sl_trades if i['score'] >= 8.0 and i['volume_ratio'] < 2.0]
    pattern2_rate = len(pattern2) / len(sl_trades) * 100 if sl_trades else 0
    
    # Паттерн 3: Squeeze + Break&Retest
    pattern3 = [i for i in sl_trades if i['regime'] == 'SQUEEZE' and i['strategy_id'] == 949095948]
    pattern3_rate = len(pattern3) / len(sl_trades) * 100 if sl_trades else 0
    
    # Паттерн 4: Trend + Break&Retest
    pattern4 = [i for i in sl_trades if i['regime'] == 'TREND' and i['strategy_id'] == 949095948]
    pattern4_rate = len(pattern4) / len(sl_trades) * 100 if sl_trades else 0
    
    print(f"\n📊 Паттерны в SL сделках:")
    print(f"\n   Паттерн 1: Score<6.0 + Volume<1.5x")
    print(f"      Количество: {len(pattern1)} ({pattern1_rate:.1f}% от всех SL)")
    
    print(f"\n   Паттерн 2: Score>=8.0 + Volume<2.0x (парадокс)")
    print(f"      Количество: {len(pattern2)} ({pattern2_rate:.1f}% от всех SL)")
    
    print(f"\n   Паттерн 3: SQUEEZE + Break&Retest")
    print(f"      Количество: {len(pattern3)} ({pattern3_rate:.1f}% от всех SL)")
    
    print(f"\n   Паттерн 4: TREND + Break&Retest")
    print(f"      Количество: {len(pattern4)} ({pattern4_rate:.1f}% от всех SL)")

def main():
    print("\n" + "="*80)
    print("🔍 ПОЛНЫЙ ФАКТОРНЫЙ АНАЛИЗ - ПОИСК ПРИЧИН SL")
    print("="*80)
    
    print("\n🔄 Загрузка и сопоставление данных...")
    matched = load_matched_data()
    print(f"✅ Загружено {len(matched)} сопоставленных сделок")
    
    # Общая статистика
    wins = len([i for i in matched if i['is_win']])
    wr = wins / len(matched) * 100
    avg_pnl = sum(i['pnl'] for i in matched) / len(matched)
    total_pnl = sum(i['pnl'] for i in matched)
    
    sl_count = len([i for i in matched if i['exit_type'] == 'SL'])
    sl_rate = sl_count / len(matched) * 100
    
    print(f"\n📈 Общая статистика:")
    print(f"   Win Rate: {wr:.1f}%")
    print(f"   Avg PnL: {avg_pnl:+.2f}%")
    print(f"   Total PnL: {total_pnl:+.2f}%")
    print(f"   SL Rate: {sl_rate:.1f}% ({sl_count} из {len(matched)})")
    
    # Анализы
    analyze_score_correlation(matched)
    analyze_volume_correlation(matched)
    analyze_by_strategy(matched)
    analyze_by_symbol(matched)
    analyze_exit_types(matched)
    find_correlation_patterns(matched)
    
    print("\n" + "="*80)
    print("✅ ПОЛНЫЙ АНАЛИЗ ЗАВЕРШЕН")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
