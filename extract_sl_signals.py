#!/usr/bin/env python3
"""
Извлечение всех стоп-лосс сигналов с деталями
"""

import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

def parse_logs():
    """Парсинг логов для извлечения SL сигналов"""
    log_dir = Path('attached_assets')
    log_files = sorted(log_dir.glob('bot_2025-10-*.log'), 
                      key=lambda x: x.stat().st_mtime)
    
    # Словарь для хранения параметров сигналов
    signal_params = {}
    sl_signals = []
    
    # Паттерны
    valid_signal_pattern = re.compile(
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \w+ \| .* \| '
        r'✅ VALID SIGNAL: .* \| (\w+) (LONG|SHORT) @ ([\d.]+) \| '
        r'Score: ([\d.]+) \| SL: ([\d.]+) \| TP1: ([\d.]+) \| TP2: ([\d.]+)'
    )
    
    closed_sl_pattern = re.compile(
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \w+ \| .* \| '
        r'[❌✅] Signal closed: (\w+) (LONG|SHORT) \| '
        r'Entry: ([\d.]+) → Exit: ([\d.]+) \| '
        r'PnL: ([+-]?[\d.]+)% .*\(SL\)'
    )
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Найти все VALID SIGNAL
            for match in valid_signal_pattern.finditer(content):
                timestamp = match.group(1)
                symbol = match.group(2)
                direction = match.group(3)
                entry = match.group(4)
                score = match.group(5)
                sl = match.group(6)
                tp1 = match.group(7)
                tp2 = match.group(8)
                
                key = f"{symbol}_{direction}_{entry}"
                signal_params[key] = {
                    'timestamp': timestamp,
                    'symbol': symbol,
                    'direction': direction,
                    'entry': entry,
                    'score': score,
                    'sl': sl,
                    'tp1': tp1,
                    'tp2': tp2
                }
            
            # Найти все SL закрытия
            for match in closed_sl_pattern.finditer(content):
                timestamp = match.group(1)
                symbol = match.group(2)
                direction = match.group(3)
                entry = match.group(4)
                exit_price = match.group(5)
                pnl = match.group(6)
                
                # Попробовать найти параметры
                key = f"{symbol}_{direction}_{entry}"
                
                if key in signal_params:
                    params = signal_params[key]
                    sl_signals.append({
                        'timestamp': params['timestamp'],
                        'symbol': symbol,
                        'direction': direction,
                        'entry': entry,
                        'sl': params['sl'],
                        'tp1': params['tp1'],
                        'tp2': params['tp2'],
                        'exit_price': exit_price,
                        'pnl': pnl,
                        'score': params['score']
                    })
                else:
                    # Если не нашли параметры, используем доступные данные
                    sl_signals.append({
                        'timestamp': timestamp,
                        'symbol': symbol,
                        'direction': direction,
                        'entry': entry,
                        'sl': '-',
                        'tp1': '-',
                        'tp2': '-',
                        'exit_price': exit_price,
                        'pnl': pnl,
                        'score': '-'
                    })
        
        except Exception as e:
            print(f"Ошибка при обработке {log_file}: {e}")
    
    return sl_signals

def format_timestamp(timestamp_str):
    """Конвертировать timestamp в киевское время"""
    try:
        # Парсим timestamp
        dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        # Форматируем для читабельности
        return dt.strftime('%d.%m.%Y %H:%M:%S')
    except:
        return timestamp_str

def create_report(sl_signals):
    """Создать отчет"""
    
    # Сортировка по времени
    sl_signals.sort(key=lambda x: x['timestamp'])
    
    report = []
    report.append("="*100)
    report.append("📊 ВСЕ СТОП-ЛОСС СИГНАЛЫ")
    report.append("="*100)
    report.append(f"\nВсего Stop Loss: {len(sl_signals)}\n")
    report.append("="*100)
    report.append("")
    
    for i, signal in enumerate(sl_signals, 1):
        report.append(f"#{i}")
        report.append("-"*100)
        report.append(f"  Время (Киев):  {format_timestamp(signal['timestamp'])}")
        report.append(f"  Монета:        {signal['symbol']}")
        report.append(f"  Направление:   {signal['direction']}")
        report.append(f"  Entry:         {signal['entry']}")
        report.append(f"  Stop Loss:     {signal['sl']}")
        report.append(f"  Take Profit 1: {signal['tp1']}")
        report.append(f"  Take Profit 2: {signal['tp2']}")
        report.append(f"  Exit (факт):   {signal['exit_price']}")
        report.append(f"  PnL:           {signal['pnl']}%")
        if signal['score'] != '-':
            report.append(f"  Score:         {signal['score']}")
        report.append("")
    
    report.append("="*100)
    report.append(f"ИТОГО: {len(sl_signals)} стоп-лосс сигналов")
    report.append("="*100)
    
    return "\n".join(report)

def create_csv(sl_signals):
    """Создать CSV файл"""
    
    lines = []
    lines.append("Номер;Время (Киев);Монета;Направление;Entry;Stop Loss;Take Profit 1;Take Profit 2;Exit;PnL %;Score")
    
    for i, signal in enumerate(sl_signals, 1):
        lines.append(
            f"{i};"
            f"{format_timestamp(signal['timestamp'])};"
            f"{signal['symbol']};"
            f"{signal['direction']};"
            f"{signal['entry']};"
            f"{signal['sl']};"
            f"{signal['tp1']};"
            f"{signal['tp2']};"
            f"{signal['exit_price']};"
            f"{signal['pnl']};"
            f"{signal['score']}"
        )
    
    return "\n".join(lines)

def main():
    print("🔍 Извлечение стоп-лосс сигналов из логов...")
    
    sl_signals = parse_logs()
    
    print(f"✅ Найдено {len(sl_signals)} стоп-лосс сигналов")
    
    # Создать текстовый отчет
    report = create_report(sl_signals)
    
    with open('STOP_LOSS_SIGNALS.txt', 'w', encoding='utf-8') as f:
        f.write(report)
    
    print("✅ Создан файл: STOP_LOSS_SIGNALS.txt")
    
    # Создать CSV
    csv_content = create_csv(sl_signals)
    
    with open('STOP_LOSS_SIGNALS.csv', 'w', encoding='utf-8') as f:
        f.write(csv_content)
    
    print("✅ Создан файл: STOP_LOSS_SIGNALS.csv")
    
    # Статистика
    print(f"\n📊 Статистика:")
    
    # По направлениям
    long_count = len([s for s in sl_signals if s['direction'] == 'LONG'])
    short_count = len([s for s in sl_signals if s['direction'] == 'SHORT'])
    
    print(f"   LONG:  {long_count} ({long_count/len(sl_signals)*100:.1f}%)")
    print(f"   SHORT: {short_count} ({short_count/len(sl_signals)*100:.1f}%)")
    
    # По монетам
    symbol_counts = defaultdict(int)
    for signal in sl_signals:
        symbol_counts[signal['symbol']] += 1
    
    print(f"\n   Топ-10 монет по SL:")
    for symbol, count in sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"      {symbol}: {count} SL")
    
    print("\n✅ Готово!")

if __name__ == "__main__":
    main()
