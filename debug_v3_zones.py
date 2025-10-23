"""
V3 S/R Zones Diagnostic Script
Выгружает данные из БД для анализа проблемы "0 signals"
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path


def analyze_v3_zones(db_path="data/trading_bot.db"):
    """Анализ V3 S/R зон из базы данных"""
    
    print("=" * 80)
    print("🔍 V3 S/R ZONES DIAGNOSTIC REPORT")
    print("=" * 80)
    print(f"Database: {db_path}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()
    
    # Проверка существования БД
    if not Path(db_path).exists():
        print(f"❌ ERROR: Database not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Доступ по имени колонки
    cursor = conn.cursor()
    
    # Результаты для JSON
    results = {
        "timestamp": datetime.now().isoformat(),
        "database": db_path,
        "analysis": {}
    }
    
    try:
        # =====================================================================
        # 1. ОБЩАЯ СТАТИСТИКА ПО ЗОНАМ
        # =====================================================================
        print("📊 1. TOTAL ZONES BY TIMEFRAME")
        print("-" * 80)
        
        cursor.execute("""
            SELECT 
                tf,
                COUNT(*) as total_zones,
                AVG(strength) as avg_strength,
                MIN(strength) as min_strength,
                MAX(strength) as max_strength
            FROM sr_zones_v3
            GROUP BY tf
            ORDER BY 
                CASE tf
                    WHEN '15m' THEN 1
                    WHEN '1h' THEN 2
                    WHEN '4h' THEN 3
                    WHEN '1d' THEN 4
                END
        """)
        
        zones_by_tf = []
        for row in cursor.fetchall():
            zones_by_tf.append(dict(row))
            print(f"  {row['tf']:>4} | Zones: {row['total_zones']:>4} | "
                  f"Strength: avg={row['avg_strength']:.1f}, "
                  f"min={row['min_strength']:.0f}, max={row['max_strength']:.0f}")
        
        results["analysis"]["zones_by_timeframe"] = zones_by_tf
        print()
        
        # =====================================================================
        # 2. FLIP STATUS ANALYSIS (КРИТИЧНО!)
        # =====================================================================
        print("🔄 2. FLIP STATUS ANALYSIS (CRITICAL)")
        print("-" * 80)
        
        cursor.execute("""
            SELECT 
                tf,
                COUNT(*) as total,
                SUM(CASE WHEN json_extract(meta, '$.flipped') = 1 THEN 1 ELSE 0 END) as flipped_true,
                SUM(CASE WHEN json_extract(meta, '$.flipped') = 0 THEN 1 ELSE 0 END) as flipped_false,
                SUM(CASE WHEN json_extract(meta, '$.flipped') IS NULL THEN 1 ELSE 0 END) as flipped_null,
                SUM(CASE WHEN json_extract(meta, '$.flip_side') IS NOT NULL THEN 1 ELSE 0 END) as has_flip_side
            FROM sr_zones_v3
            GROUP BY tf
            ORDER BY 
                CASE tf
                    WHEN '15m' THEN 1
                    WHEN '1h' THEN 2
                    WHEN '4h' THEN 3
                    WHEN '1d' THEN 4
                END
        """)
        
        flip_analysis = []
        for row in cursor.fetchall():
            flip_analysis.append(dict(row))
            flip_pct = (row['flipped_true'] / row['total'] * 100) if row['total'] > 0 else 0
            print(f"  {row['tf']:>4} | Total: {row['total']:>4} | "
                  f"Flipped: {row['flipped_true']:>3} ({flip_pct:>5.1f}%) | "
                  f"Not Flipped: {row['flipped_false']:>3} | "
                  f"NULL: {row['flipped_null']:>3} | "
                  f"Has flip_side: {row['has_flip_side']:>3}")
            
            if flip_pct < 5:
                print(f"       ⚠️  WARNING: Only {flip_pct:.1f}% zones are flipped!")
        
        results["analysis"]["flip_status"] = flip_analysis
        print()
        
        # =====================================================================
        # 3. STRENGTH DISTRIBUTION (для порога zone_min_strength=60)
        # =====================================================================
        print("💪 3. STRENGTH DISTRIBUTION (threshold=60)")
        print("-" * 80)
        
        cursor.execute("""
            SELECT 
                tf,
                SUM(CASE WHEN strength >= 80 THEN 1 ELSE 0 END) as key_zones,
                SUM(CASE WHEN strength >= 60 AND strength < 80 THEN 1 ELSE 0 END) as strong_zones,
                SUM(CASE WHEN strength >= 40 AND strength < 60 THEN 1 ELSE 0 END) as normal_zones,
                SUM(CASE WHEN strength < 40 THEN 1 ELSE 0 END) as weak_zones,
                COUNT(*) as total
            FROM sr_zones_v3
            GROUP BY tf
            ORDER BY 
                CASE tf
                    WHEN '15m' THEN 1
                    WHEN '1h' THEN 2
                    WHEN '4h' THEN 3
                    WHEN '1d' THEN 4
                END
        """)
        
        strength_dist = []
        for row in cursor.fetchall():
            strength_dist.append(dict(row))
            usable = row['key_zones'] + row['strong_zones']
            usable_pct = (usable / row['total'] * 100) if row['total'] > 0 else 0
            print(f"  {row['tf']:>4} | Key(≥80): {row['key_zones']:>3} | "
                  f"Strong(60-79): {row['strong_zones']:>3} | "
                  f"Normal(40-59): {row['normal_zones']:>3} | "
                  f"Weak(<40): {row['weak_zones']:>3} | "
                  f"Usable: {usable_pct:.1f}%")
            
            if usable_pct < 30:
                print(f"       ⚠️  WARNING: Only {usable_pct:.1f}% zones meet strength threshold!")
        
        results["analysis"]["strength_distribution"] = strength_dist
        print()
        
        # =====================================================================
        # 4. ZONE KIND DISTRIBUTION (Support vs Resistance)
        # =====================================================================
        print("⚖️  4. ZONE KIND DISTRIBUTION")
        print("-" * 80)
        
        cursor.execute("""
            SELECT 
                tf,
                kind,
                COUNT(*) as count
            FROM sr_zones_v3
            GROUP BY tf, kind
            ORDER BY 
                CASE tf
                    WHEN '15m' THEN 1
                    WHEN '1h' THEN 2
                    WHEN '4h' THEN 3
                    WHEN '1d' THEN 4
                END,
                kind
        """)
        
        kind_dist = {}
        for row in cursor.fetchall():
            tf = row['tf']
            if tf not in kind_dist:
                kind_dist[tf] = {}
            kind_dist[tf][row['kind']] = row['count']
        
        for tf, kinds in kind_dist.items():
            support = kinds.get('S', 0)
            resistance = kinds.get('R', 0)
            total = support + resistance
            print(f"  {tf:>4} | Support: {support:>3} ({support/total*100:.1f}%) | "
                  f"Resistance: {resistance:>3} ({resistance/total*100:.1f}%)")
        
        results["analysis"]["kind_distribution"] = kind_dist
        print()
        
        # =====================================================================
        # 5. RECENT ZONES (последние 5 по каждому TF)
        # =====================================================================
        print("📋 5. RECENT ZONES SAMPLE (5 per TF)")
        print("-" * 80)
        
        recent_zones = {}
        for tf in ['15m', '1h', '4h', '1d']:
            cursor.execute("""
                SELECT 
                    zone_id,
                    symbol,
                    kind,
                    low,
                    high,
                    strength,
                    meta,
                    updated_at
                FROM sr_zones_v3
                WHERE tf = ?
                ORDER BY updated_at DESC
                LIMIT 5
            """, (tf,))
            
            zones = []
            for row in cursor.fetchall():
                meta = json.loads(row['meta']) if row['meta'] else {}
                zone = {
                    "zone_id": row['zone_id'],
                    "symbol": row['symbol'],
                    "kind": row['kind'],
                    "low": row['low'],
                    "high": row['high'],
                    "strength": row['strength'],
                    "flipped": meta.get('flipped'),
                    "flip_side": meta.get('flip_side'),
                    "touches": meta.get('touches'),
                    "reactions": meta.get('reactions'),
                    "updated_at": row['updated_at']
                }
                zones.append(zone)
            
            recent_zones[tf] = zones
            
            print(f"\n  {tf} zones:")
            for z in zones:
                flipped_status = "✓" if z['flipped'] else "✗"
                print(f"    [{flipped_status}] {z['symbol']:>12} {z['kind']} | "
                      f"Strength: {z['strength']:>5.1f} | "
                      f"Range: {z['low']:.4f}-{z['high']:.4f} | "
                      f"Touches: {z.get('touches', 0)} | "
                      f"Reactions: {z.get('reactions', 0)}")
        
        results["analysis"]["recent_zones_sample"] = recent_zones
        print()
        
        # =====================================================================
        # 6. FLIPPED ZONES EXAMPLES (если есть)
        # =====================================================================
        print("🔄 6. FLIPPED ZONES EXAMPLES")
        print("-" * 80)
        
        cursor.execute("""
            SELECT 
                zone_id,
                symbol,
                tf,
                kind,
                low,
                high,
                strength,
                meta
            FROM sr_zones_v3
            WHERE json_extract(meta, '$.flipped') = 1
            LIMIT 10
        """)
        
        flipped_zones = []
        flipped_rows = cursor.fetchall()
        
        if not flipped_rows:
            print("  ❌ NO FLIPPED ZONES FOUND!")
            print("  ⚠️  This is likely the main reason for 0 signals!")
        else:
            for row in flipped_rows:
                meta = json.loads(row['meta']) if row['meta'] else {}
                zone = {
                    "zone_id": row['zone_id'],
                    "symbol": row['symbol'],
                    "tf": row['tf'],
                    "kind": row['kind'],
                    "low": row['low'],
                    "high": row['high'],
                    "strength": row['strength'],
                    "flip_side": meta.get('flip_side'),
                    "flip_ts": meta.get('flip_ts')
                }
                flipped_zones.append(zone)
                
                print(f"  {zone['symbol']:>12} {zone['tf']:>4} {zone['kind']} | "
                      f"Strength: {zone['strength']:>5.1f} | "
                      f"Flip from: {zone.get('flip_side', 'N/A')} | "
                      f"Range: {zone['low']:.4f}-{zone['high']:.4f}")
        
        results["analysis"]["flipped_zones_examples"] = flipped_zones
        print()
        
        # =====================================================================
        # 7. SUMMARY & RECOMMENDATIONS
        # =====================================================================
        print("=" * 80)
        print("📊 DIAGNOSTIC SUMMARY")
        print("=" * 80)
        
        # Total zones
        cursor.execute("SELECT COUNT(*) as total FROM sr_zones_v3")
        total_zones = cursor.fetchone()['total']
        print(f"Total zones in database: {total_zones}")
        
        # Flipped zones count
        cursor.execute("""
            SELECT COUNT(*) as flipped 
            FROM sr_zones_v3 
            WHERE json_extract(meta, '$.flipped') = 1
        """)
        total_flipped = cursor.fetchone()['flipped']
        flipped_pct = (total_flipped / total_zones * 100) if total_zones > 0 else 0
        print(f"Flipped zones: {total_flipped} ({flipped_pct:.1f}%)")
        
        # Usable zones (strength >= 60)
        cursor.execute("""
            SELECT COUNT(*) as usable 
            FROM sr_zones_v3 
            WHERE strength >= 60
        """)
        usable_zones = cursor.fetchone()['usable']
        usable_pct = (usable_zones / total_zones * 100) if total_zones > 0 else 0
        print(f"Usable zones (strength≥60): {usable_zones} ({usable_pct:.1f}%)")
        
        print()
        print("🔍 CRITICAL FINDINGS:")
        
        issues = []
        
        if flipped_pct < 10:
            issue = f"❌ CRITICAL: Only {flipped_pct:.1f}% zones are flipped!"
            print(f"  {issue}")
            print("     → Flip-Retest setup will NEVER trigger (requires flipped=true)")
            issues.append(issue)
        
        if usable_pct < 30:
            issue = f"⚠️  WARNING: Only {usable_pct:.1f}% zones meet strength threshold"
            print(f"  {issue}")
            print("     → Consider lowering zone_min_strength from 60 to 40")
            issues.append(issue)
        
        if total_flipped == 0:
            issue = "❌ CRITICAL: ZERO flipped zones in entire database!"
            print(f"  {issue}")
            print("     → This is the PRIMARY reason for 0 signals")
            issues.append(issue)
        
        if not issues:
            print("  ✅ No critical issues found in zone data")
        
        results["summary"] = {
            "total_zones": total_zones,
            "flipped_zones": total_flipped,
            "flipped_percentage": flipped_pct,
            "usable_zones": usable_zones,
            "usable_percentage": usable_pct,
            "critical_issues": issues
        }
        
        print()
        
    except Exception as e:
        print(f"❌ ERROR during analysis: {e}")
        import traceback
        traceback.print_exc()
        results["error"] = str(e)
    
    finally:
        conn.close()
    
    # Сохранить результаты в JSON
    output_file = f"v3_zones_diagnostic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print("=" * 80)
    print(f"✅ Analysis complete!")
    print(f"📄 Full report saved to: {output_file}")
    print("=" * 80)


if __name__ == "__main__":
    analyze_v3_zones()
