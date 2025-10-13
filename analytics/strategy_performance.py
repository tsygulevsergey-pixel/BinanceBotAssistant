"""
Анализ производительности стратегий
Показывает детальную статистику по каждой стратегии
"""
import os
import sys
from pathlib import Path

# Добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from src.database.models import Signal, ActionPriceSignal
from datetime import datetime, timedelta
import pytz

# Подключение к БД
engine = create_engine('sqlite:///trading_bot.db')
Session = sessionmaker(bind=engine)

def analyze_main_strategies(days=30):
    """Анализ основных стратегий за последние N дней"""
    session = Session()
    
    # Фильтр по времени
    cutoff_date = datetime.now(pytz.UTC) - timedelta(days=days)
    
    # Группировка по стратегиям
    strategies = session.query(Signal.strategy_name).distinct().all()
    
    print(f"\n{'='*80}")
    print(f"📊 АНАЛИЗ ПРОИЗВОДИТЕЛЬНОСТИ СТРАТЕГИЙ (последние {days} дней)")
    print(f"{'='*80}\n")
    
    results = []
    
    for (strategy_name,) in strategies:
        signals = session.query(Signal).filter(
            Signal.strategy_name == strategy_name,
            Signal.created_at >= cutoff_date,
            Signal.status.in_(['PROFIT', 'LOSS', 'BREAKEVEN'])
        ).all()
        
        if not signals:
            continue
            
        total = len(signals)
        wins = len([s for s in signals if s.pnl_percent and s.pnl_percent > 0])
        losses = len([s for s in signals if s.pnl_percent and s.pnl_percent <= 0])
        
        tp1_count = len([s for s in signals if s.exit_type == 'TP1'])
        tp2_count = len([s for s in signals if s.exit_type == 'TP2'])
        sl_count = len([s for s in signals if s.exit_type == 'SL'])
        
        # Средние значения
        avg_pnl = sum([s.pnl_percent for s in signals if s.pnl_percent]) / total if total > 0 else 0
        avg_win = sum([s.pnl_percent for s in signals if s.pnl_percent and s.pnl_percent > 0]) / wins if wins > 0 else 0
        avg_loss = sum([s.pnl_percent for s in signals if s.pnl_percent and s.pnl_percent <= 0]) / losses if losses > 0 else 0
        
        win_rate = (wins / total * 100) if total > 0 else 0
        
        # Расчет expectancy (матожидание)
        expectancy = (win_rate/100 * avg_win) + ((100-win_rate)/100 * avg_loss)
        
        results.append({
            'name': strategy_name,
            'total': total,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'tp1': tp1_count,
            'tp2': tp2_count,
            'sl': sl_count,
            'expectancy': expectancy
        })
    
    # Сортировка по expectancy (лучшие сверху)
    results.sort(key=lambda x: x['expectancy'], reverse=True)
    
    # Вывод таблицы
    print(f"{'Стратегия':<30} {'Сигн':<6} {'WR%':<7} {'Avg PnL':<9} {'Avg Win':<9} {'Avg Loss':<10} {'TP1/TP2/SL':<12} {'Expect':<7}")
    print(f"{'-'*115}")
    
    for r in results:
        status = "🟢" if r['expectancy'] > 0.3 else "🟡" if r['expectancy'] > 0 else "🔴"
        print(f"{status} {r['name']:<28} {r['total']:<6} {r['win_rate']:<6.1f}% {r['avg_pnl']:>+7.2f}% {r['avg_win']:>+7.2f}% {r['avg_loss']:>+8.2f}% {r['tp1']}/{r['tp2']}/{r['sl']:<9} {r['expectancy']:>+6.2f}%")
    
    print(f"\n{'='*80}")
    print("🟢 Отлично (Expectancy > 0.3%)  🟡 Норма (0% < E < 0.3%)  🔴 Плохо (E < 0%)")
    print(f"{'='*80}\n")
    
    session.close()
    return results

