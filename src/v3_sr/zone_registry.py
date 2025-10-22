"""
Zone Registry - Единый реестр зон для всех Signal Engines

Хранит только Active/Key зоны из V3 builder
Предоставляет доступ по TF и HTF фильтры
"""

import hashlib
from typing import Dict, List, Optional
from datetime import datetime


class ZoneRegistry:
    """
    Центральный реестр V3 S/R зон
    
    Фильтрует и предоставляет доступ к Active/Key зонам
    для Signal Engines M15 и H1
    """
    
    def __init__(self):
        """Initialize empty registry"""
        self._zones_by_tf: Dict[str, List[Dict]] = {
            '15m': [],
            '1h': [],
            '4h': [],
            '1d': []
        }
        self._last_update_ts: Optional[int] = None
    
    def update(self, zones_by_tf: Dict[str, List[Dict]], as_of_ts: int) -> None:
        """
        Обновить реестр зон из V3 builder
        
        Фильтрует только Active/Key зоны и нормализует формат
        
        Args:
            zones_by_tf: Output from SRZonesV3Builder.build_zones()
            as_of_ts: Timestamp обновления
        """
        self._last_update_ts = as_of_ts
        
        for tf in ['15m', '1h', '4h', '1d']:
            raw_zones = zones_by_tf.get(tf, [])
            
            # Filter только Active/Key зоны
            filtered = []
            for zone in raw_zones:
                lifecycle_state = zone.get('lifecycle_state', 'candidate')
                
                if lifecycle_state in ['active', 'key']:
                    # Normalize zone format
                    normalized = self._normalize_zone(zone, as_of_ts)
                    filtered.append(normalized)
            
            self._zones_by_tf[tf] = filtered
    
    def get_zones(self, tf: str) -> List[Dict]:
        """
        Получить зоны для конкретного TF
        
        Args:
            tf: Timeframe ('15m', '1h', '4h', '1d')
        
        Returns:
            Список зон для этого TF (только Active/Key)
        """
        return self._zones_by_tf.get(tf, [])
    
    def get_htf_zones(self) -> Dict[str, List[Dict]]:
        """
        Получить HTF зоны (4h и 1d)
        
        Returns:
            {'4h': [...], '1d': [...]}
        """
        return {
            '4h': self._zones_by_tf.get('4h', []),
            '1d': self._zones_by_tf.get('1d', [])
        }
    
    def get_nearest_htf_bands(self, 
                             price: float, 
                             symbol: str,
                             direction: str = 'LONG') -> Dict:
        """
        Найти ближайшие HTF "стены" по направлению
        
        Args:
            price: Текущая цена
            symbol: Символ (для фильтрации)
            direction: 'LONG' или 'SHORT'
        
        Returns:
            {
                'nearest_resistance': {'zone': {...}, 'distance_atr': float},
                'nearest_support': {'zone': {...}, 'distance_atr': float},
                'influencing_zones': [...]  # HTF зоны в зоне влияния
            }
        """
        htf_zones = []
        
        # Собрать все HTF зоны (4h + 1d)
        for tf in ['4h', '1d']:
            for zone in self._zones_by_tf.get(tf, []):
                if zone['symbol'] == symbol:
                    htf_zones.append(zone)
        
        if not htf_zones:
            return {
                'nearest_resistance': None,
                'nearest_support': None,
                'influencing_zones': []
            }
        
        # Найти ближайшее сопротивление выше цены
        resistances = [z for z in htf_zones if z['kind'] == 'R' and z['low'] > price]
        nearest_resistance = None
        if resistances:
            nearest_resistance = min(resistances, key=lambda z: z['low'] - price)
        
        # Найти ближайшую поддержку ниже цены
        supports = [z for z in htf_zones if z['kind'] == 'S' and z['high'] < price]
        nearest_support = None
        if supports:
            nearest_support = max(supports, key=lambda z: price - z['high'])
        
        # Зоны влияния (price внутри зоны ± margin)
        influencing_zones = []
        for zone in htf_zones:
            # Margin для влияния = ширина зоны
            zone_width = zone['high'] - zone['low']
            margin = zone_width * 1.5
            
            if zone['low'] - margin <= price <= zone['high'] + margin:
                influencing_zones.append(zone)
        
        return {
            'nearest_resistance': nearest_resistance,
            'nearest_support': nearest_support,
            'influencing_zones': influencing_zones
        }
    
    def _normalize_zone(self, raw_zone: Dict, as_of_ts: int) -> Dict:
        """
        Нормализовать зону в стандартный формат для registry
        
        Args:
            raw_zone: Zone из V3 builder
            as_of_ts: Timestamp обновления
        
        Returns:
            Normalized zone dict
        """
        # Generate deterministic zone_id
        zone_id = self._generate_zone_id(raw_zone)
        
        # Extract class from lifecycle_state
        lifecycle_state = raw_zone.get('lifecycle_state', 'candidate')
        zone_class = 'key' if lifecycle_state == 'key' else 'active'
        
        # Build normalized zone
        normalized = {
            'zone_id': zone_id,
            'symbol': raw_zone.get('symbol', 'BTCUSDT'),
            'tf': raw_zone.get('tf'),
            'kind': raw_zone.get('kind'),
            'low': raw_zone.get('low'),
            'high': raw_zone.get('high'),
            'mid': raw_zone.get('mid'),
            'strength': raw_zone.get('strength', 0),
            'class': zone_class,
            'meta': {
                'purity': raw_zone.get('purity', 0.0),
                'kde_prominence': raw_zone.get('kde_prominence', 0.0),
                'htf_overlap': raw_zone.get('htf_overlap', []),
                'touches': raw_zone.get('touches', 0),
                'last_reaction_atr': raw_zone.get('last_reaction_atr', 0.0),
            },
            'updated_ts': as_of_ts
        }
        
        return normalized
    
    def _generate_zone_id(self, zone: Dict) -> str:
        """
        Generate deterministic zone ID
        
        Args:
            zone: Zone dict
        
        Returns:
            Hash string
        """
        # Use symbol, tf, low, high, kind for deterministic ID
        symbol = zone.get('symbol', 'UNKNOWN')
        tf = zone.get('tf', 'unknown')
        kind = zone.get('kind', 'S')
        low = zone.get('low', 0)
        high = zone.get('high', 0)
        
        # Create hash
        hash_input = f"{symbol}_{tf}_{kind}_{int(low*1000)}_{int(high*1000)}"
        zone_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        
        return zone_id
    
    @property
    def last_update_ts(self) -> Optional[int]:
        """Get timestamp of last update"""
        return self._last_update_ts
    
    def get_zone_count(self, tf: Optional[str] = None) -> int:
        """
        Получить количество зон
        
        Args:
            tf: Конкретный TF или None для всех
        
        Returns:
            Количество зон
        """
        if tf:
            return len(self._zones_by_tf.get(tf, []))
        else:
            return sum(len(zones) for zones in self._zones_by_tf.values())
