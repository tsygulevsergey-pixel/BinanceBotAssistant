"""
Точная диагностика проблемы V3 - найти где теряются зоны
"""

from pathlib import Path

log_file = "logs/v3_2025-10-23_04-31-53.log"

print("=" * 80)
print("🔍 V3 PROBLEM DIAGNOSTIC - WHERE ARE ZONES LOST?")
print("=" * 80)
print()

if not Path(log_file).exists():
    print(f"❌ Log file not found: {log_file}")
    exit()

with open(log_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"📄 Reading {len(lines)} lines from {log_file}")
print()

# ============================================================================
# ПРОВЕРКА 1: Вызывается ли batch_build_zones_parallel()?
# ============================================================================
print("1️⃣  CHECK: Is batch_build_zones_parallel() called?")
print("-" * 80)

batch_start = [l for l in lines if "Building zones in parallel" in l or "🚀 Building zones" in l]
batch_complete = [l for l in lines if "Parallel zone building complete" in l or "🎉 Parallel" in l]

if batch_start:
    print(f"✅ batch_build_zones_parallel() started: {len(batch_start)} time(s)")
    print(f"   Example: {batch_start[0].strip()[:100]}")
else:
    print("❌ batch_build_zones_parallel() NEVER called!")

if batch_complete:
    print(f"✅ Parallel building completed: {len(batch_complete)} time(s)")
    print(f"   Example: {batch_complete[0].strip()[:100]}")
else:
    print("❌ Parallel building NEVER completed!")

print()

# ============================================================================
# ПРОВЕРКА 2: Кешируются ли зоны после parallel build?
# ============================================================================
print("2️⃣  CHECK: Are zones cached after parallel build?")
print("-" * 80)

cache_updates = [l for l in lines if "parallel worker" in l.lower() and ("zones built" in l.lower() or "✅" in l)]

if cache_updates:
    print(f"✅ Zones cached from workers: {len(cache_updates)} symbols")
    print(f"   Examples:")
    for line in cache_updates[:5]:
        print(f"     {line.strip()[:100]}")
else:
    print("❌ NO zones cached from parallel workers!")
    print("   Expected: '✅ BTCUSDT: Zones built successfully (parallel worker)'")
    print("   This means workers succeeded but cache update failed!")

print()

# ============================================================================
# ПРОВЕРКА 3: Вызывается ли analyze()?
# ============================================================================
print("3️⃣  CHECK: Is analyze() called for symbols?")
print("-" * 80)

analyze_calls = [l for l in lines if "🔍 Analyzing" in l or "Analyzing.*Dual-Engine" in l.lower()]

if analyze_calls:
    print(f"✅ analyze() called: {len(analyze_calls)} time(s)")
    print(f"   Examples:")
    for line in analyze_calls[:5]:
        print(f"     {line.strip()[:120]}")
else:
    print("❌ analyze() NEVER called!")
    print("   This means V3 strategy is not being invoked at all!")

print()

# ============================================================================
# ПРОВЕРКА 4: Находятся ли зоны в analyze()?
# ============================================================================
print("4️⃣  CHECK: Does analyze() find zones?")
print("-" * 80)

no_zones = [l for l in lines if "no zones built" in l.lower()]
zones_updated = [l for l in lines if "📦" in l and "zones updated in registry" in l]

if no_zones:
    print(f"❌ 'no zones built' found {len(no_zones)} time(s)")
    print("   This means _get_or_build_zones() returned empty dict!")
    print(f"   Examples:")
    for line in no_zones[:5]:
        print(f"     {line.strip()[:120]}")
else:
    print("✅ No 'no zones built' errors found")

if zones_updated:
    print(f"✅ Registry updated: {len(zones_updated)} time(s)")
    print(f"   Examples:")
    for line in zones_updated[:3]:
        print(f"     {line.strip()[:120]}")
else:
    print("❌ Registry NEVER updated!")
    print("   Expected: '📦 BTCUSDT zones updated in registry: {'15m': 5, '1h': 3}'")

print()

