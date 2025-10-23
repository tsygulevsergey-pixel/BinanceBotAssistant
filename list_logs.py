"""
Quick script to list all available log files
"""

from pathlib import Path
from datetime import datetime

log_dir = Path("logs")

print("=" * 80)
print("📂 LOG FILES IN logs/ DIRECTORY")
print("=" * 80)
print()

if not log_dir.exists():
    print("❌ logs/ directory does not exist!")
    print()
    print("This means the bot has never been run on this machine.")
    print("Please run main.py first to generate logs.")
    print("=" * 80)
    exit()

# Get all log files
all_logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

if not all_logs:
    print("❌ No .log files found in logs/ directory!")
    print()
    print("This means:")
    print("  1. The bot hasn't been run yet, OR")
    print("  2. Logs are being written to a different location")
    print()
    print("Expected log files:")
    print("  - main_YYYY-MM-DD_HH-MM-SS.log")
    print("  - v3_YYYY-MM-DD_HH-MM-SS.log")
    print("  - action_price_YYYY-MM-DD_HH-MM-SS.log")
    print("=" * 80)
    exit()

# Categorize logs
v3_logs = []
ap_logs = []
main_logs = []
other_logs = []

for log_file in all_logs:
    name = log_file.name
    size_mb = log_file.stat().st_size / (1024 * 1024)
    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
    
    log_info = {
        'name': name,
        'path': str(log_file),
        'size_mb': size_mb,
        'modified': mtime
    }
    
    if name.startswith('v3_'):
        v3_logs.append(log_info)
    elif name.startswith('action_price'):
        ap_logs.append(log_info)
    elif name.startswith('main'):
        main_logs.append(log_info)
    else:
        other_logs.append(log_info)

# Print categorized logs
print(f"Found {len(all_logs)} total log file(s):")
print()

if v3_logs:
    print(f"🔷 V3 S/R Logs ({len(v3_logs)}):")
    for log in v3_logs[:5]:  # Show latest 5
        print(f"  📄 {log['name']}")
        print(f"     Size: {log['size_mb']:.2f} MB | Modified: {log['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
    if len(v3_logs) > 5:
        print(f"  ... and {len(v3_logs) - 5} more")
    print()
else:
    print("⚠️  No V3 S/R logs found!")
    print("   → V3 strategy might not be enabled or hasn't run yet")
    print()

if ap_logs:
    print(f"🟢 Action Price Logs ({len(ap_logs)}):")
    for log in ap_logs[:3]:
        print(f"  📄 {log['name']}")
        print(f"     Size: {log['size_mb']:.2f} MB | Modified: {log['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
    if len(ap_logs) > 3:
        print(f"  ... and {len(ap_logs) - 3} more")
    print()

if main_logs:
    print(f"📊 Main Bot Logs ({len(main_logs)}):")
    for log in main_logs[:3]:
        print(f"  📄 {log['name']}")
        print(f"     Size: {log['size_mb']:.2f} MB | Modified: {log['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
    if len(main_logs) > 3:
        print(f"  ... and {len(main_logs) - 3} more")
    print()

if other_logs:
    print(f"📁 Other Logs ({len(other_logs)}):")
    for log in other_logs[:3]:
        print(f"  📄 {log['name']}")
        print(f"     Size: {log['size_mb']:.2f} MB | Modified: {log['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
    print()

# Recommendation
print("=" * 80)
print("💡 NEXT STEPS:")
print("=" * 80)

if v3_logs:
    latest_v3 = v3_logs[0]
    print(f"✅ Latest V3 log found: {latest_v3['name']}")
    print()
    print("Run analysis:")
    print(f"  python analyze_zone_registry.py")
    print()
    print("Or specify manually:")
    print(f'  # Edit analyze_zone_registry.py, line ~358')
    print(f'  analyze_zone_registry_from_logs("{latest_v3["path"]}")')
else:
    print("⚠️  No V3 logs found!")
    print()
    print("To generate V3 logs:")
    print("  1. Make sure V3 strategy is enabled in config.yaml:")
    print("     sr_zones_v3:")
    print("       enabled: true")
    print()
    print("  2. Run the bot:")
    print("     python main.py")
    print()
    print("  3. Wait for at least one signal check cycle (90 seconds)")
    print()
    print("  4. Run this script again:")
    print("     python list_logs.py")

print("=" * 80)
