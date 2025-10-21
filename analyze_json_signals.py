#!/usr/bin/env python3
"""
Полный анализ основных стратегий из JSON файла
"""

import json
from collections import defaultdict
from datetime import datetime

def load_signals(json_file):
    """Загрузить сигналы из JSON"""
    with open(json_file, 'r', encoding='utf-8') as f:
        signals = json.load(f)
    
    # Парсим meta_data из строки в dict
    for signal in signals:
        if signal.get('meta_data') and isinstance(signal['meta_data'], str):
            try:
                signal['meta_data'] = json.loads(signal['meta_data'])
            except:
                signal['meta_data'] = {}
    
    return signals

def analyze_strategies(signals):
    """Анализ по каждой стратегии"""
    strategies_map = {
        949095948: 'Break & Retest',
        2063993909: 'Liquidity Sweep',
        1792560554: 'MA/VWAP Pullback',
        1460278342: 'Order Flow',
        1844580909: 'Volume Profile',
        773958525: 'ATR Momentum'
    }
    
    stats = {}
    
    for strategy_id, strategy_name in strategies_map.items():
        strategy_signals = [s for s in signals if s['strategy_id'] == strategy_id]
        
        if not strategy_signals:
            stats[strategy_name] = {'count': 0, 'active': False}
            continue
        
        closed = [s for s in strategy_signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
        active = [s for s in strategy_signals if s['status'] == 'ACTIVE']
        
        if not closed:
            stats[strategy_name] = {
                'count': len(strategy_signals),
                'active': True,
                'closed': 0,
                'active_count': len(active)
            }
            continue
        
        wins = [s for s in closed if s['pnl_percent'] > 0]
        losses = [s for s in closed if s['pnl_percent'] <= 0]
        
        win_rate = (len(wins) / len(closed) * 100) if closed else 0
        avg_win = sum(s['pnl_percent'] for s in wins) / len(wins) if wins else 0
        avg_loss = sum(s['pnl_percent'] for s in losses) / len(losses) if losses else 0
        total_pnl = sum(s['pnl_percent'] for s in closed)
        avg_pnl = total_pnl / len(closed) if closed else 0
        
        profit_factor = abs(sum(s['pnl_percent'] for s in wins) / sum(s['pnl_percent'] for s in losses)) if losses and wins else 0
        
        stats[strategy_name] = {
            'count': len(strategy_signals),
            'active': True,
            'closed': len(closed),
            'active_count': len(active),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'profit_factor': profit_factor,
            'best_trade': max((s['pnl_percent'] for s in closed), default=0),
            'worst_trade': min((s['pnl_percent'] for s in closed), default=0)
        }
    
    return stats

def analyze_by_regime(signals):
    """Анализ по рыночным режимам"""
    closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
    
    regimes = defaultdict(list)
    for signal in closed:
        regimes[signal['market_regime']].append(signal)
    
    stats = {}
    for regime, regime_signals in regimes.items():
        wins = [s for s in regime_signals if s['pnl_percent'] > 0]
        
        total_pnl = sum(s['pnl_percent'] for s in regime_signals)
        avg_pnl = total_pnl / len(regime_signals)
        
        stats[regime] = {
            'count': len(regime_signals),
            'wins': len(wins),
            'losses': len(regime_signals) - len(wins),
            'win_rate': (len(wins) / len(regime_signals) * 100),
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl
        }
    
    return stats

def analyze_by_bias(signals):
    """Анализ по BTC bias"""
    closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
    
    bias_groups = defaultdict(list)
    for signal in closed:
        meta = signal.get('meta_data') or {}
        bias = meta.get('bias', 'unknown')
        bias_groups[bias].append(signal)
    
    stats = {}
    for bias, bias_signals in bias_groups.items():
        wins = [s for s in bias_signals if s['pnl_percent'] > 0]
        
        total_pnl = sum(s['pnl_percent'] for s in bias_signals)
        avg_pnl = total_pnl / len(bias_signals)
        
        stats[bias] = {
            'count': len(bias_signals),
            'wins': len(wins),
            'win_rate': (len(wins) / len(bias_signals) * 100),
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl
        }
    
    return stats

def analyze_by_direction(signals):
    """Анализ по направлениям"""
    closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
    
    directions = defaultdict(list)
    for signal in closed:
        directions[signal['direction']].append(signal)
    
    stats = {}
    for direction, dir_signals in directions.items():
        wins = [s for s in dir_signals if s['pnl_percent'] > 0]
        
        total_pnl = sum(s['pnl_percent'] for s in dir_signals)
        avg_pnl = total_pnl / len(dir_signals)
        
        stats[direction] = {
            'count': len(dir_signals),
            'wins': len(wins),
            'win_rate': (len(wins) / len(dir_signals) * 100),
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl
        }
    
    return stats

def analyze_exit_types(signals):
    """Анализ по типам выхода"""
    closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
    
    exit_types = defaultdict(list)
    for signal in closed:
        exit_type = signal.get('exit_type') or 'UNKNOWN'
        exit_types[exit_type].append(signal)
    
    stats = {}
    for exit_type, type_signals in exit_types.items():
        wins = [s for s in type_signals if s['pnl_percent'] > 0]
        
        total_pnl = sum(s['pnl_percent'] for s in type_signals)
        avg_pnl = total_pnl / len(type_signals)
        
        stats[exit_type] = {
            'count': len(type_signals),
            'wins': len(wins),
            'win_rate': (len(wins) / len(type_signals) * 100),
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl
        }
    
    return stats

def analyze_volume_ratio(signals):
    """Анализ volume ratio"""
    closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
    
    volume_groups = {
        '< 1.0x': [],
        '1.0-1.5x': [],
        '1.5-2.0x': [],
        '> 2.0x': []
    }
    
    for signal in closed:
        meta = signal.get('meta_data') or {}
        vol_ratio = meta.get('volume_ratio', 1.0)
        
        if vol_ratio < 1.0:
            volume_groups['< 1.0x'].append(signal)
        elif vol_ratio < 1.5:
            volume_groups['1.0-1.5x'].append(signal)
        elif vol_ratio < 2.0:
            volume_groups['1.5-2.0x'].append(signal)
        else:
            volume_groups['> 2.0x'].append(signal)
    
    stats = {}
    for level, vol_signals in volume_groups.items():
        if not vol_signals:
            continue
        
        wins = [s for s in vol_signals if s['pnl_percent'] > 0]
        
        stats[level] = {
            'count': len(vol_signals),
            'win_rate': (len(wins) / len(vol_signals) * 100),
            'avg_pnl': sum(s['pnl_percent'] for s in vol_signals) / len(vol_signals)
        }
    
    return stats

def analyze_score_distribution(signals):
    """Анализ распределения score"""
    closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
    
    score_groups = {
        '< 3.0': [],
        '3.0-5.0': [],
        '5.0-7.0': [],
        '7.0-10.0': [],
        '> 10.0': []
    }
    
    for signal in closed:
        score = signal['score']
        
        if score < 3.0:
            score_groups['< 3.0'].append(signal)
        elif score < 5.0:
            score_groups['3.0-5.0'].append(signal)
        elif score < 7.0:
            score_groups['5.0-7.0'].append(signal)
        elif score < 10.0:
            score_groups['7.0-10.0'].append(signal)
        else:
            score_groups['> 10.0'].append(signal)
    
    stats = {}
    for range_name, score_signals in score_groups.items():
        if not score_signals:
            continue
        
        wins = [s for s in score_signals if s['pnl_percent'] > 0]
        
        stats[range_name] = {
            'count': len(score_signals),
            'win_rate': (len(wins) / len(score_signals) * 100),
            'avg_pnl': sum(s['pnl_percent'] for s in score_signals) / len(score_signals)
        }
    
    return stats

def get_top_trades(signals, n=10):
    """Топ сделок"""
    closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
    sorted_signals = sorted(closed, key=lambda x: x['pnl_percent'], reverse=True)
    
    return {
        'best': sorted_signals[:n],
        'worst': sorted_signals[-n:][::-1]
    }

def find_common_factors(signals, condition_func, name):
    """Найти общие факторы для группы сделок"""
    filtered = [s for s in signals if condition_func(s)]
    
    if not filtered:
        return None
    
    # Анализ общих характеристик
    regimes = defaultdict(int)
    biases = defaultdict(int)
    exits = defaultdict(int)
    strategies = defaultdict(int)
    
    for signal in filtered:
        regimes[signal['market_regime']] += 1
        exits[signal.get('exit_type', 'UNKNOWN')] += 1
        strategies[signal['strategy_name']] += 1
        
        meta = signal.get('meta_data') or {}
        biases[meta.get('bias', 'unknown')] += 1
    
    return {
        'count': len(filtered),
        'regimes': dict(regimes),
        'biases': dict(biases),
        'exits': dict(exits),
        'strategies': dict(strategies)
    }

def main():
    print("\n" + "="*80)
    print("📊 ПОЛНЫЙ АНАЛИЗ ОСНОВНЫХ СТРАТЕГИЙ")
    print("="*80)
    
    signals = load_signals('attached_assets/main_strategies_export_1761073131225.json')
    
    print(f"\n📈 КРАТКАЯ СВОДКА")
    print(f"="*80)
    
    closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
    active = [s for s in signals if s['status'] == 'ACTIVE']
    wins = [s for s in closed if s['pnl_percent'] > 0]
    losses = [s for s in closed if s['pnl_percent'] <= 0]
    
    total_pnl = sum(s['pnl_percent'] for s in closed)
    win_rate = (len(wins) / len(closed) * 100) if closed else 0
    avg_pnl = total_pnl / len(closed) if closed else 0
    
    print(f"Всего сигналов: {len(signals)}")
    print(f"Активных: {len(active)}")
    print(f"Закрытых: {len(closed)}")
    print(f"Побед: {len(wins)} ({win_rate:.1f}%)")
    print(f"Убытков: {len(losses)} ({100-win_rate:.1f}%)")
    print(f"Суммарный PnL: {total_pnl:+.2f}%")
    print(f"Средний PnL: {avg_pnl:+.2f}%")
    
    if wins:
        avg_win = sum(s['pnl_percent'] for s in wins) / len(wins)
        print(f"Средняя победа: {avg_win:+.2f}%")
    
    if losses:
        avg_loss = sum(s['pnl_percent'] for s in losses) / len(losses)
        print(f"Средний убыток: {avg_loss:+.2f}%")
    
    if wins and losses:
        profit_factor = abs(sum(s['pnl_percent'] for s in wins) / sum(s['pnl_percent'] for s in losses))
        print(f"Profit Factor: {profit_factor:.2f}")
    
    if closed:
        best = max(closed, key=lambda x: x['pnl_percent'])
        worst = min(closed, key=lambda x: x['pnl_percent'])
        print(f"\nЛучшая сделка: {best['symbol']} {best['direction']} {best['pnl_percent']:+.2f}%")
        print(f"Худшая сделка: {worst['symbol']} {worst['direction']} {worst['pnl_percent']:+.2f}%")
    
    # Анализ по стратегиям
    print(f"\n\n📊 АНАЛИЗ ПО СТРАТЕГИЯМ")
    print(f"="*80)
    
    strategy_stats = analyze_strategies(signals)
    
    print(f"\n{'Стратегия':<25} {'Всего':<8} {'Закр.':<8} {'Актив.':<8} {'WR%':<8} {'PnL%':<10} {'PF':<8} {'Статус'}")
    print(f"-"*90)
    
    for strategy_name, stats in strategy_stats.items():
        if stats['count'] == 0:
            print(f"{strategy_name:<25} {0:<8} {0:<8} {0:<8} {'-':<8} {'-':<10} {'-':<8} ❌ НЕ РАБОТАЕТ")
        elif stats['closed'] == 0:
            print(f"{strategy_name:<25} {stats['count']:<8} {0:<8} {stats.get('active_count', 0):<8} {'-':<8} {'-':<10} {'-':<8} ⚠️ НЕТ ЗАКРЫТЫХ")
        else:
            wr = f"{stats['win_rate']:.1f}"
            pnl = f"{stats['total_pnl']:+.2f}"
            pf = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] > 0 else "-"
            status = "✅" if stats['win_rate'] >= 50 else "⚠️" if stats['win_rate'] >= 35 else "❌"
            print(f"{strategy_name:<25} {stats['count']:<8} {stats['closed']:<8} {stats.get('active_count', 0):<8} {wr:<8} {pnl:<10} {pf:<8} {status}")
    
    # Детальная статистика по активным стратегиям
    print(f"\n\n📈 ДЕТАЛЬНАЯ СТАТИСТИКА СТРАТЕГИЙ")
    print(f"="*80)
    
    for strategy_name, stats in strategy_stats.items():
        if stats['count'] > 0 and stats.get('closed', 0) > 0:
            print(f"\n🔹 {strategy_name}:")
            print(f"   Всего сигналов: {stats['count']}")
            print(f"   Закрыто: {stats['closed']} | Активных: {stats.get('active_count', 0)}")
            print(f"   Побед: {stats['wins']} / Убытков: {stats['losses']}")
            print(f"   Win Rate: {stats['win_rate']:.1f}%")
            print(f"   Средняя победа: {stats['avg_win']:+.2f}%")
            print(f"   Средний убыток: {stats['avg_loss']:+.2f}%")
            print(f"   Суммарный PnL: {stats['total_pnl']:+.2f}%")
            print(f"   Средний PnL: {stats['avg_pnl']:+.2f}%")
            print(f"   Profit Factor: {stats['profit_factor']:.2f}")
            print(f"   Лучшая: {stats['best_trade']:+.2f}% | Худшая: {stats['worst_trade']:+.2f}%")
    
    # Анализ по режимам
    print(f"\n\n🌊 АНАЛИЗ ПО РЫНОЧНЫМ РЕЖИМАМ")
    print(f"="*80)
    
    regime_stats = analyze_by_regime(signals)
    
    print(f"\n{'Режим':<15} {'Сделок':<10} {'Побед':<10} {'WR%':<10} {'Total PnL%':<12} {'Avg PnL%':<12} {'Оценка'}")
    print(f"-"*85)
    
    for regime, stats in sorted(regime_stats.items(), key=lambda x: x[1]['win_rate'], reverse=True):
        rating = "✅ ОТЛИЧНО" if stats['win_rate'] >= 50 else "⚠️ СРЕДНЕ" if stats['win_rate'] >= 35 else "❌ ПЛОХО"
        print(f"{regime:<15} {stats['count']:<10} {stats['wins']:<10} {stats['win_rate']:<10.1f} {stats['total_pnl']:<+12.2f} {stats['avg_pnl']:<+12.2f} {rating}")
    
    # Анализ по BTC bias
    print(f"\n\n📉 АНАЛИЗ ПО BTC BIAS")
    print(f"="*80)
    
    bias_stats = analyze_by_bias(signals)
    
    print(f"\n{'Bias':<15} {'Сделок':<10} {'Побед':<10} {'WR%':<10} {'Total PnL%':<12} {'Avg PnL%':<12} {'Оценка'}")
    print(f"-"*85)
    
    for bias, stats in sorted(bias_stats.items(), key=lambda x: x[1]['avg_pnl'], reverse=True):
        rating = "✅" if stats['avg_pnl'] > 0 else "❌"
        print(f"{bias:<15} {stats['count']:<10} {stats['wins']:<10} {stats['win_rate']:<10.1f} {stats['total_pnl']:<+12.2f} {stats['avg_pnl']:<+12.2f} {rating}")
    
    # Анализ по направлениям
    print(f"\n\n🎯 АНАЛИЗ ПО НАПРАВЛЕНИЯМ")
    print(f"="*80)
    
    direction_stats = analyze_by_direction(signals)
    
    for direction, stats in direction_stats.items():
        print(f"\n{direction}:")
        print(f"   Сделок: {stats['count']}")
        print(f"   Побед: {stats['wins']} ({stats['win_rate']:.1f}%)")
        print(f"   Суммарный PnL: {stats['total_pnl']:+.2f}%")
        print(f"   Средний PnL: {stats['avg_pnl']:+.2f}%")
    
    # Анализ по типам выхода
    print(f"\n\n🚪 АНАЛИЗ ПО ТИПАМ ВЫХОДА")
    print(f"="*80)
    
    exit_stats = analyze_exit_types(signals)
    
    print(f"\n{'Тип выхода':<15} {'Количество':<12} {'WR%':<10} {'Avg PnL%':<12} {'Total PnL%':<12} {'Оценка'}")
    print(f"-"*80)
    
    for exit_type, stats in sorted(exit_stats.items(), key=lambda x: x[1]['avg_pnl'], reverse=True):
        rating = "✅" if stats['avg_pnl'] > 0 else "❌"
        print(f"{exit_type:<15} {stats['count']:<12} {stats['win_rate']:<10.1f} {stats['avg_pnl']:<+12.2f} {stats['total_pnl']:<+12.2f} {rating}")
    
    # Volume Ratio
    print(f"\n\n📊 АНАЛИЗ VOLUME RATIO")
    print(f"="*80)
    
    volume_stats = analyze_volume_ratio(signals)
    
    print(f"\n{'Диапазон':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL%':<12}")
    print(f"-"*50)
    
    for level, stats in volume_stats.items():
        rating = "✅" if stats['avg_pnl'] > 0 else "❌"
        print(f"{level:<15} {stats['count']:<10} {stats['win_rate']:<10.1f} {stats['avg_pnl']:<+12.2f} {rating}")
    
    # Score Distribution
    print(f"\n\n📈 РАСПРЕДЕЛЕНИЕ SCORE")
    print(f"="*80)
    
    score_stats = analyze_score_distribution(signals)
    
    print(f"\n{'Score':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL%':<12}")
    print(f"-"*50)
    
    for score_range, stats in score_stats.items():
        rating = "✅" if stats['avg_pnl'] > 0 else "❌"
        print(f"{score_range:<15} {stats['count']:<10} {stats['win_rate']:<10.1f} {stats['avg_pnl']:<+12.2f} {rating}")
    
    # Топ сделок
    print(f"\n\n🏆 ТОП-10 ЛУЧШИХ СДЕЛОК")
    print(f"="*80)
    
    top_trades = get_top_trades(signals, 10)
    
    for i, signal in enumerate(top_trades['best'], 1):
        meta = signal.get('meta_data') or {}
        bias = meta.get('bias', 'unknown')
        vol_ratio = meta.get('volume_ratio', 1.0)
        
        print(f"\n{i}. {signal['symbol']} {signal['direction']} → {signal['pnl_percent']:+.2f}%")
        print(f"   Стратегия: {signal['strategy_name']} | Score: {signal['score']:.1f}")
        print(f"   Режим: {signal['market_regime']} | Bias: {bias} | Vol: {vol_ratio:.2f}x")
        print(f"   Exit: {signal.get('exit_type', 'UNKNOWN')}")
    
    print(f"\n\n💥 ТОП-10 ХУДШИХ СДЕЛОК")
    print(f"="*80)
    
    for i, signal in enumerate(top_trades['worst'], 1):
        meta = signal.get('meta_data') or {}
        bias = meta.get('bias', 'unknown')
        vol_ratio = meta.get('volume_ratio', 1.0)
        
        print(f"\n{i}. {signal['symbol']} {signal['direction']} → {signal['pnl_percent']:+.2f}%")
        print(f"   Стратегия: {signal['strategy_name']} | Score: {signal['score']:.1f}")
        print(f"   Режим: {signal['market_regime']} | Bias: {bias} | Vol: {vol_ratio:.2f}x")
        print(f"   Exit: {signal.get('exit_type', 'UNKNOWN')}")
    
    # Анализ общих факторов
    print(f"\n\n🔍 АНАЛИЗ ОБЩИХ ФАКТОРОВ")
    print(f"="*80)
    
    # Факторы прибыльных сделок
    profitable = find_common_factors(
        closed,
        lambda s: s['pnl_percent'] > 0,
        "Прибыльные сделки"
    )
    
    if profitable:
        print(f"\n✅ ПРИБЫЛЬНЫЕ СДЕЛКИ ({profitable['count']} шт):")
        print(f"   Режимы: {profitable['regimes']}")
        print(f"   Bias: {profitable['biases']}")
        print(f"   Выходы: {profitable['exits']}")
        print(f"   Стратегии: {profitable['strategies']}")
    
    # Факторы убыточных сделок
    losing = find_common_factors(
        closed,
        lambda s: s['pnl_percent'] <= 0,
        "Убыточные сделки"
    )
    
    if losing:
        print(f"\n❌ УБЫТОЧНЫЕ СДЕЛКИ ({losing['count']} шт):")
        print(f"   Режимы: {losing['regimes']}")
        print(f"   Bias: {losing['biases']}")
        print(f"   Выходы: {losing['exits']}")
        print(f"   Стратегии: {losing['strategies']}")
    
    print(f"\n\n{'='*80}")
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