# ============================================================================
# ПРОВЕРКА 5: Генерируются ли raw signals в engines?
# ============================================================================
print("5️⃣  CHECK: Do signal engines generate raw signals?")
print("-" * 80)

m15_engine = [l for l in lines if "M15 engine:" in l or "🔧 M15" in l]
h1_engine = [l for l in lines if "H1 engine:" in l or "🔧 H1" in l]

if m15_engine:
    print(f"✅ M15 engine logs: {len(m15_engine)} time(s)")
    for line in m15_engine[:3]:
        print(f"   {line.strip()[:120]}")
else:
    print("❌ NO M15 engine activity!")

if h1_engine:
    print(f"✅ H1 engine logs: {len(h1_engine)} time(s)")
    for line in h1_engine[:3]:
        print(f"   {line.strip()[:120]}")
else:
    print("❌ NO H1 engine activity!")

print()

# ============================================================================
# ПРОВЕРКА 6: Что говорят логи о "zones built"
# ============================================================================
print("6️⃣  CHECK: What 'zones built' messages exist?")
print("-" * 80)

zones_built = [l for l in lines if "zones built" in l.lower()]

if zones_built:
    print(f"Found {len(zones_built)} 'zones built' message(s):")
    for i, line in enumerate(zones_built[:10], 1):
        print(f"  {i}. {line.strip()[:120]}")
else:
    print("❌ NO 'zones built' messages in entire log!")

print()

# ============================================================================
# SUMMARY
# ============================================================================
print("=" * 80)
print("📊 DIAGNOSTIC SUMMARY")
print("=" * 80)
print()

print("Expected flow:")
print("  1. batch_build_zones_parallel() called → builds zones")
print("  2. Zones cached in v3_zones_provider.cache")
print("  3. analyze() called for each symbol")
print("  4. _get_or_build_zones() reads from cache")
print("  5. Registry updated with zones")
print("  6. Signal engines tick → generate signals")
print()

print("Current status:")
if batch_start and batch_complete:
    print("  ✅ Step 1: Parallel building works")
else:
    print("  ❌ Step 1: Parallel building NOT working")

if cache_updates:
    print("  ✅ Step 2: Zones cached from workers")
else:
    print("  ❌ Step 2: Zones NOT cached (MAIN ISSUE!)")

if analyze_calls:
    print("  ✅ Step 3: analyze() called")
else:
    print("  ❌ Step 3: analyze() NOT called")

if zones_updated:
    print("  ✅ Step 5: Registry updated")
else:
    print("  ❌ Step 5: Registry NOT updated")

if m15_engine or h1_engine:
    print("  ✅ Step 6: Engines active")
else:
    print("  ❌ Step 6: Engines NOT active")

print()
print("=" * 80)
print("🔍 ROOT CAUSE:")
print("=" * 80)

if not cache_updates:
    print("❌ PROBLEM: Zones built by workers but NOT cached!")
    print()
    print("LOCATION: src/v3_sr/strategy.py:177-191")
    print("CODE: self.v3_zones_provider.cache[symbol] = {...}")
    print()
    print("This code is NOT executing despite successful zone builds.")
    print("Possible causes:")
    print("  1. result['success'] is False (but no error logged)")
    print("  2. Exception caught silently")
    print("  3. Parallel workers use different v3_zones_provider instance")
    print()
    print("NEXT STEP: Add debug logging to batch_build_zones_parallel()")

elif not analyze_calls:
    print("❌ PROBLEM: analyze() never called!")
    print()
    print("V3 strategy exists but main loop doesn't call it.")
    print("Check main.py:1924-2050")

elif no_zones:
    print("❌ PROBLEM: analyze() called but finds no zones!")
    print()
    print("Cache is empty when analyze() tries to read it.")
    print("Timing issue: cache cleared between batch and analyze?")

else:
    print("✅ Flow looks OK but no signals - check:")
    print("  - Flip metadata (zones not flipped)")
    print("  - VWAP filter (too strict)")
    print("  - Zone strength threshold (too high)")

print("=" * 80)
