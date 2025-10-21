#!/usr/bin/env python3
"""
Полный анализ основных стратегий торгового бота
Анализирует все 6 стратегий: Liquidity Sweep, Break & Retest, Order Flow, 
MA/VWAP Pullback, Volume Profile, ATR Momentum
"""

import sqlite3
import json
from datetime import datetime, timedelta
from collections import defaultdict
import re
from pathlib import Path

class MainStrategiesAnalyzer:
    def __init__(self, db_path='trading_bot.db'):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        
        self.strategies = {
            0: 'Liquidity Sweep',
            1: 'Break & Retest',
            2: 'Order Flow',
            3: 'MA/VWAP Pullback',
            4: 'Volume Profile',
            5: 'ATR Momentum'
        }
        
    def get_all_signals(self):
        """Получить все сигналы основных стратегий"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 
                id, symbol, strategy_id, strategy_name, direction,
                entry_price, stop_loss, take_profit_1, take_profit_2,
                score, market_regime, timeframe,
                created_at, status,
                exit_price, exit_reason, exit_type,
                pnl, pnl_percent,
                tp1_hit, tp1_closed_at,
                tp2_hit, tp2_closed_at,
                max_favorable_excursion, max_adverse_excursion,
                meta_data,
                closed_at
            FROM signals
            WHERE strategy_name NOT LIKE '%Action Price%'
              AND strategy_name NOT LIKE '%V3%'
            ORDER BY created_at DESC
        """)
        
        signals = []
        for row in cursor.fetchall():
            signal = dict(row)
            if signal['meta_data']:
                try:
                    signal['meta_data'] = json.loads(signal['meta_data'])
                except:
                    signal['meta_data'] = {}
            signals.append(signal)
        
        return signals
    
    def analyze_by_strategy(self, signals):
        """Анализ по каждой стратегии"""
        stats = {}
        
        for strategy_id, strategy_name in self.strategies.items():
            strategy_signals = [s for s in signals if s['strategy_id'] == strategy_id]
            
            if not strategy_signals:
                stats[strategy_name] = {
                    'count': 0,
                    'active': False
                }
                continue
            
            closed = [s for s in strategy_signals if s['status'] == 'CLOSED']
            wins = [s for s in closed if s['pnl_percent'] and s['pnl_percent'] > 0]
            losses = [s for s in closed if s['pnl_percent'] and s['pnl_percent'] <= 0]
            
            win_rate = (len(wins) / len(closed) * 100) if closed else 0
            avg_win = sum(s['pnl_percent'] for s in wins) / len(wins) if wins else 0
            avg_loss = sum(s['pnl_percent'] for s in losses) / len(losses) if losses else 0
            total_pnl = sum(s['pnl_percent'] or 0 for s in closed)
            
            profit_factor = abs(sum(s['pnl_percent'] for s in wins) / sum(s['pnl_percent'] for s in losses)) if losses and wins else 0
            
            stats[strategy_name] = {
                'count': len(strategy_signals),
                'active': True,
                'closed': len(closed),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'total_pnl': total_pnl,
                'profit_factor': profit_factor,
                'best_trade': max((s['pnl_percent'] for s in closed if s['pnl_percent']), default=0),
                'worst_trade': min((s['pnl_percent'] for s in closed if s['pnl_percent']), default=0)
            }
        
        return stats
    
    def analyze_by_regime(self, signals):
        """Анализ по рыночным режимам"""
        closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
        
        regimes = {}
        for signal in closed:
            regime = signal['market_regime']
            if regime not in regimes:
                regimes[regime] = []
            regimes[regime].append(signal)
        
        stats = {}
        for regime, regime_signals in regimes.items():
            wins = [s for s in regime_signals if s['pnl_percent'] > 0]
            losses = [s for s in regime_signals if s['pnl_percent'] <= 0]
            
            win_rate = (len(wins) / len(regime_signals) * 100) if regime_signals else 0
            total_pnl = sum(s['pnl_percent'] for s in regime_signals)
            avg_pnl = total_pnl / len(regime_signals) if regime_signals else 0
            
            stats[regime] = {
                'count': len(regime_signals),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl
            }
        
        return stats
    
    def analyze_by_direction(self, signals):
        """Анализ по направлениям (LONG/SHORT)"""
        closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
        
        directions = {'LONG': [], 'SHORT': []}
        for signal in closed:
            directions[signal['direction']].append(signal)
        
        stats = {}
        for direction, dir_signals in directions.items():
            if not dir_signals:
                stats[direction] = {'count': 0}
                continue
                
            wins = [s for s in dir_signals if s['pnl_percent'] > 0]
            losses = [s for s in dir_signals if s['pnl_percent'] <= 0]
            
            win_rate = (len(wins) / len(dir_signals) * 100) if dir_signals else 0
            total_pnl = sum(s['pnl_percent'] for s in dir_signals)
            avg_pnl = total_pnl / len(dir_signals) if dir_signals else 0
            
            stats[direction] = {
                'count': len(dir_signals),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl
            }
        
        return stats
    
    def analyze_exit_types(self, signals):
        """Анализ по типам выхода"""
        closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
        
        exit_types = defaultdict(list)
        for signal in closed:
            exit_type = signal['exit_type'] or 'UNKNOWN'
            exit_types[exit_type].append(signal)
        
        stats = {}
        for exit_type, type_signals in exit_types.items():
            wins = [s for s in type_signals if s['pnl_percent'] > 0]
            total_pnl = sum(s['pnl_percent'] for s in type_signals)
            avg_pnl = total_pnl / len(type_signals) if type_signals else 0
            
            stats[exit_type] = {
                'count': len(type_signals),
                'wins': len(wins),
                'win_rate': (len(wins) / len(type_signals) * 100) if type_signals else 0,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl
            }
        
        return stats
    
    def analyze_metadata(self, signals):
        """Анализ метаданных (volume_ratio, bias, CVD, OI)"""
        closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
        
        # Группировка по bias
        bias_groups = defaultdict(list)
        for signal in closed:
            meta = signal.get('meta_data') or {}
            bias = meta.get('btc_bias', 'unknown')
            bias_groups[bias].append(signal)
        
        bias_stats = {}
        for bias, bias_signals in bias_groups.items():
            wins = [s for s in bias_signals if s['pnl_percent'] > 0]
            total_pnl = sum(s['pnl_percent'] for s in bias_signals)
            avg_pnl = total_pnl / len(bias_signals) if bias_signals else 0
            
            bias_stats[bias] = {
                'count': len(bias_signals),
                'wins': len(wins),
                'win_rate': (len(wins) / len(bias_signals) * 100) if bias_signals else 0,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl
            }
        
        # Анализ volume_ratio
        volume_stats = {
            'low': [],  # < 1.0
            'normal': [],  # 1.0 - 1.5
            'high': []  # > 1.5
        }
        
        for signal in closed:
            meta = signal.get('meta_data') or {}
            vol_ratio = meta.get('volume_ratio', 1.0)
            
            if vol_ratio < 1.0:
                volume_stats['low'].append(signal)
            elif vol_ratio <= 1.5:
                volume_stats['normal'].append(signal)
            else:
                volume_stats['high'].append(signal)
        
        volume_analysis = {}
        for level, vol_signals in volume_stats.items():
            if not vol_signals:
                continue
            wins = [s for s in vol_signals if s['pnl_percent'] > 0]
            volume_analysis[level] = {
                'count': len(vol_signals),
                'win_rate': (len(wins) / len(vol_signals) * 100) if vol_signals else 0,
                'avg_pnl': sum(s['pnl_percent'] for s in vol_signals) / len(vol_signals)
            }
        
        return {
            'bias': bias_stats,
            'volume': volume_analysis
        }
    
    def get_top_trades(self, signals, n=10):
        """Топ лучших и худших сделок"""
        closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
        
        sorted_signals = sorted(closed, key=lambda x: x['pnl_percent'], reverse=True)
        
        return {
            'best': sorted_signals[:n],
            'worst': sorted_signals[-n:][::-1]
        }
    
    def analyze_score_distribution(self, signals):
        """Анализ распределения score"""
        score_groups = defaultdict(list)
        
        for signal in signals:
            score = round(signal['score'], 1)
            score_groups[score].append(signal)
        
        stats = {}
        for score, score_signals in sorted(score_groups.items()):
            closed = [s for s in score_signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
            if not closed:
                continue
            
            wins = [s for s in closed if s['pnl_percent'] > 0]
            win_rate = (len(wins) / len(closed) * 100) if closed else 0
            avg_pnl = sum(s['pnl_percent'] for s in closed) / len(closed)
            
            stats[score] = {
                'total': len(score_signals),
                'closed': len(closed),
                'win_rate': win_rate,
                'avg_pnl': avg_pnl
            }
        
        return stats
    
    def generate_report(self):
        """Генерация полного отчета"""
        print("\n" + "="*80)
        print("📊 ПОЛНЫЙ АНАЛИЗ ОСНОВНЫХ СТРАТЕГИЙ")
        print("="*80)
        
        signals = self.get_all_signals()
        
        if not signals:
            print("\n❌ НЕТ СИГНАЛОВ ДЛЯ АНАЛИЗА")
            return
        
        # Общая статистика
        closed = [s for s in signals if s['status'] == 'CLOSED' and s['pnl_percent'] is not None]
        wins = [s for s in closed if s['pnl_percent'] > 0]
        losses = [s for s in closed if s['pnl_percent'] <= 0]
        
        total_pnl = sum(s['pnl_percent'] for s in closed)
        win_rate = (len(wins) / len(closed) * 100) if closed else 0
        avg_win = sum(s['pnl_percent'] for s in wins) / len(wins) if wins else 0
        avg_loss = sum(s['pnl_percent'] for s in losses) / len(losses) if losses else 0
        profit_factor = abs(sum(s['pnl_percent'] for s in wins) / sum(s['pnl_percent'] for s in losses)) if losses and wins else 0
        
        print(f"\n📈 КРАТКАЯ СВОДКА")
        print(f"{'='*80}")
        print(f"Всего сигналов: {len(signals)}")
        print(f"Закрытых сделок: {len(closed)}")
        print(f"Побед: {len(wins)} ({win_rate:.1f}%)")
        print(f"Убытков: {len(losses)} ({100-win_rate:.1f}%)")
        print(f"Суммарный PnL: {total_pnl:+.2f}%")
        print(f"Средний PnL: {total_pnl/len(closed):+.2f}%" if closed else "N/A")
        print(f"Средняя победа: {avg_win:+.2f}%")
        print(f"Средний убыток: {avg_loss:+.2f}%")
        print(f"Profit Factor: {profit_factor:.2f}")
        
        if closed:
            best = max(closed, key=lambda x: x['pnl_percent'])
            worst = min(closed, key=lambda x: x['pnl_percent'])
            print(f"Лучшая сделка: {best['symbol']} {best['direction']} {best['pnl_percent']:+.2f}%")
            print(f"Худшая сделка: {worst['symbol']} {worst['direction']} {worst['pnl_percent']:+.2f}%")
        
        # Анализ по стратегиям
        print(f"\n\n📊 АНАЛИЗ ПО СТРАТЕГИЯМ")
        print(f"{'='*80}")
        
        strategy_stats = self.analyze_by_strategy(signals)
        
        print(f"\n{'Стратегия':<25} {'Сигналов':<10} {'WR%':<8} {'PnL%':<10} {'PF':<8} {'Статус'}")
        print(f"{'-'*80}")
        
        for strategy_name in self.strategies.values():
            stats = strategy_stats[strategy_name]
            if stats['count'] == 0:
                print(f"{strategy_name:<25} {0:<10} {'-':<8} {'-':<10} {'-':<8} ❌ НЕ РАБОТАЕТ")
            else:
                status = "✅ АКТИВНА" if stats['active'] else "❌ НЕАКТИВНА"
                wr = f"{stats['win_rate']:.1f}" if stats['closed'] > 0 else "-"
                pnl = f"{stats['total_pnl']:+.2f}" if stats['closed'] > 0 else "-"
                pf = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] > 0 else "-"
                print(f"{strategy_name:<25} {stats['count']:<10} {wr:<8} {pnl:<10} {pf:<8} {status}")
        
        # Детальная статистика по активным стратегиям
        print(f"\n\n📈 ДЕТАЛЬНАЯ СТАТИСТИКА АКТИВНЫХ СТРАТЕГИЙ")
        print(f"{'='*80}")
        
        for strategy_name, stats in strategy_stats.items():
            if stats['count'] > 0 and stats['closed'] > 0:
                print(f"\n🔹 {strategy_name}")
                print(f"   Всего сигналов: {stats['count']}")
                print(f"   Закрыто сделок: {stats['closed']}")
                print(f"   Побед: {stats['wins']} / Убытков: {stats['losses']}")
                print(f"   Win Rate: {stats['win_rate']:.1f}%")
                print(f"   Средняя победа: {stats['avg_win']:+.2f}%")
                print(f"   Средний убыток: {stats['avg_loss']:+.2f}%")
                print(f"   Суммарный PnL: {stats['total_pnl']:+.2f}%")
                print(f"   Profit Factor: {stats['profit_factor']:.2f}")
                print(f"   Лучшая сделка: {stats['best_trade']:+.2f}%")
                print(f"   Худшая сделка: {stats['worst_trade']:+.2f}%")
        
        # Анализ по режимам
        print(f"\n\n🌊 АНАЛИЗ ПО РЫНОЧНЫМ РЕЖИМАМ")
        print(f"{'='*80}")
        
        regime_stats = self.analyze_by_regime(signals)
        
        print(f"\n{'Режим':<15} {'Сигналов':<10} {'Побед':<10} {'WR%':<10} {'PnL%':<10} {'Avg PnL%'}")
        print(f"{'-'*80}")
        
        for regime, stats in sorted(regime_stats.items(), key=lambda x: x[1]['win_rate'], reverse=True):
            rating = "✅ ОТЛИЧНО" if stats['win_rate'] >= 50 else "⚠️ СРЕДНЕ" if stats['win_rate'] >= 35 else "❌ ПЛОХО"
            print(f"{regime:<15} {stats['count']:<10} {stats['wins']:<10} {stats['win_rate']:<10.1f} {stats['total_pnl']:<+10.2f} {stats['avg_pnl']:+.2f}% {rating}")
        
        # Анализ по направлениям
        print(f"\n\n🎯 АНАЛИЗ ПО НАПРАВЛЕНИЯМ")
        print(f"{'='*80}")
        
        direction_stats = self.analyze_by_direction(signals)
        
        for direction, stats in direction_stats.items():
            if stats['count'] > 0:
                print(f"\n{direction}:")
                print(f"   Сделок: {stats['count']}")
                print(f"   Побед: {stats['wins']} / Убытков: {stats['losses']}")
                print(f"   Win Rate: {stats['win_rate']:.1f}%")
                print(f"   Суммарный PnL: {stats['total_pnl']:+.2f}%")
                print(f"   Средний PnL: {stats['avg_pnl']:+.2f}%")
        
        # Анализ по типам выхода
        print(f"\n\n🚪 АНАЛИЗ ПО ТИПАМ ВЫХОДА")
        print(f"{'='*80}")
        
        exit_stats = self.analyze_exit_types(signals)
        
        print(f"\n{'Тип выхода':<15} {'Количество':<12} {'WR%':<10} {'Avg PnL%':<12} {'Total PnL%'}")
        print(f"{'-'*80}")
        
        for exit_type, stats in sorted(exit_stats.items(), key=lambda x: x[1]['avg_pnl'], reverse=True):
            print(f"{exit_type:<15} {stats['count']:<12} {stats['win_rate']:<10.1f} {stats['avg_pnl']:<+12.2f} {stats['total_pnl']:+.2f}%")
        
        # Анализ метаданных
        print(f"\n\n📊 АНАЛИЗ МЕТАДАННЫХ")
        print(f"{'='*80}")
        
        meta_stats = self.analyze_metadata(signals)
        
        print(f"\n🔸 По BTC Bias:")
        print(f"\n{'Bias':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL%':<12} {'Total PnL%'}")
        print(f"{'-'*70}")
        
        for bias, stats in sorted(meta_stats['bias'].items(), key=lambda x: x[1]['avg_pnl'], reverse=True):
            rating = "✅" if stats['avg_pnl'] > 0 else "❌"
            print(f"{bias:<15} {stats['count']:<10} {stats['win_rate']:<10.1f} {stats['avg_pnl']:<+12.2f} {stats['total_pnl']:+.2f}% {rating}")
        
        print(f"\n🔸 По Volume Ratio:")
        print(f"\n{'Уровень':<15} {'Сделок':<10} {'WR%':<10} {'Avg PnL%'}")
        print(f"{'-'*50}")
        
        for level, stats in meta_stats['volume'].items():
            print(f"{level:<15} {stats['count']:<10} {stats['win_rate']:<10.1f} {stats['avg_pnl']:+.2f}%")
        
        # Score Distribution
        print(f"\n\n📈 РАСПРЕДЕЛЕНИЕ SCORE")
        print(f"{'='*80}")
        
        score_stats = self.analyze_score_distribution(signals)
        
        print(f"\n{'Score':<10} {'Всего':<10} {'Закрыто':<10} {'WR%':<10} {'Avg PnL%'}")
        print(f"{'-'*50}")
        
        for score, stats in sorted(score_stats.items()):
            print(f"{score:<10.1f} {stats['total']:<10} {stats['closed']:<10} {stats['win_rate']:<10.1f} {stats['avg_pnl']:+.2f}%")
        
        # Топ сделок
        print(f"\n\n🏆 ТОП-10 ЛУЧШИХ СДЕЛОК")
        print(f"{'='*80}")
        
        top_trades = self.get_top_trades(signals, 10)
        
        for i, signal in enumerate(top_trades['best'], 1):
            meta = signal.get('meta_data') or {}
            bias = meta.get('btc_bias', 'unknown')
            print(f"\n{i}. {signal['symbol']} {signal['direction']} → {signal['pnl_percent']:+.2f}%")
            print(f"   Стратегия: {signal['strategy_name']}")
            print(f"   Режим: {signal['market_regime']} | Bias: {bias} | Score: {signal['score']:.1f}")
            print(f"   Exit: {signal['exit_type']} | Создан: {signal['created_at'][:16]}")
        
        print(f"\n\n💥 ТОП-10 ХУДШИХ СДЕЛОК")
        print(f"{'='*80}")
        
        for i, signal in enumerate(top_trades['worst'], 1):
            meta = signal.get('meta_data') or {}
            bias = meta.get('btc_bias', 'unknown')
            print(f"\n{i}. {signal['symbol']} {signal['direction']} → {signal['pnl_percent']:+.2f}%")
            print(f"   Стратегия: {signal['strategy_name']}")
            print(f"   Режим: {signal['market_regime']} | Bias: {bias} | Score: {signal['score']:.1f}")
            print(f"   Exit: {signal['exit_type']} | Создан: {signal['created_at'][:16]}")
        
        print(f"\n\n{'='*80}")
        print("📊 АНАЛИЗ ЗАВЕРШЕН")
        print(f"{'='*80}\n")
        
    def close(self):
        self.conn.close()


if __name__ == "__main__":
    analyzer = MainStrategiesAnalyzer()
    analyzer.generate_report()
    analyzer.close()
