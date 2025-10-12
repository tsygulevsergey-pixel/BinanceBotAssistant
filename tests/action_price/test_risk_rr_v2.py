"""
Unit тесты для R:R проверки V2

Проверяют:
- V2: R:R рассчитывается до boundary зоны (не центра)
- min_rr_zone_v2 = 1.2
- Корректность расчёта distance
"""
import unittest
import pandas as pd

from src.action_price.risk_manager import ActionPriceRiskManager


class TestRiskRRV2(unittest.TestCase):
    """Тесты для R:R проверки V2"""
    
    def setUp(self):
        """Инициализация"""
        self.config_v2 = {
            'version': 'v2',
            'min_rr': 1.5,
            'max_sl_distance_mult': 3.0,
            'v2': {
                'min_rr_zone_v2': 1.2
            }
        }
        self.risk_manager_v2 = ActionPriceRiskManager(self.config_v2)
        
        self.config_v1 = {
            'version': 'v1',
            'min_rr': 1.5,
            'max_sl_distance_mult': 3.0
        }
        self.risk_manager_v1 = ActionPriceRiskManager(self.config_v1)
    
    # ==================== V2 R:R TO ZONE BOUNDARY ====================
    
    def test_rr_v2_long_to_zone_low(self):
        """Тест V2: LONG - расстояние до нижней границы зоны (low)"""
        entry = 100.0
        zone = {'type': 'supply', 'high': 105, 'low': 103}
        mtr_exec = 2.0
        
        result = self.risk_manager_v2.check_rr_v2(entry, zone, 'LONG', mtr_exec)
        
        # distance = entry - zone['low'] = 100 - 103 = -3 (НЕ проходит)
        # Но если зона supply выше entry, то не должна использоваться
        # для LONG (это противоположная зона)
        self.assertFalse(result['valid'])
    
    def test_rr_v2_long_valid(self):
        """Тест V2: LONG с корректной demand зоной"""
        entry = 100.0
        zone = {'type': 'demand', 'high': 97, 'low': 95}
        mtr_exec = 2.0
        
        result = self.risk_manager_v2.check_rr_v2(entry, zone, 'LONG', mtr_exec)
        
        # distance = entry - zone['high'] = 100 - 97 = 3
        # rr = 3 / 2.0 = 1.5 >= 1.2 ✓
        self.assertTrue(result['valid'])
        self.assertAlmostEqual(result['rr'], 1.5, places=1)
    
    def test_rr_v2_short_to_zone_high(self):
        """Тест V2: SHORT - расстояние до верхней границы зоны (high)"""
        entry = 100.0
        zone = {'type': 'supply', 'high': 103, 'low': 101}
        mtr_exec = 2.0
        
        result = self.risk_manager_v2.check_rr_v2(entry, zone, 'SHORT', mtr_exec)
        
        # distance = zone['high'] - entry = 103 - 100 = 3
        # rr = 3 / 2.0 = 1.5 >= 1.2 ✓
        self.assertTrue(result['valid'])
        self.assertAlmostEqual(result['rr'], 1.5, places=1)
    
    def test_rr_v2_insufficient(self):
        """Тест V2: недостаточный R:R < 1.2"""
        entry = 100.0
        zone = {'type': 'demand', 'high': 98.5, 'low': 97}
        mtr_exec = 2.0
        
        result = self.risk_manager_v2.check_rr_v2(entry, zone, 'LONG', mtr_exec)
        
        # distance = 100 - 98.5 = 1.5
        # rr = 1.5 / 2.0 = 0.75 < 1.2 ✗
        self.assertFalse(result['valid'])
    
    # ==================== V1 R:R TO ZONE CENTER ====================
    
    def test_rr_v1_uses_zone_center(self):
        """Тест V1: использует центр зоны"""
        entry = 100.0
        zone = {'type': 'demand', 'high': 97, 'low': 95, 'center': 96}
        mtr_exec = 2.0
        
        # V1 должен использовать center (если есть) или (high+low)/2
        result = self.risk_manager_v1.check_rr(entry, zone, 'LONG', mtr_exec)
        
        # distance = entry - center = 100 - 96 = 4
        # rr = 4 / 2.0 = 2.0 >= 1.5 ✓
        self.assertTrue(result['valid'])
    
    # ==================== EDGE CASES ====================
    
    def test_rr_zero_mtr(self):
        """Тест: MTR = 0 → invalid"""
        entry = 100.0
        zone = {'type': 'demand', 'high': 97, 'low': 95}
        mtr_exec = 0.0
        
        result = self.risk_manager_v2.check_rr_v2(entry, zone, 'LONG', mtr_exec)
        self.assertFalse(result['valid'])
    
    def test_rr_negative_distance(self):
        """Тест: отрицательное расстояние → invalid"""
        entry = 100.0
        zone = {'type': 'demand', 'high': 102, 'low': 101}  # Зона выше entry
        mtr_exec = 2.0
        
        result = self.risk_manager_v2.check_rr_v2(entry, zone, 'LONG', mtr_exec)
        self.assertFalse(result['valid'])


if __name__ == '__main__':
    unittest.main()
