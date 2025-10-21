#!/usr/bin/env python3
"""
Углубленный анализ корреляций:
- Score vs PnL
- Стратегия vs Exit Type (SL/TP2)
- Режим vs Win Rate
- BTC Bias vs Результат
"""

import json
import re
from pathlib import Path
from collections import defaultdict

def load_json_signals():
    """Загрузить сигналы из JSON"""
    with open('attached_assets/main_strategies_export_1761073131225.json', 'r', encoding='utf-8') as f:
        signals = json.load(f)
    
    # Парсим meta_data
    for signal in signals:
        if signal.get('meta_data') and isinstance(signal['meta_data'], str):
            try:
                signal['meta_data'] = json.loads(signal['meta_data'])
            except:
                signal['meta_data'] = {}
    
    return signals

def analyze_score_vs_status(signals):
    """Анализ корреляции Score с результатом"""
    print("\n" + "="*80)
    print("📊 АНАЛИЗ: SCORE vs РЕЗУЛЬТАТ")
    print("="*80)
    
    # Группировка по score диапазонам
    score_groups = {
        '< 3.0': [],
        '3.0-5.0': [],
        '5.0-7.0': [],
        '7.0-10.0': [],
        '> 10.0': []
    }
    
    for signal in signals:
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
    
    print(f"\n{'Score диапазон':<20} {'Сигналов':<12} {'Активных':<12} {'% от всех'}")
    print("-"*60)
    
    for score_range, sigs in score_groups.items():
        active = len([s for s in sigs if s['status'] == 'ACTIVE'])
        percentage = (len(sigs) / len(signals) * 100) if signals else 0
        
        print(f"{score_range:<20} {len(sigs):<12} {active:<12} {percentage:.1f}%")
    
    # Статистика по score
    scores = [s['score'] for s in signals]
    
    print(f"\n📈 Статистика Score:")
    print(f"   Минимальный: {min(scores):.2f}")
    print(f"   Максимальный: {max(scores):.2f}")
    print(f"   Средний: {sum(scores)/len(scores):.2f}")
    print(f"   Медиана: {sorted(scores)[len(scores)//2]:.2f}")
    
    # Анализ по стратегиям
    strategies_map = {
        949095948: 'Break & Retest',
        2063993909: 'Liquidity Sweep',
        1792560554: 'MA/VWAP Pullback'
    }
    
    print(f"\n📊 Score по стратегиям:")
    print(f"{'Стратегия':<25} {'Avg Score':<12} {'Min':<10} {'Max'}")
    print("-"*65)
    
    for strategy_id, strategy_name in strategies_map.items():
        strategy_sigs = [s for s in signals if s['strategy_id'] == strategy_id]
        if not strategy_sigs:
            continue
        
        strategy_scores = [s['score'] for s in strategy_sigs]
        avg_score = sum(strategy_scores) / len(strategy_scores)
        
        print(f"{strategy_name:<25} {avg_score:<12.2f} {min(strategy_scores):<10.2f} {max(strategy_scores):.2f}")

def analyze_by_strategy(signals):
    """Анализ по стратегиям"""
    print("\n" + "="*80)
    print("📊 АНАЛИЗ ПО СТРАТЕГИЯМ")
    print("="*80)
    
    strategies_map = {
        949095948: 'Break & Retest',
        2063993909: 'Liquidity Sweep',
        1792560554: 'MA/VWAP Pullback',
        1460278342: 'Order Flow',
        1844580909: 'Volume Profile',
        773958525: 'ATR Momentum'
    }
    
    print(f"\n{'Стратегия':<25} {'Сигналов':<12} {'Активных':<12} {'% от всех':<12} {'Avg Score'}")
    print("-"*80)
    
    for strategy_id, strategy_name in strategies_map.items():
        strategy_sigs = [s for s in signals if s['strategy_id'] == strategy_id]
        
        if not strategy_sigs:
            print(f"{strategy_name:<25} {0:<12} {0:<12} {0:<12} {'-'}")
            continue
        
        active = len([s for s in strategy_sigs if s['status'] == 'ACTIVE'])
        percentage = (len(strategy_sigs) / len(signals) * 100)
        scores = [s['score'] for s in strategy_sigs]
        avg_score = sum(scores) / len(scores)
        
        print(f"{strategy_name:<25} {len(strategy_sigs):<12} {active:<12} {percentage:<12.1f} {avg_score:.2f}")