def show_worst_performers(results, count=3):
    """Показать худшие стратегии и причины"""
    worst = sorted(results, key=lambda x: x['expectancy'])[:count]
    
    print(f"\n{'='*80}")
    print(f"🔴 ТОП-{count} ХУДШИХ СТРАТЕГИЙ И ЧТО ИСПРАВИТЬ:")
    print(f"{'='*80}\n")
    
    for i, r in enumerate(worst, 1):
        print(f"{i}. {r['name']}")
        print(f"   Expectancy: {r['expectancy']:+.2f}% | Win Rate: {r['win_rate']:.1f}% | Avg PnL: {r['avg_pnl']:+.2f}%")
        
        # Диагностика проблем
        problems = []
        fixes = []
        
        if r['win_rate'] < 40:
            problems.append("❌ Низкий винрейт (<40%)")
            fixes.append("   → Ужесточить фильтры (ADX, ATR, BBW)")
            fixes.append("   → Увеличить min_score в config.yaml")
            fixes.append("   → Проверить условия входа стратегии")
        
        if r['avg_loss'] < -1.5:
            problems.append("❌ Большие убытки")
            fixes.append("   → Уменьшить max_risk_percent в config.yaml")
            fixes.append("   → Улучшить логику стоп-лоссов")
        
        if r['avg_win'] < 1.0:
            problems.append("❌ Маленькая средняя прибыль")
            fixes.append("   → Проверить логику тейк-профитов")
            fixes.append("   → Рассмотреть trailing stop")
        
        if r['total'] < 5:
            problems.append("⚠️ Мало сигналов для анализа")
            fixes.append("   → Подождать больше данных (минимум 20-30 сигналов)")
        
        if r['sl'] > r['tp1'] + r['tp2']:
            problems.append("❌ Больше SL чем TP")
            fixes.append("   → Пересмотреть логику входа и фильтры")
        
        if problems:
            print(f"\n   Проблемы:")
            for p in problems:
                print(f"   {p}")
            print(f"\n   Что исправить:")
            for f in fixes:
                print(f"   {f}")
        else:
            print(f"   ℹ️ Недостаточно данных для диагностики")
        
        print()

def show_best_performers(results, count=3):
    """Показать лучшие стратегии"""
    best = sorted(results, key=lambda x: x['expectancy'], reverse=True)[:count]
    
    print(f"\n{'='*80}")
    print(f"🟢 ТОП-{count} ЛУЧШИХ СТРАТЕГИЙ:")
    print(f"{'='*80}\n")
    
    for i, r in enumerate(best, 1):
        print(f"{i}. {r['name']}")
        print(f"   ✅ Expectancy: {r['expectancy']:+.2f}% | Win Rate: {r['win_rate']:.1f}% | Avg PnL: {r['avg_pnl']:+.2f}%")
        print(f"   📊 TP1: {r['tp1']} | TP2: {r['tp2']} | SL: {r['sl']}")
        print()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Анализ производительности стратегий')
    parser.add_argument('--days', type=int, default=30, help='Количество дней для анализа (по умолчанию 30)')
    args = parser.parse_args()
    
    results = analyze_main_strategies(days=args.days)
    
    if results:
        show_best_performers(results, count=3)
        show_worst_performers(results, count=3)
        
        print(f"\n💡 ОБЩИЕ РЕКОМЕНДАЦИИ:")
        print(f"   1. Стратегии с Expectancy < 0% → отключить (enabled: false в config.yaml)")
        print(f"   2. Стратегии с WR < 35% → проверить фильтры и условия входа")
        print(f"   3. Если много SL → ужесточить min_score или добавить фильтры")
        print(f"   4. Минимум 20-30 сигналов для достоверных выводов")
        print(f"\n   📝 Настройки в config.yaml:")
        print(f"      - min_score: порог оценки сигнала (выше = меньше сигналов, но качественнее)")
        print(f"      - enabled: включить/выключить стратегию")
        print(f"      - max_risk_percent: максимальный риск на сделку\n")
    else:
        print("⚠️ Нет закрытых сигналов для анализа")
