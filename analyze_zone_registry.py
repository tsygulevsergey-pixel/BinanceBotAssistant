"""
Zone Registry Memory Analysis
Анализирует зоны из логов (in-memory zones, не из БД)
"""

import re
import json
from pathlib import Path
from collections import defaultdict


def analyze_zone_registry_from_logs(log_file="logs/v3_sr.log"):
    """
    Анализ зон из V3 логов
    
    Ищет строки:
    - "Zone registry updated: 15m: X, 1h: Y, 4h: Z, 1d: W"
    - Любые детали о зонах в логах
    """
    
    print("=" * 80)
    print("🔍 ZONE REGISTRY MEMORY ANALYSIS (FROM LOGS)")
    print("=" * 80)
    print(f"Log file: {log_file}")
    print("=" * 80)
    print()
    
    if not Path(log_file).exists():
        print(f"❌ ERROR: Log file not found: {log_file}")
        print()
        print("Please provide the correct path to your V3 S/R log file.")
        print("Expected format: logs/v3_sr.log or logs/v3_sr_YYYYMMDD.log")
        return
    
    # Read log file
    with open(log_file, 'r', encoding='utf-8') as f:
        log_lines = f.readlines()
    
    print(f"📄 Read {len(log_lines)} lines from log")
    print()
    
    # =========================================================================
    # 1. FIND ZONE REGISTRY UPDATES
    # =========================================================================
    print("📊 1. ZONE REGISTRY UPDATES")
    print("-" * 80)
    
    registry_updates = []
    pattern = r"Zone registry updated.*?15m:\s*(\d+).*?1h:\s*(\d+).*?4h:\s*(\d+).*?1d:\s*(\d+)"
    
    for i, line in enumerate(log_lines):
        match = re.search(pattern, line)
        if match:
            m15, h1, h4, d1 = match.groups()
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            timestamp = timestamp_match.group(1) if timestamp_match else "unknown"
            
            registry_updates.append({
                'timestamp': timestamp,
                'line_num': i + 1,
                '15m': int(m15),
                '1h': int(h1),
                '4h': int(h4),
                '1d': int(d1),
                'total': int(m15) + int(h1) + int(h4) + int(d1)
            })
    
    if registry_updates:
        print(f"Found {len(registry_updates)} registry update(s):")
        for upd in registry_updates[-5:]:  # Show last 5
            print(f"  [{upd['timestamp']}] Line {upd['line_num']:>6} | "
                  f"15m: {upd['15m']:>3}, 1h: {upd['1h']:>3}, 4h: {upd['4h']:>3}, 1d: {upd['1d']:>3} | "
                  f"Total: {upd['total']:>3}")
        
        latest = registry_updates[-1]
        print()
        print(f"  Latest registry state:")
        print(f"    15m zones: {latest['15m']}")
        print(f"    1h zones:  {latest['1h']}")
        print(f"    4h zones:  {latest['4h']}")
        print(f"    1d zones:  {latest['1d']}")
        print(f"    TOTAL:     {latest['total']}")
    else:
        print("  ❌ NO registry updates found in log!")
        print("     This could mean zone building is failing.")
    
    print()
    
    # =========================================================================
    # 2. SEARCH FOR FLIP METADATA
    # =========================================================================
    print("🔄 2. FLIP STATUS IN LOGS")
    print("-" * 80)
    
    flip_mentions = []
    flip_patterns = [
        r"flipped.*?=.*?(True|False|true|false)",
        r"flip_side.*?=.*?['\"]?(\w+)['\"]?",
        r"Flip detected",
        r"Zone flipped",
        r"not flipped"
    ]
    
    for i, line in enumerate(log_lines):
        for pattern in flip_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                flip_mentions.append({
                    'line_num': i + 1,
                    'content': line.strip()
                })
                break
    
    if flip_mentions:
        print(f"Found {len(flip_mentions)} flip-related log entries:")
        for entry in flip_mentions[:10]:  # Show first 10
            print(f"  Line {entry['line_num']:>6}: {entry['content'][:100]}")
    else:
        print("  ❌ NO flip metadata found in logs!")
        print()
        print("  🔍 CRITICAL FINDING:")
        print("     Zones are likely NOT being marked as 'flipped'")
        print("     This would explain 0 signals from Flip-Retest setup!")
    
    print()
    
    # =========================================================================
    # 3. SIGNAL GENERATION ATTEMPTS
    # =========================================================================
    print("📡 3. SIGNAL GENERATION ATTEMPTS")
    print("-" * 80)
    
    signal_attempts = {
        'flip_setup_detected': 0,
        'sweep_setup_detected': 0,
        'blocked_by_flip': 0,
        'blocked_by_vwap': 0,
        'blocked_by_htf': 0,
        'signals_generated': 0
    }
    
    for line in log_lines:
        if re.search(r'Flip.*setup.*detected', line, re.IGNORECASE):
            signal_attempts['flip_setup_detected'] += 1
        if re.search(r'Sweep.*setup.*detected', line, re.IGNORECASE):
            signal_attempts['sweep_setup_detected'] += 1
        if re.search(r'not flipped|BLOCK.*flip', line, re.IGNORECASE):
            signal_attempts['blocked_by_flip'] += 1
        if re.search(r'BLOCK.*VWAP|vwap.*bias.*required', line, re.IGNORECASE):
            signal_attempts['blocked_by_vwap'] += 1
        if re.search(r'BLOCK.*HTF|too close to HTF', line, re.IGNORECASE):
            signal_attempts['blocked_by_htf'] += 1
        if re.search(r'V3.*signal.*generated|🎯.*LONG|🎯.*SHORT', line):
            signal_attempts['signals_generated'] += 1
    
    print("  Setup Detection:")
    print(f"    Flip-Retest detected:  {signal_attempts['flip_setup_detected']}")
    print(f"    Sweep-Return detected: {signal_attempts['sweep_setup_detected']}")
    print()
    print("  Filter Blocks:")
    print(f"    Blocked by flip requirement:  {signal_attempts['blocked_by_flip']}")
    print(f"    Blocked by VWAP bias:         {signal_attempts['blocked_by_vwap']}")
    print(f"    Blocked by HTF clearance:     {signal_attempts['blocked_by_htf']}")
    print()
    print(f"  ✅ Signals Generated:           {signal_attempts['signals_generated']}")
    
    if signal_attempts['signals_generated'] == 0:
        print()
        print("  ⚠️  WARNING: ZERO signals generated!")
        
        if signal_attempts['blocked_by_flip'] > 0:
            print("     → Main issue: Flip requirement blocking signals")
        elif signal_attempts['flip_setup_detected'] == 0 and signal_attempts['sweep_setup_detected'] == 0:
            print("     → Main issue: NO setups detected at all")
        elif signal_attempts['blocked_by_vwap'] > 0:
            print("     → Main issue: VWAP bias blocking signals")
    
    print()
    
    # =========================================================================
    # 4. ZONE BUILDING SUCCESS
    # =========================================================================
    print("🏗️  4. ZONE BUILDING STATUS")
    print("-" * 80)
    
    building_success = 0
    building_errors = 0
    
    for line in log_lines:
        if re.search(r'✅.*zones built successfully|Zone building.*success', line, re.IGNORECASE):
            building_success += 1
        if re.search(r'❌.*zone.*building.*error|Failed to build zones', line, re.IGNORECASE):
            building_errors += 1
    
    print(f"  Successful builds: {building_success}")
    print(f"  Build errors:      {building_errors}")
    
    if building_success == 0 and building_errors == 0:
        print()
        print("  ⚠️  WARNING: No zone building activity found in logs!")
        print("     Either zone building didn't run, or logs are from different file.")
    
    print()
    
    # =========================================================================
    # 5. RECOMMENDATIONS
    # =========================================================================
    print("=" * 80)
    print("💡 RECOMMENDATIONS")
    print("=" * 80)
    
    issues = []
    
    if not registry_updates:
        issues.append("❌ CRITICAL: No zone registry updates found")
        print("1. ❌ CRITICAL: Zone registry is NOT being updated")
        print("   → Check if zone building is running at all")
        print()
    
    if not flip_mentions:
        issues.append("❌ CRITICAL: No flip metadata in zones")
        print("2. ❌ CRITICAL: Zones do NOT have 'flipped' metadata")
        print("   → FlipDetector is NOT running or NOT setting flip metadata")
        print("   → This is likely the PRIMARY reason for 0 signals")
        print()
        print("   FIX: Check FlipDetector in src/utils/sr_zones_v3/flip_detector.py")
        print("        Verify it sets zone['meta']['flipped'] = True")
        print()
    
    if signal_attempts['signals_generated'] == 0:
        if signal_attempts['blocked_by_flip'] > 0:
            issues.append("⚠️  Signals blocked by flip requirement")
            print("3. ⚠️  Flip requirement blocking signals")
            print("   → Even if zones exist, they're not marked as flipped")
            print()
        elif signal_attempts['blocked_by_vwap'] > 0:
            issues.append("⚠️  Signals blocked by VWAP filter")
            print("3. ⚠️  VWAP bias filter blocking signals")
            print("   → Consider making VWAP optional for M15 temporarily")
            print()
    
    if not issues:
        print("✅ No critical issues found in logs!")
        print()
        print("If you're still getting 0 signals, check:")
        print("  - Market conditions (maybe no valid setups right now)")
        print("  - Symbol list (are you monitoring the right symbols?)")
        print("  - Timeframe data (is historical data loaded correctly?)")
    
    print("=" * 80)


def find_latest_log():
    """Find the most recent V3 log file"""
    log_dir = Path("logs")
    
    if not log_dir.exists():
        return None
    
    # Look for v3_sr logs
    v3_logs = list(log_dir.glob("v3_sr*.log"))
    
    if not v3_logs:
        return None
    
    # Return most recent
    return max(v3_logs, key=lambda p: p.stat().st_mtime)


if __name__ == "__main__":
    # Try to find latest log
    latest_log = find_latest_log()
    
    if latest_log:
        print(f"Found V3 log: {latest_log}")
        print()
        analyze_zone_registry_from_logs(str(latest_log))
    else:
        print("No V3 S/R logs found in logs/ directory")
        print()
        print("Please specify log file manually:")
        print("  python analyze_zone_registry.py")
        print()
        print("Or provide path:")
        analyze_zone_registry_from_logs("logs/v3_sr.log")
