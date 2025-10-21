#!/usr/bin/env python3
"""
Анализ основных стратегий из лог-файлов
Парсит логи strategies_*.log и извлекает статистику
"""

import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import json

class LogAnalyzer:
    def __init__(self, log_dir='attached_assets'):
        self.log_dir = Path(log_dir)
        self.strategies = {
            'Liquidity Sweep': 0,
            'Break & Retest': 1,
            'Order Flow': 2,
            'MA/VWAP Pullback': 3,
            'Volume Profile': 4,
            'ATR Momentum': 5
        }
        
        # Паттерны для парсинга
        self.patterns = {
            'signal_generated': re.compile(r'Signal generated: (.*?) \| (.*?) (LONG|SHORT).*?Score: ([\d.]+)'),
            'signal_details': re.compile(r'Entry: ([\d.]+).*?SL: ([\d.]+).*?TP1: ([\d.]+).*?TP2: ([\d.]+)', re.DOTALL),
            'regime': re.compile(r'Regime: (\w+)'),
            'bias': re.compile(r'BTC Bias: (\w+)'),
            'volume_ratio': re.compile(r'Volume Ratio: ([\d.]+)'),
            'exit': re.compile(r'(.*?) (LONG|SHORT).*?closed.*?(TP1|TP2|SL|BREAKEVEN|TIME_STOP).*?([\d.]+)%'),
            'strategy_disabled': re.compile(r'(.*?) strategy.*?(disabled|not active|skipped)', re.IGNORECASE),
            'filter_rejection': re.compile(r'(❌|⚠️|Rejected|Skipped|Failed).*?(\w+.*?)(?:\n|$)'),
            'adx_filter': re.compile(r'ADX.*?([\d.]+).*?<.*?([\d.]+)'),
            'volume_filter': re.compile(r'Volume.*?([\d.]+)x.*?<.*?([\d.]+)x'),
        }
    
    def find_log_files(self):
        """Найти все лог-файлы strategies_*.log"""
        return sorted(self.log_dir.glob('strategies_*.log'), key=lambda x: x.stat().st_mtime, reverse=True)
    
    def parse_logs(self, max_files=None):
        """Парсинг лог-файлов"""
        log_files = self.find_log_files()
        
        if max_files:
            log_files = log_files[:max_files]
        
        print(f"\n🔍 Анализирую {len(log_files)} лог-файлов...")
        
        all_signals = []
        all_exits = []
        strategy_activity = defaultdict(int)
        filter_rejections = defaultdict(int)
        
        for log_file in log_files:
            print(f"   Обрабатываю: {log_file.name} ({log_file.stat().st_size / 1024:.1f} KB)")
            
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Парсинг сигналов
                for match in self.patterns['signal_generated'].finditer(content):
                    strategy_name = match.group(1)
                    symbol = match.group(2)
                    direction = match.group(3)
                    score = float(match.group(4))
                    
                    signal = {
                        'strategy': strategy_name,
                        'symbol': symbol,
                        'direction': direction,
                        'score': score,
                        'log_file': log_file.name
                    }
                    
                    # Ищем детали сигнала после генерации
                    signal_pos = match.end()
                    nearby_text = content[signal_pos:signal_pos+500]
                    
                    # Режим
                    regime_match = self.patterns['regime'].search(nearby_text)
                    if regime_match:
                        signal['regime'] = regime_match.group(1)
                    
                    # Bias
                    bias_match = self.patterns['bias'].search(nearby_text)
                    if bias_match:
                        signal['bias'] = bias_match.group(1)
                    
                    # Volume ratio
                    vol_match = self.patterns['volume_ratio'].search(nearby_text)
                    if vol_match:
                        signal['volume_ratio'] = float(vol_match.group(1))
                    
                    all_signals.append(signal)
                    strategy_activity[strategy_name] += 1
                
                # Парсинг выходов
                for match in self.patterns['exit'].finditer(content):
                    symbol = match.group(1)
                    direction = match.group(2)
                    exit_type = match.group(3)
                    pnl = float(match.group(4))
                    
                    exit_data = {
                        'symbol': symbol,
                        'direction': direction,
                        'exit_type': exit_type,
                        'pnl_percent': pnl,
                        'log_file': log_file.name
                    }
                    
                    all_exits.append(exit_data)
                
                # Парсинг отклонений фильтрами
                for line in content.split('\n'):
                    # ADX фильтр
                    adx_match = self.patterns['adx_filter'].search(line)
                    if adx_match:
                        filter_rejections['ADX_too_weak'] += 1
                    
                    # Volume фильтр
                    vol_match = self.patterns['volume_filter'].search(line)
                    if vol_match:
                        filter_rejections['Volume_too_low'] += 1
                    
                    # Общие отклонения
                    if any(word in line.lower() for word in ['rejected', 'failed', 'skipped', 'не прошёл']):
                        if 'volume' in line.lower():
                            filter_rejections['Volume_filters'] += 1
                        elif 'adx' in line.lower():
                            filter_rejections['ADX_filters'] += 1
                        elif 'regime' in line.lower():
                            filter_rejections['Regime_filters'] += 1
                
            except Exception as e:
                print(f"   ❌ Ошибка при обработке {log_file.name}: {e}")
        
        return {
            'signals': all_signals,
            'exits': all_exits,
            'strategy_activity': dict(strategy_activity),
            'filter_rejections': dict(filter_rejections)
        }
    
    def analyze_data(self, data):
        """Анализ собранных данных"""
        signals = data['signals']
        exits = data['exits']
        
        print(f"\n" + "="*80)
        print(f"📊 РЕЗУЛЬТАТЫ АНАЛИЗА")
        print(f"="*80)
        
        print(f"\n📈 ОБЩАЯ СТАТИСТИКА")
        print(f"-"*80)
        print(f"Всего найдено сигналов: {len(signals)}")
        print(f"Всего найдено выходов: {len(exits)}")
        
        # Анализ по стратегиям
        print(f"\n\n📊 АКТИВНОСТЬ СТРАТЕГИЙ")
        print(f"-"*80)
        
        print(f"\n{'Стратегия':<30} {'Сигналов':<15} {'Статус'}")
        print(f"-"*80)
        
        total_generated = sum(data['strategy_activity'].values())
        
        for strategy_name in self.strategies.keys():
            count = data['strategy_activity'].get(strategy_name, 0)
            percentage = (count / total_generated * 100) if total_generated > 0 else 0
            
            if count == 0:
                status = "❌ НЕ РАБОТАЕТ"
            elif count < 5:
                status = f"⚠️ МАЛО СИГНАЛОВ ({percentage:.1f}%)"
            else:
                status = f"✅ АКТИВНА ({percentage:.1f}%)"
            
            print(f"{strategy_name:<30} {count:<15} {status}")
        
        # Анализ по режимам
        print(f"\n\n🌊 РАСПРЕДЕЛЕНИЕ ПО РЕЖИМАМ")
        print(f"-"*80)
        
        regime_counts = defaultdict(int)
        for signal in signals:
            if 'regime' in signal:
                regime_counts[signal['regime']] += 1
        
        for regime, count in sorted(regime_counts.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(signals) * 100) if signals else 0
            print(f"{regime:<20} {count:<10} ({percentage:.1f}%)")
        
        # Анализ по bias
        print(f"\n\n📉 РАСПРЕДЕЛЕНИЕ ПО BTC BIAS")
        print(f"-"*80)
        
        bias_counts = defaultdict(int)
        for signal in signals:
            if 'bias' in signal:
                bias_counts[signal['bias']] += 1
        
        for bias, count in sorted(bias_counts.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(signals) * 100) if signals else 0
            print(f"{bias:<20} {count:<10} ({percentage:.1f}%)")
        
        # Анализ направлений
        print(f"\n\n🎯 РАСПРЕДЕЛЕНИЕ ПО НАПРАВЛЕНИЯМ")
        print(f"-"*80)
        
        direction_counts = defaultdict(int)
        for signal in signals:
            direction_counts[signal['direction']] += 1
        
        for direction, count in sorted(direction_counts.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(signals) * 100) if signals else 0
            print(f"{direction:<20} {count:<10} ({percentage:.1f}%)")
        
        # Анализ Score
        print(f"\n\n📊 РАСПРЕДЕЛЕНИЕ SCORE")
        print(f"-"*80)
        
        if signals:
            scores = [s['score'] for s in signals if 'score' in s]
            if scores:
                print(f"Минимальный score: {min(scores):.1f}")
                print(f"Максимальный score: {max(scores):.1f}")
                print(f"Средний score: {sum(scores)/len(scores):.2f}")
                
                score_ranges = {
                    '< 2.0': len([s for s in scores if s < 2.0]),
                    '2.0-3.0': len([s for s in scores if 2.0 <= s < 3.0]),
                    '3.0-4.0': len([s for s in scores if 3.0 <= s < 4.0]),
                    '>= 4.0': len([s for s in scores if s >= 4.0])
                }
                
                print(f"\nРаспределение по диапазонам:")
                for range_name, count in score_ranges.items():
                    percentage = (count / len(scores) * 100) if scores else 0
                    print(f"  {range_name:<15} {count:<10} ({percentage:.1f}%)")
        
        # Анализ выходов
        if exits:
            print(f"\n\n🚪 АНАЛИЗ ВЫХОДОВ")
            print(f"-"*80)
            
            exit_type_counts = defaultdict(list)
            for exit_data in exits:
                exit_type_counts[exit_data['exit_type']].append(exit_data['pnl_percent'])
            
            print(f"\n{'Тип выхода':<20} {'Количество':<15} {'Avg PnL%':<15} {'Total PnL%'}")
            print(f"-"*80)
            
            for exit_type, pnls in sorted(exit_type_counts.items(), key=lambda x: sum(x[1]), reverse=True):
                avg_pnl = sum(pnls) / len(pnls) if pnls else 0
                total_pnl = sum(pnls)
                count = len(pnls)
                
                rating = "✅" if avg_pnl > 0 else "❌"
                
                print(f"{exit_type:<20} {count:<15} {avg_pnl:<+15.2f} {total_pnl:+.2f}% {rating}")
            
            # Общая статистика PnL
            all_pnls = [e['pnl_percent'] for e in exits]
            positive_pnls = [p for p in all_pnls if p > 0]
            negative_pnls = [p for p in all_pnls if p <= 0]
            
            win_rate = (len(positive_pnls) / len(all_pnls) * 100) if all_pnls else 0
            
            print(f"\n📈 ОБЩИЙ PnL АНАЛИЗ:")
            print(f"-"*80)
            print(f"Win Rate: {win_rate:.1f}% ({len(positive_pnls)} побед / {len(exits)} сделок)")
            print(f"Суммарный PnL: {sum(all_pnls):+.2f}%")
            print(f"Средний PnL: {sum(all_pnls)/len(all_pnls):+.2f}%")
            
            if positive_pnls:
                print(f"Средняя победа: {sum(positive_pnls)/len(positive_pnls):+.2f}%")
                print(f"Лучшая сделка: {max(positive_pnls):+.2f}%")
            
            if negative_pnls:
                print(f"Средний убыток: {sum(negative_pnls)/len(negative_pnls):+.2f}%")
                print(f"Худшая сделка: {min(negative_pnls):+.2f}%")
            
            if positive_pnls and negative_pnls:
                profit_factor = abs(sum(positive_pnls) / sum(negative_pnls))
                print(f"Profit Factor: {profit_factor:.2f}")
        
        # Анализ фильтров
        if data['filter_rejections']:
            print(f"\n\n🚫 ОТКЛОНЕНИЯ ФИЛЬТРАМИ")
            print(f"-"*80)
            
            for filter_name, count in sorted(data['filter_rejections'].items(), key=lambda x: x[1], reverse=True):
                print(f"{filter_name:<30} {count} раз")
        
        # Volume Ratio анализ
        print(f"\n\n📊 АНАЛИЗ VOLUME RATIO")
        print(f"-"*80)
        
        volume_ratios = [s.get('volume_ratio') for s in signals if 'volume_ratio' in s]
        if volume_ratios:
            print(f"Минимальный: {min(volume_ratios):.2f}x")
            print(f"Максимальный: {max(volume_ratios):.2f}x")
            print(f"Средний: {sum(volume_ratios)/len(volume_ratios):.2f}x")
            
            vol_distribution = {
                '< 1.0x': len([v for v in volume_ratios if v < 1.0]),
                '1.0-1.5x': len([v for v in volume_ratios if 1.0 <= v < 1.5]),
                '>= 1.5x': len([v for v in volume_ratios if v >= 1.5])
            }
            
            print(f"\nРаспределение:")
            for range_name, count in vol_distribution.items():
                percentage = (count / len(volume_ratios) * 100) if volume_ratios else 0
                print(f"  {range_name:<15} {count:<10} ({percentage:.1f}%)")
        else:
            print("❌ Нет данных о volume ratio в логах")
        
        print(f"\n" + "="*80)
        print(f"✅ АНАЛИЗ ЗАВЕРШЕН")
        print(f"="*80 + "\n")
        
        return {
            'signals_count': len(signals),
            'exits_count': len(exits),
            'win_rate': win_rate if exits else 0,
            'total_pnl': sum(all_pnls) if exits else 0
        }


if __name__ == "__main__":
    analyzer = LogAnalyzer()
    
    # Анализируем последние 5 самых свежих файлов
    print("\n🔍 АНАЛИЗ ОСНОВНЫХ СТРАТЕГИЙ ПО ЛОГ-ФАЙЛАМ")
    print("="*80)
    
    data = analyzer.parse_logs(max_files=5)
    results = analyzer.analyze_data(data)
    
    print(f"\n📋 КРАТКИЕ ИТОГИ:")
    print(f"   Всего сигналов: {results['signals_count']}")
    print(f"   Закрыто сделок: {results['exits_count']}")
    if results['exits_count'] > 0:
        print(f"   Win Rate: {results['win_rate']:.1f}%")
        print(f"   Суммарный PnL: {results['total_pnl']:+.2f}%")
