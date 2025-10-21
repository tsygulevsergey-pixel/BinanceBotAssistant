#!/usr/bin/env python3
"""
Полный парсинг и анализ закрытых сделок из bot_*.log файлов
"""

import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

class BotLogParser:
    def __init__(self, log_dir='attached_assets'):
        self.log_dir = Path(log_dir)
        
        # Паттерны для парсинга
        self.patterns = {
            # Основной паттерн для закрытия сделок
            'signal_closed': re.compile(
                r'Signal closed.*?:\s*(\w+)\s+(LONG|SHORT).*?'
                r'Entry:\s*([\d.]+).*?Exit:\s*([\d.]+).*?'
                r'PnL:\s*([+-]?[\d.]+)%.*?\(([\w_]+)\)',
                re.IGNORECASE
            ),
            # Паттерн для breakeven/TP1
            'breakeven': re.compile(
                r'Signal closed.*?:\s*(\w+)\s+(LONG|SHORT).*?'
                r'Breakeven.*?\(\+?([\d.]+)%\)',
                re.IGNORECASE
            ),
            # Паттерн для SL/TP2
            'sl_tp': re.compile(
                r'Signal closed.*?:\s*(\w+)\s+(LONG|SHORT).*?'
                r'(SL|TP\d)\s*\(([+-]?[\d.]+)%\)',
                re.IGNORECASE
            ),
        }
    
    def parse_all_logs(self):
        """Парсинг всех bot_*.log файлов"""
        log_files = sorted(self.log_dir.glob('bot_2025-10-*.log'), 
                          key=lambda x: x.stat().st_mtime, reverse=True)
        
        print(f"\n🔍 Найдено {len(log_files)} лог-файлов бота")
        
        all_trades = []
        
        for log_file in log_files[:20]:  # Берем последние 20 файлов
            print(f"   Парсинг: {log_file.name} ({log_file.stat().st_size / 1024:.1f} KB)")
            
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Парсинг основного формата
                for match in self.patterns['signal_closed'].finditer(content):
                    symbol = match.group(1)
                    direction = match.group(2)
                    entry = float(match.group(3))
                    exit_price = float(match.group(4))
                    pnl = float(match.group(5))
                    exit_type = match.group(6)
                    
                    trade = {
                        'symbol': symbol,
                        'direction': direction,
                        'entry': entry,
                        'exit': exit_price,
                        'pnl': pnl,
                        'exit_type': exit_type,
                        'log_file': log_file.name
                    }
                    
                    all_trades.append(trade)
                
                # Парсинг breakeven формата
                for match in self.patterns['breakeven'].finditer(content):
                    symbol = match.group(1)
                    direction = match.group(2)
                    pnl = float(match.group(3))
                    
                    trade = {
                        'symbol': symbol,
                        'direction': direction,
                        'entry': 0,
                        'exit': 0,
                        'pnl': pnl,
                        'exit_type': 'BREAKEVEN',
                        'log_file': log_file.name
                    }
                    
                    all_trades.append(trade)
                
                # Парсинг SL/TP формата
                for match in self.patterns['sl_tp'].finditer(content):
                    symbol = match.group(1)
                    direction = match.group(2)
                    exit_type = match.group(3)
                    pnl = float(match.group(4))
                    
                    trade = {
                        'symbol': symbol,
                        'direction': direction,
                        'entry': 0,
                        'exit': 0,
                        'pnl': pnl,
                        'exit_type': exit_type,
                        'log_file': log_file.name
                    }
                    
                    all_trades.append(trade)
                
            except Exception as e:
                print(f"   ❌ Ошибка: {e}")
        
        # Удаляем дубликаты
        unique_trades = []
        seen = set()
        
        for trade in all_trades:
            key = f"{trade['symbol']}_{trade['direction']}_{trade['pnl']}"
            if key not in seen:
                seen.add(key)
                unique_trades.append(trade)
        
        print(f"\n✅ Всего найдено сделок: {len(all_trades)}")
        print(f"✅ Уникальных сделок: {len(unique_trades)}")
        
        return unique_trades
    
    def analyze_trades(self, trades):
        """Полный анализ сделок"""
        if not trades:
            print("\n❌ Нет сделок для анализа!")
            return
        
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]
        
        total_pnl = sum(t['pnl'] for t in trades)
        win_rate = (len(wins) / len(trades) * 100) if trades else 0
        
        print(f"\n" + "="*80)
        print(f"📊 ОБЩАЯ СТАТИСТИКА")
        print(f"="*80)
        
        print(f"\nВсего сделок: {len(trades)}")
        print(f"Побед: {len(wins)} ({win_rate:.1f}%)")
        print(f"Убытков: {len(losses)} ({100-win_rate:.1f}%)")
        print(f"Суммарный PnL: {total_pnl:+.2f}%")
        print(f"Средний PnL: {total_pnl/len(trades):+.2f}%")
        
        if wins:
            avg_win = sum(t['pnl'] for t in wins) / len(wins)
            max_win = max(t['pnl'] for t in wins)
            print(f"Средняя победа: {avg_win:+.2f}%")
            print(f"Лучшая победа: {max_win:+.2f}%")
        
        if losses:
            avg_loss = sum(t['pnl'] for t in losses) / len(losses)
            max_loss = min(t['pnl'] for t in losses)
            print(f"Средний убыток: {avg_loss:+.2f}%")
            print(f"Худший убыток: {max_loss:+.2f}%")
        
        if wins and losses:
            profit_factor = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses))
            print(f"Profit Factor: {profit_factor:.2f}")
        
        # Анализ по направлениям
        print(f"\n\n🎯 АНАЛИЗ ПО НАПРАВЛЕНИЯМ")
        print(f"="*80)
        
        for direction in ['LONG', 'SHORT']:
            dir_trades = [t for t in trades if t['direction'] == direction]
            if not dir_trades:
                continue
            
            dir_wins = [t for t in dir_trades if t['pnl'] > 0]
            dir_pnl = sum(t['pnl'] for t in dir_trades)
            dir_wr = (len(dir_wins) / len(dir_trades) * 100) if dir_trades else 0
            
            print(f"\n{direction}:")
            print(f"   Сделок: {len(dir_trades)}")
            print(f"   Побед: {len(dir_wins)} ({dir_wr:.1f}%)")
            print(f"   Суммарный PnL: {dir_pnl:+.2f}%")
            print(f"   Средний PnL: {dir_pnl/len(dir_trades):+.2f}%")
        
        # Анализ по типам выхода
        print(f"\n\n🚪 АНАЛИЗ ПО ТИПАМ ВЫХОДА")
        print(f"="*80)
        
        exit_groups = defaultdict(list)
        for trade in trades:
            exit_groups[trade['exit_type']].append(trade)
        
        print(f"\n{'Тип выхода':<20} {'Количество':<15} {'WR%':<10} {'Avg PnL%':<12} {'Total PnL%'}")
        print(f"-"*80)
        
        for exit_type, exit_trades in sorted(exit_groups.items(), 
                                            key=lambda x: sum(t['pnl'] for t in x[1]), 
                                            reverse=True):
            exit_wins = [t for t in exit_trades if t['pnl'] > 0]
            exit_wr = (len(exit_wins) / len(exit_trades) * 100) if exit_trades else 0
            exit_pnl = sum(t['pnl'] for t in exit_trades)
            avg_pnl = exit_pnl / len(exit_trades)
            
            rating = "✅" if avg_pnl > 0 else "❌"
            
            print(f"{exit_type:<20} {len(exit_trades):<15} {exit_wr:<10.1f} {avg_pnl:<+12.2f} {exit_pnl:+.2f}% {rating}")
        
        # Топ-10 лучших и худших
        print(f"\n\n🏆 ТОП-10 ЛУЧШИХ СДЕЛОК")
        print(f"="*80)
        
        sorted_trades = sorted(trades, key=lambda x: x['pnl'], reverse=True)
        
        for i, trade in enumerate(sorted_trades[:10], 1):
            print(f"{i}. {trade['symbol']} {trade['direction']} → {trade['pnl']:+.2f}% ({trade['exit_type']})")
        
        print(f"\n\n💥 ТОП-10 ХУДШИХ СДЕЛОК")
        print(f"="*80)
        
        for i, trade in enumerate(sorted_trades[-10:][::-1], 1):
            print(f"{i}. {trade['symbol']} {trade['direction']} → {trade['pnl']:+.2f}% ({trade['exit_type']})")
        
        # Статистика по символам
        print(f"\n\n💰 ТОП-10 САМЫХ ПРИБЫЛЬНЫХ СИМВОЛОВ")
        print(f"="*80)
        
        symbol_groups = defaultdict(list)
        for trade in trades:
            symbol_groups[trade['symbol']].append(trade)
        
        symbol_pnls = {}
        for symbol, sym_trades in symbol_groups.items():
            symbol_pnls[symbol] = sum(t['pnl'] for t in sym_trades)
        
        top_symbols = sorted(symbol_pnls.items(), key=lambda x: x[1], reverse=True)[:10]
        
        for i, (symbol, pnl) in enumerate(top_symbols, 1):
            count = len(symbol_groups[symbol])
            avg = pnl / count
            print(f"{i}. {symbol}: {pnl:+.2f}% (сделок: {count}, avg: {avg:+.2f}%)")
        
        print(f"\n\n📉 ТОП-10 САМЫХ УБЫТОЧНЫХ СИМВОЛОВ")
        print(f"="*80)
        
        worst_symbols = sorted(symbol_pnls.items(), key=lambda x: x[1])[:10]
        
        for i, (symbol, pnl) in enumerate(worst_symbols, 1):
            count = len(symbol_groups[symbol])
            avg = pnl / count
            print(f"{i}. {symbol}: {pnl:+.2f}% (сделок: {count}, avg: {avg:+.2f}%)")
        
        # Дополнительная статистика
        print(f"\n\n📊 ДОПОЛНИТЕЛЬНАЯ СТАТИСТИКА")
        print(f"="*80)
        
        # Самая длинная серия побед/убытков
        max_win_streak = 0
        max_loss_streak = 0
        current_win_streak = 0
        current_loss_streak = 0
        
        for trade in trades:
            if trade['pnl'] > 0:
                current_win_streak += 1
                current_loss_streak = 0
                max_win_streak = max(max_win_streak, current_win_streak)
            else:
                current_loss_streak += 1
                current_win_streak = 0
                max_loss_streak = max(max_loss_streak, current_loss_streak)
        
        print(f"Максимальная серия побед: {max_win_streak}")
        print(f"Максимальная серия убытков: {max_loss_streak}")
        
        # Распределение PnL
        pnl_ranges = {
            '> +2.0%': len([t for t in trades if t['pnl'] > 2.0]),
            '+1.0% to +2.0%': len([t for t in trades if 1.0 <= t['pnl'] <= 2.0]),
            '+0.0% to +1.0%': len([t for t in trades if 0.0 < t['pnl'] < 1.0]),
            '0.0%': len([t for t in trades if t['pnl'] == 0.0]),
            '-1.0% to -0.0%': len([t for t in trades if -1.0 < t['pnl'] <= 0.0]),
            '-2.0% to -1.0%': len([t for t in trades if -2.0 <= t['pnl'] <= -1.0]),
            '< -2.0%': len([t for t in trades if t['pnl'] < -2.0]),
        }
        
        print(f"\nРаспределение PnL:")
        for range_name, count in pnl_ranges.items():
            percentage = (count / len(trades) * 100) if trades else 0
            print(f"   {range_name:<20} {count:<10} ({percentage:.1f}%)")
        
        print(f"\n" + "="*80)
        print(f"✅ АНАЛИЗ ЗАВЕРШЕН")
        print(f"="*80 + "\n")


if __name__ == "__main__":
    parser = BotLogParser()
    
    print("\n" + "="*80)
    print("📊 ПОЛНЫЙ АНАЛИЗ ОСНОВНЫХ СТРАТЕГИЙ ИЗ ЛОГОВ БОТА")
    print("="*80)
    
    trades = parser.parse_all_logs()
    parser.analyze_trades(trades)
