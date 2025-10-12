"""
Unit тесты для Price Action Patterns V2

Проверяют:
- Базовое распознавание паттернов (pin-bar, engulfing, etc)
- V2 pattern quality scoring
- Граничные случаи
"""
import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.action_price.patterns import PriceActionPatterns


class TestPatternsV2(unittest.TestCase):
    """Тесты для паттернов Action Price V2"""
    
    def setUp(self):
        """Инициализация перед каждым тестом"""
        self.config = {
            'enabled': ['pin_bar', 'engulfing', 'inside_bar', 'fakey', 'ppr'],
            'eps_mult': 0.0001,
            'pin_bar': {
                'wick_body_ratio': 2.0,
                'wick_range_ratio': 0.6,
                'opposite_wick_max': 0.25,
                'close_position': 0.6
            },
            'engulfing': {
                'body_ratio': 0.8
            },
            'fakey': {
                'sequence_bars': 3
            },
            'v2': {
                'wick_body_min': 3.0,
                'wick_body_perfect': 5.0,
                'close_position_min': 0.7,
                'close_position_perfect': 0.85,
                'engulfing_body_min': 1.0,
                'engulfing_body_perfect': 1.5,
                'pattern_score_weight': 3.0
            }
        }
        self.patterns = PriceActionPatterns(self.config)
    
    def create_candles(self, candle_data):
        """Создать DataFrame из списка свечей"""
        df = pd.DataFrame(candle_data)
        df['timestamp'] = pd.date_range(start='2025-01-01', periods=len(df), freq='1H')
        df.set_index('timestamp', inplace=True)
        return df
    
    # ==================== PIN-BAR TESTS ====================
    
    def test_pin_bar_bullish_basic(self):
        """Тест: базовый бычий Pin-Bar"""
        candles = [
            {'open': 100, 'high': 102, 'low': 95, 'close': 101},  # Бычий Pin-Bar
        ]
        df = self.create_candles(candles)
        
        result = self.patterns.detect_pin_bar(df, 'LONG')
        self.assertTrue(result['detected'])
        self.assertEqual(result['direction'], 'LONG')
    
    def test_pin_bar_bearish_basic(self):
        """Тест: базовый медвежий Pin-Bar"""
        candles = [
            {'open': 100, 'high': 105, 'low': 98, 'close': 99},  # Медвежий Pin-Bar
        ]
        df = self.create_candles(candles)
        
        result = self.patterns.detect_pin_bar(df, 'SHORT')
        self.assertTrue(result['detected'])
        self.assertEqual(result['direction'], 'SHORT')
    
    def test_pin_bar_v2_quality_scoring(self):
        """Тест V2: скоринг качества Pin-Bar"""
        # Perfect Pin-Bar: wick/body >= 5.0, close >= 0.85
        candles = [
            {'open': 100, 'high': 101, 'low': 90, 'close': 100.9},  # Идеальный
        ]
        df = self.create_candles(candles)
        
        parent_config = {'version': 'v2'}
        result = self.patterns.detect_pin_bar(df, 'LONG', parent_config=parent_config)
        
        self.assertTrue(result['detected'])
        self.assertAlmostEqual(result['pattern_score'], 3.0, places=1)  # Максимум
    
    def test_pin_bar_weak_quality(self):
        """Тест V2: слабый Pin-Bar с низким скором"""
        # Weak: wick/body = 2.5, close = 0.7
        candles = [
            {'open': 100, 'high': 101, 'low': 95, 'close': 100.5},  
        ]
        df = self.create_candles(candles)
        
        parent_config = {'version': 'v2'}
        result = self.patterns.detect_pin_bar(df, 'LONG', parent_config=parent_config)
        
        self.assertTrue(result['detected'])
        self.assertLess(result['pattern_score'], 2.0)  # Слабый скор
    
    # ==================== ENGULFING TESTS ====================
    
    def test_engulfing_bullish(self):
        """Тест: бычий Engulfing"""
        candles = [
            {'open': 100, 'high': 101, 'low': 99, 'close': 99.5},   # Медвежья
            {'open': 99, 'high': 102, 'low': 98, 'close': 102},     # Engulfing
        ]
        df = self.create_candles(candles)
        
        result = self.patterns.detect_engulfing(df, 'LONG')
        self.assertTrue(result['detected'])
    
    def test_engulfing_v2_quality(self):
        """Тест V2: качество Engulfing по размеру body"""
        candles = [
            {'open': 100, 'high': 101, 'low': 99, 'close': 99.5},   # Prev body=0.5
            {'open': 99, 'high': 103, 'low': 98, 'close': 103},     # Body=4.0 → ratio=8.0
        ]
        df = self.create_candles(candles)
        
        parent_config = {'version': 'v2'}
        result = self.patterns.detect_engulfing(df, 'LONG', parent_config=parent_config)
        
        self.assertTrue(result['detected'])
        self.assertGreater(result['pattern_score'], 2.5)  # Высокий скор
    
    # ==================== INSIDE-BAR TESTS ====================
    
    def test_inside_bar_basic(self):
        """Тест: базовый Inside-Bar"""
        candles = [
            {'open': 100, 'high': 105, 'low': 95, 'close': 102},   # Mother
            {'open': 101, 'high': 103, 'low': 99, 'close': 102},   # Inside
        ]
        df = self.create_candles(candles)
        
        result = self.patterns.detect_inside_bar(df, trend='LONG')
        self.assertTrue(result['detected'])
    
    # ==================== FAKEY TESTS ====================
    
    def test_fakey_bullish(self):
        """Тест: бычий Fakey"""
        candles = [
            {'open': 100, 'high': 105, 'low': 95, 'close': 102},   # Mother
            {'open': 101, 'high': 103, 'low': 99, 'close': 100},   # Inside
            {'open': 100, 'high': 104, 'low': 93, 'close': 103},   # Fakey breakout
        ]
        df = self.create_candles(candles)
        
        result = self.patterns.detect_fakey(df, 'LONG')
        self.assertTrue(result['detected'])
    
    # ==================== PPR TESTS ====================
    
    def test_ppr_bullish(self):
        """Тест: бычий PPR (Pivot Point Reversal)"""
        candles = [
            {'open': 100, 'high': 101, 'low': 95, 'close': 96},    # Первая down
            {'open': 96, 'high': 97, 'low': 92, 'close': 93},      # Вторая down (pivot)
            {'open': 93, 'high': 99, 'low': 92, 'close': 98},      # Reversal up
        ]
        df = self.create_candles(candles)
        
        result = self.patterns.detect_ppr(df, 'LONG')
        self.assertTrue(result['detected'])


if __name__ == '__main__':
    unittest.main()