def analyze_by_regime(signals):
    """Анализ по режимам"""
    print("\n" + "="*80)
    print("🌊 АНАЛИЗ ПО РЫНОЧНЫМ РЕЖИМАМ")
    print("="*80)
    
    regime_groups = defaultdict(list)
    for signal in signals:
        regime_groups[signal['market_regime']].append(signal)
    
    print(f"\n{'Режим':<20} {'Сигналов':<12} {'% от всех':<12} {'Avg Score':<12} {'Оценка'}")
    print("-"*75)
    
    for regime, sigs in sorted(regime_groups.items(), key=lambda x: len(x[1]), reverse=True):
        percentage = (len(sigs) / len(signals) * 100)
        scores = [s['score'] for s in sigs]
        avg_score = sum(scores) / len(scores)
        
        rating = "✅" if len(sigs) > 50 else "⚠️" if len(sigs) > 20 else "❌"
        
        print(f"{regime:<20} {len(sigs):<12} {percentage:<12.1f} {avg_score:<12.2f} {rating}")
    
    # Детальная статистика по режимам
    print(f"\n📊 Детальная статистика по режимам:")
    
    for regime, sigs in sorted(regime_groups.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"\n🔹 {regime} ({len(sigs)} сигналов):")
        
        # По направлениям
        long_sigs = [s for s in sigs if s['direction'] == 'LONG']
        short_sigs = [s for s in sigs if s['direction'] == 'SHORT']
        
        print(f"   LONG: {len(long_sigs)} ({len(long_sigs)/len(sigs)*100:.1f}%)")
        print(f"   SHORT: {len(short_sigs)} ({len(short_sigs)/len(sigs)*100:.1f}%)")
        
        # По стратегиям
        strategy_counts = defaultdict(int)
        strategies_map = {
            949095948: 'Break & Retest',
            2063993909: 'Liquidity Sweep',
            1792560554: 'MA/VWAP Pullback'
        }
        
        for sig in sigs:
            strategy_name = strategies_map.get(sig['strategy_id'], 'Unknown')
            strategy_counts[strategy_name] += 1
        
        print(f"   Стратегии:")
        for strategy, count in sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True):
            if count > 0:
                print(f"      {strategy}: {count}")

def analyze_by_bias(signals):
    """Анализ по BTC bias"""
    print("\n" + "="*80)
    print("📉 АНАЛИЗ ПО BTC BIAS")
    print("="*80)
    
    bias_groups = defaultdict(list)
    
    for signal in signals:
        meta = signal.get('meta_data') or {}
        bias = meta.get('bias', 'unknown')
        bias_groups[bias].append(signal)
    
    print(f"\n{'Bias':<20} {'Сигналов':<12} {'% от всех':<12} {'Avg Score':<12} {'Оценка'}")
    print("-"*75)
    
    for bias, sigs in sorted(bias_groups.items(), key=lambda x: len(x[1]), reverse=True):
        percentage = (len(sigs) / len(signals) * 100)
        scores = [s['score'] for s in sigs]
        avg_score = sum(scores) / len(scores)
        
        rating = "✅" if bias in ['neutral', 'bullish'] else "⚠️"
        
        print(f"{bias:<20} {len(sigs):<12} {percentage:<12.1f} {avg_score:<12.2f} {rating}")
    
    # Детальный анализ по bias и направлениям
    print(f"\n📊 Распределение LONG/SHORT по bias:")
    
    print(f"\n{'Bias':<20} {'LONG':<15} {'SHORT':<15} {'Конфликтов'}")
    print("-"*65)
    
    for bias, sigs in sorted(bias_groups.items(), key=lambda x: len(x[1]), reverse=True):
        long_sigs = [s for s in sigs if s['direction'] == 'LONG']
        short_sigs = [s for s in sigs if s['direction'] == 'SHORT']
        
        # Конфликты: LONG при bearish или SHORT при bullish
        conflicts = 0
        if bias == 'bearish':
            conflicts = len(long_sigs)
        elif bias == 'bullish':
            conflicts = len(short_sigs)
        
        conflict_rate = f"{conflicts} ({conflicts/len(sigs)*100:.1f}%)" if conflicts > 0 else "-"
        
        print(f"{bias:<20} {len(long_sigs):<15} {len(short_sigs):<15} {conflict_rate}")

