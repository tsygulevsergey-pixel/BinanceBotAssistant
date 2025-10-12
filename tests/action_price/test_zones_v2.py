"""
Unit тесты для S/R Zones V2

Проверяют:
- Определение касаний (touch detection)
- Recency scoring (затухание со временем)
- Touch penalty (пенализация множественных касаний)
- Zone strength calculation
"""
import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.action_price.zones import SRZoneBuilder


class TestZonesV2(unittest.TestCase):
    """Тесты для зон S/R V2"""
    
    def setUp(self):
        """Инициализация"""
        self.config = {
            'swing_k_1d': 2,
            'swing_k_4h': 3,
            'width_mult_1d': 0.5,
            'width_mult_4h': 0.3,
            'merge_distance_mult': 1.5,
            'mtr_period_1d': 50,
            'mtr_period_4h': 50,
            'touch_shadow_in_zone_ratio': 0.33,
            'touch_gap_bars_4h': 5,
            'touch_weight_cap': 2.0,
            'touch_penalty_threshold': 4,
            'touch_penalty_mult': 0.25,
            'recency_decay_days': 30,
            'zone_score_weight': 4.0,
            'zones_distance_k_atr': 3.0,
            'zones_top_per_side': 3,
            'v2': {
                'touch_shadow_in_zone_strict': 0.5,
                'touch_gap_bars_strict': 8,
                'recency_boost_days': 7,
                'recency_boost_mult': 1.5
            }
        }
        self.parent_config = {'version': 'v2'}
        self.zones = SRZoneBuilder(self.config, parent_config=self.parent_config)
    
    def create_candles_1d(self, num_bars=100):
        """Создать дневные свечи"""
        dates = pd.date_range(start='2025-01-01', periods=num_bars, freq='1D')
        df = pd.DataFrame({
            'open': np.random.uniform(95, 105, num_bars),
            'high': np.random.uniform(105, 110, num_bars),
            'low': np.random.uniform(90, 95, num_bars),
            'close': np.random.uniform(95, 105, num_bars),
            'volume': np.random.uniform(1000, 5000, num_bars)
        }, index=dates)
        return df
    
    def create_candles_4h(self, num_bars=200):
        """Создать 4-часовые свечи"""
        dates = pd.date_range(start='2025-01-01', periods=num_bars, freq='4H')
        df = pd.DataFrame({
            'open': np.random.uniform(95, 105, num_bars),
            'high': np.random.uniform(105, 110, num_bars),
            'low': np.random.uniform(90, 95, num_bars),
            'close': np.random.uniform(95, 105, num_bars),
            'volume': np.random.uniform(1000, 5000, num_bars)
        }, index=dates)
        return df
    
    # ==================== TOUCH DETECTION TESTS ====================
    
    def test_touch_detection_shadow_in_zone(self):
        """Тест V2: касание если тень >= 50% в зоне (strict)"""
        zone = {'high': 105, 'low': 100, 'type': 'supply'}
        
        # Касание: low=102, high=106 → тень в зоне = 3, ширина зоны = 5 → 60% > 50%
        candle = pd.Series({
            'open': 103, 'high': 106, 'low': 102, 'close': 104,
            'timestamp': datetime(2025, 1, 15)
        })
        
        is_touch = self.zones._check_touch_v2(candle, zone, zone_width=5)
        self.assertTrue(is_touch)
    
    def test_touch_detection_no_touch(self):
        """Тест V2: НЕ касание если тень < 50% в зоне"""
        zone = {'high': 105, 'low': 100, 'type': 'supply'}
        
        # Касание слабое: low=103, high=106 → тень в зоне = 2, ширина = 5 → 40% < 50%
        candle = pd.Series({
            'open': 104, 'high': 106, 'low': 103, 'close': 105,
            'timestamp': datetime(2025, 1, 15)
        })
        
        is_touch = self.zones._check_touch_v2(candle, zone, zone_width=5)
        self.assertFalse(is_touch)
    
    def test_touch_anti_dither_gap(self):
        """Тест V2: анти-дребезг - минимум 8 баров между касаниями"""
        zone = {
            'high': 105, 'low': 100, 'type': 'supply',
            'touches': [],
            'last_touch_bar': 10
        }
        
        # Касание на баре 15 → gap = 5 < 8 → не считается
        candle = pd.Series({
            'open': 103, 'high': 106, 'low': 101, 'close': 104,
            'timestamp': datetime(2025, 1, 15)
        })
        
        # Эмуляция: current_bar = 15
        result = self.zones._should_count_touch_v2(zone, current_bar=15, gap_bars=8)
        self.assertFalse(result)
        
        # Касание на баре 20 → gap = 10 > 8 → считается
        result = self.zones._should_count_touch_v2(zone, current_bar=20, gap_bars=8)
        self.assertTrue(result)
    
    # ==================== RECENCY SCORING TESTS ====================
    
    def test_recency_score_fresh(self):
        """Тест: высокий recency для свежих зон (<7 дней)"""
        now = datetime(2025, 1, 15)
        zone_time = datetime(2025, 1, 10)  # 5 дней назад
        
        recency = self.zones._calculate_recency_v2(zone_time, now, 
                                                    boost_days=7, boost_mult=1.5,
                                                    decay_days=30)
        
        self.assertGreater(recency, 1.0)  # Бустер активен
    
    def test_recency_score_old(self):
        """Тест: низкий recency для старых зон (>30 дней)"""
        now = datetime(2025, 2, 15)
        zone_time = datetime(2025, 1, 1)  # 45 дней назад
        
        recency = self.zones._calculate_recency_v2(zone_time, now,
                                                    boost_days=7, boost_mult=1.5,
                                                    decay_days=30)
        
        self.assertLess(recency, 0.5)  # Сильное затухание
    
    # ==================== TOUCH PENALTY TESTS ====================
    
    def test_touch_penalty_few_touches(self):
        """Тест: нет пенализации при малом числе касаний (<= 4)"""
        touches_count = 3
        penalty = self.zones._calculate_touch_penalty(touches_count, 
                                                       threshold=4, mult=0.25)
        
        self.assertEqual(penalty, 0.0)
    
    def test_touch_penalty_many_touches(self):
        """Тест: пенализация при многих касаниях (> 4)"""
        touches_count = 6  # 6 касаний → penalty = (6-4) * 0.25 = 0.5
        penalty = self.zones._calculate_touch_penalty(touches_count,
                                                       threshold=4, mult=0.25)
        
        self.assertAlmostEqual(penalty, 0.5, places=2)
    
    # ==================== ZONE STRENGTH TESTS ====================
    
    def test_zone_strength_calculation(self):
        """Тест: расчёт силы зоны (touches + recency - penalty)"""
        zone = {
            'touches': [
                {'timestamp': datetime(2025, 1, 10)},
                {'timestamp': datetime(2025, 1, 12)},
                {'timestamp': datetime(2025, 1, 14)}
            ],
            'timestamp': datetime(2025, 1, 10)
        }
        
        strength = self.zones._calculate_zone_strength_v2(
            zone, 
            current_time=datetime(2025, 1, 15),
            touch_cap=2.0,
            penalty_threshold=4,
            penalty_mult=0.25,
            recency_decay=30,
            recency_boost_days=7,
            recency_boost_mult=1.5
        )
        
        self.assertGreater(strength, 0.0)
        self.assertLessEqual(strength, 4.0)  # Max = touch_cap + recency


if __name__ == '__main__':
    unittest.main()
