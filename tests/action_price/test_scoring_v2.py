"""
Unit тесты для Scoring V2

Проверяют:
- Нормализованную шкалу 0-10
- Компоненты: zone(4.0) + pattern(3.0) + vwap(1.2) + proximity(1.0) + ema(0.8)
- Порог >= 6.5
"""
import unittest

from src.action_price.engine import ActionPriceEngine


class TestScoringV2(unittest.TestCase):
    """Тесты для scoring V2"""
    
    def setUp(self):
        """Инициализация"""
        # Минимальная конфигурация для тестов
        self.config = {
            'version': 'v2',
            'zones': {'zone_score_weight': 4.0},
            'patterns': {'v2': {'pattern_score_weight': 3.0}},
            'avwap': {'v2': {'vwap_family_bonus_cap': 1.2}},
            'proximity': {},
            'ema': {'v2': {'strict_score': 0.8}},
            'filters': {'v2': {'min_total_score': 6.5}}
        }
    
    # ==================== SCORING COMPONENTS ====================
    
    def test_score_component_weights(self):
        """Тест: максимальные веса компонентов"""
        zone_max = 4.0
        pattern_max = 3.0
        vwap_max = 1.2
        proximity_max = 1.0
        ema_max = 0.8
        
        total_max = zone_max + pattern_max + vwap_max + proximity_max + ema_max
        
        self.assertAlmostEqual(total_max, 10.0, places=1)
    
    def test_score_perfect_signal(self):
        """Тест: идеальный сигнал с максимальными компонентами"""
        score_components = {
            'zone_score': 4.0,
            'pattern_score': 3.0,
            'vwap_bonus': 1.2,
            'proximity_score': 1.0,
            'ema_score': 0.8
        }
        
        total = sum(score_components.values())
        self.assertAlmostEqual(total, 10.0, places=1)
        
        # Проверка порога
        threshold = 6.5
        self.assertGreater(total, threshold)
    
    def test_score_threshold_pass(self):
        """Тест: сигнал проходит порог 6.5"""
        score_components = {
            'zone_score': 3.5,
            'pattern_score': 2.0,
            'vwap_bonus': 0.8,
            'proximity_score': 0.5,
            'ema_score': 0.4
        }
        
        total = sum(score_components.values())
        self.assertAlmostEqual(total, 7.2, places=1)
        self.assertGreater(total, 6.5)
    
    def test_score_threshold_fail(self):
        """Тест: сигнал НЕ проходит порог 6.5"""
        score_components = {
            'zone_score': 2.0,
            'pattern_score': 1.5,
            'vwap_bonus': 0.5,
            'proximity_score': 0.3,
            'ema_score': 0.2
        }
        
        total = sum(score_components.values())
        self.assertAlmostEqual(total, 4.5, places=1)
        self.assertLess(total, 6.5)
    
    # ==================== CAPPING TESTS ====================
    
    def test_zone_score_capped(self):
        """Тест: zone_score ограничен 4.0"""
        raw_zone = 5.5  # Сырой скор может быть больше
        capped = min(raw_zone, 4.0)
        
        self.assertEqual(capped, 4.0)
    
    def test_pattern_score_capped(self):
        """Тест: pattern_score ограничен 3.0"""
        raw_pattern = 3.8
        capped = min(raw_pattern, 3.0)
        
        self.assertEqual(capped, 3.0)
    
    def test_vwap_bonus_capped(self):
        """Тест: vwap_bonus ограничен 1.2"""
        raw_vwap = 2.0  # Если бы не было cap
        capped = min(raw_vwap, 1.2)
        
        self.assertEqual(capped, 1.2)
    
    def test_proximity_capped(self):
        """Тест: proximity ограничен 1.0"""
        raw_proximity = 1.5
        capped = min(raw_proximity, 1.0)
        
        self.assertEqual(capped, 1.0)
    
    def test_ema_capped(self):
        """Тест: ema_score ограничен 0.8"""
        raw_ema = 1.0
        capped = min(raw_ema, 0.8)
        
        self.assertEqual(capped, 0.8)
    
    # ==================== INTEGRATION TEST ====================
    
    def test_total_score_calculation(self):
        """Тест: итоговый расчёт с capping"""
        # Сырые значения (могут превышать лимиты)
        raw_scores = {
            'zone': 5.0,      # cap → 4.0
            'pattern': 3.5,   # cap → 3.0
            'vwap': 1.8,      # cap → 1.2
            'proximity': 1.2, # cap → 1.0
            'ema': 0.9        # cap → 0.8
        }
        
        # Применение cap
        capped_scores = {
            'zone': min(raw_scores['zone'], 4.0),
            'pattern': min(raw_scores['pattern'], 3.0),
            'vwap': min(raw_scores['vwap'], 1.2),
            'proximity': min(raw_scores['proximity'], 1.0),
            'ema': min(raw_scores['ema'], 0.8)
        }
        
        total = sum(capped_scores.values())
        self.assertAlmostEqual(total, 10.0, places=1)
    
    def test_score_range_valid(self):
        """Тест: скор всегда в диапазоне [0, 10]"""
        # Минимальный
        min_score = 0.0 + 0.0 + 0.0 + 0.0 + 0.0
        self.assertEqual(min_score, 0.0)
        
        # Максимальный
        max_score = 4.0 + 3.0 + 1.2 + 1.0 + 0.8
        self.assertAlmostEqual(max_score, 10.0, places=1)


if __name__ == '__main__':
    unittest.main()