def analyze_volume_ratio(signals):
    """Анализ volume ratio"""
    print("\n" + "="*80)
    print("📊 АНАЛИЗ VOLUME RATIO")
    print("="*80)
    
    volume_groups = {
        '< 1.0x': [],
        '1.0-1.5x': [],
        '1.5-2.0x': [],
        '2.0-3.0x': [],
        '> 3.0x': []
    }
    
    for signal in signals:
        meta = signal.get('meta_data') or {}
        vol_ratio = meta.get('volume_ratio', 1.0)
        
        if vol_ratio < 1.0:
            volume_groups['< 1.0x'].append(signal)
        elif vol_ratio < 1.5:
            volume_groups['1.0-1.5x'].append(signal)
        elif vol_ratio < 2.0:
            volume_groups['1.5-2.0x'].append(signal)
        elif vol_ratio < 3.0:
            volume_groups['2.0-3.0x'].append(signal)
        else:
            volume_groups['> 3.0x'].append(signal)
    
    print(f"\n{'Volume диапазон':<20} {'Сигналов':<12} {'% от всех':<12} {'Avg Score'}")
    print("-"*60)
    
    for vol_range, sigs in volume_groups.items():
        if not sigs:
            continue
        
        percentage = (len(sigs) / len(signals) * 100)
        scores = [s['score'] for s in sigs]
        avg_score = sum(scores) / len(scores)
        
        print(f"{vol_range:<20} {len(sigs):<12} {percentage:<12.1f} {avg_score:.2f}")
    
    # Статистика
    all_volumes = []
    for signal in signals:
        meta = signal.get('meta_data') or {}
        vol_ratio = meta.get('volume_ratio', 1.0)
        all_volumes.append(vol_ratio)
    
    if all_volumes:
        print(f"\n📈 Статистика Volume Ratio:")
        print(f"   Минимальный: {min(all_volumes):.2f}x")
        print(f"   Максимальный: {max(all_volumes):.2f}x")
        print(f"   Средний: {sum(all_volumes)/len(all_volumes):.2f}x")
        print(f"   Медиана: {sorted(all_volumes)[len(all_volumes)//2]:.2f}x")

def analyze_cvd_and_oi(signals):
    """Анализ CVD и OI"""
    print("\n" + "="*80)
    print("📊 АНАЛИЗ CVD И OPEN INTEREST")
    print("="*80)
    
    # CVD Direction
    cvd_groups = defaultdict(list)
    
    for signal in signals:
        meta = signal.get('meta_data') or {}
        cvd_dir = meta.get('cvd_direction', 'Unknown')
        cvd_groups[cvd_dir].append(signal)
    
    print(f"\n🔸 CVD Direction:")
    print(f"{'CVD':<20} {'Сигналов':<12} {'% от всех'}")
    print("-"*50)
    
    for cvd_dir, sigs in sorted(cvd_groups.items(), key=lambda x: len(x[1]), reverse=True):
        percentage = (len(sigs) / len(signals) * 100)
        print(f"{cvd_dir:<20} {len(sigs):<12} {percentage:.1f}%")
    
    # OI Delta
    oi_values = []
    for signal in signals:
        meta = signal.get('meta_data') or {}
        oi_delta = meta.get('oi_delta_percent', 0)
        oi_values.append(oi_delta)
    
    if oi_values:
        positive_oi = len([v for v in oi_values if v > 0])
        negative_oi = len([v for v in oi_values if v < 0])
        zero_oi = len([v for v in oi_values if v == 0])
        
        print(f"\n🔸 Open Interest Delta:")
        print(f"   Позитивный: {positive_oi} ({positive_oi/len(oi_values)*100:.1f}%)")
        print(f"   Негативный: {negative_oi} ({negative_oi/len(oi_values)*100:.1f}%)")
        print(f"   Нулевой: {zero_oi} ({zero_oi/len(oi_values)*100:.1f}%)")
        
        non_zero = [v for v in oi_values if v != 0]
        if non_zero:
            print(f"   Средний (ненулевой): {sum(non_zero)/len(non_zero):.4f}%")

def main():
    print("\n" + "="*80)
    print("📊 УГЛУБЛЕННЫЙ АНАЛИЗ КОРРЕЛЯЦИЙ")
    print("="*80)
    
    signals = load_json_signals()
    
    print(f"\n📈 Общая информация:")
    print(f"   Всего сигналов: {len(signals)}")
    print(f"   Активных: {len([s for s in signals if s['status'] == 'ACTIVE'])}")
    print(f"   Закрытых: {len([s for s in signals if s['status'] == 'CLOSED'])}")
    
    # Основные анализы
    analyze_score_vs_status(signals)
    analyze_by_strategy(signals)
    analyze_by_regime(signals)
    analyze_by_bias(signals)
    analyze_volume_ratio(signals)
    analyze_cvd_and_oi(signals)
    
    print("\n" + "="*80)
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
