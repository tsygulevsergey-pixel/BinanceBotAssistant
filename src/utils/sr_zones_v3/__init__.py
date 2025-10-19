"""
Support/Resistance Zones V3 - Professional Implementation
Based on institutional trading methodology (2024-2025)

Multi-timeframe analysis: D → H4 → H1 → M15
Features:
- DBSCAN clustering for zone consolidation
- Validated reaction strength measurement
- Adaptive zone width by timeframe and volatility
- R⇄S flip mechanism with confirmation
- Multi-factor scoring system
- Confluence detection
"""

from .builder import SRZonesV3Builder

__all__ = ['SRZonesV3Builder']
