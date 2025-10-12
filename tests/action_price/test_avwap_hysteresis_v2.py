"""
Unit тесты для AVWAP Hysteresis V2

Проверяют:
- Гистерезис "2 из 3 условий"
- Анти-дребезг (минимум 1 день между переякорениями)
- V1/V2 совместимость
"""
import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.action_price.avwap import AnchoredVWAP


class TestAVWAPHysteresisV2(unittest.TestCase):
    """Тесты для AVWAP hysteresis V2"""
    
    def setUp(self):
        """Инициализация"""
        self.config = {
            'fractal_k_1h': 3,
            'fractal_k_4h': 2,
            'impulse_mult': 1.5,
            'impulse_bars_1h': 12,
            'impulse_bars_4h': 10,
            'lock_bars_1h': 8,
            'lock_bars_4h': 4,
            'ttl_bars_1h': 60,
            'ttl_bars_4h': 30,
            'structure_break_closes': 3,
            'structure_break_closes_4h': 2,
            'structure_distance_mult': 0.25,
            'confluence_tolerance_mult': 0.5,
            'anchor_15m_primary': '1h',
            'anchor_15m_secondary': '4h',
            'anchor_1h_primary': '4h',
            'anchor_1h_secondary': '1d',
            'v2': {
                'hysteresis_impulse_mult': 1.5,
                'hysteresis_min_bars_1h': 30,
                'hysteresis_distance_mult': 2.0,
                'hysteresis_conditions_required': 2,
                'anti_dither_min_days': 1
            }
        }
        self.avwap = AnchoredVWAP(self.config)
        self.parent_config_v2 = {'version': 'v2'}
        self.parent_config_v1 = {'version': 'v1'}
    
    def create_candles(self, num_bars=100, base_price=100):
        """Создать детерминированные свечи"""
        np.random.seed(42)  # Фиксированный seed
        dates = pd.date_range(start='2025-01-01', periods=num_bars, freq='h')
        df = pd.DataFrame({
            'open': base_price + np.random.uniform(-2, 2, num_bars),
            'high': base_price + np.random.uniform(0, 5, num_bars),
            'low': base_price + np.random.uniform(-5, 0, num_bars),
            'close': base_price + np.random.uniform(-2, 2, num_bars),
            'volume': np.random.uniform(1000, 5000, num_bars)
        }, index=dates)
        return df
    
    # ==================== HYSTERESIS "2 of 3" TESTS ====================
    
    def test_hysteresis_all_3_conditions_met(self):
        """Тест: все 3 условия выполнены → переякорить"""
        df = self.create_candles(100, base_price=100)
        
        # Создаём старый якорь
        anchor = {
            'index': 10,
            'price': 100.0,
            'timestamp': df.index[10],
            'direction': 'up',
            'impulse': 5.0
        }
        
        # Мокаем find_valid_swing для нового якоря с сильным импульсом
        def mock_find_swing(df, tf):
            from src.action_price.utils import calculate_mtr
            mtr = calculate_mtr(df, 20)
            return {
                'index': 80,
                'price': 115.0,  # Далеко от 100.0
                'timestamp': df.index[80],
                'direction': 'up',
                'impulse': 3.0 * mtr  # Гарантированно >= 1.5×MTR
            }
        
        original_find_swing = self.avwap.find_valid_swing
        self.avwap.find_valid_swing = mock_find_swing
        
        try:
            result = self.avwap.check_hysteresis_v2(
                'BTCUSDT', df, '1h', anchor, self.parent_config_v2
            )
            # Все 3 условия: импульс(ДА: 3×MTR), время(ДА: 70 баров > 30), дистанция(ДА: |115-100|=15)
            self.assertTrue(result, "Все 3 условия должны дать True")
        finally:
            self.avwap.find_valid_swing = original_find_swing
    
    def test_hysteresis_only_2_conditions_met(self):
        """Тест: 2 из 3 условий → переякорить"""
        df = self.create_candles(100, base_price=100)
        
        anchor = {
            'index': 65,  # 35 баров назад (> 30 → время OK)
            'price': 100.0,
            'timestamp': df.index[65],
            'direction': 'up',
            'impulse': 3.0
        }
        
        # Новый якорь с сильным импульсом, НО близкая цена
        def mock_find_swing(df, tf):
            from src.action_price.utils import calculate_mtr
            mtr = calculate_mtr(df, 20)
            return {
                'index': 95,
                'price': 100.5,  # Близко к 100.0 → дистанция НЕТ
                'timestamp': df.index[95],
                'direction': 'up',
                'impulse': 2.0 * mtr  # Сильный импульс → импульс ДА
            }
        
        original_find_swing = self.avwap.find_valid_swing
        self.avwap.find_valid_swing = mock_find_swing
        
        try:
            result = self.avwap.check_hysteresis_v2(
                'BTCUSDT', df, '1h', anchor, self.parent_config_v2
            )
            # 2 условия: импульс(ДА), время(ДА: 30 баров), дистанция(НЕТ: близко)
            # 2 из 3 → переякорить
            self.assertTrue(result, "2 из 3 условий должны дать True")
        finally:
            self.avwap.find_valid_swing = original_find_swing
    
    def test_hysteresis_only_1_condition_met(self):
        """Тест: только 1 условие → НЕ переякорить"""
        df = self.create_candles(100, base_price=100)
        
        anchor = {
            'index': 90,  # Очень недавно (10 баров)
            'price': 100.0,
            'timestamp': df.index[90],
            'direction': 'up',
            'impulse': 3.0
        }
        
        # Слабый новый якорь
        def mock_find_swing(df, tf):
            return {
                'index': 95,
                'price': 100.5,  # Близко к старому
                'timestamp': df.index[95],
                'direction': 'up',
                'impulse': 0.5  # Слабый импульс
            }
        
        original_find_swing = self.avwap.find_valid_swing
        self.avwap.find_valid_swing = mock_find_swing
        
        try:
            result = self.avwap.check_hysteresis_v2(
                'BTCUSDT', df, '1h', anchor, self.parent_config_v2
            )
            # Только 0-1 условие выполнено → False
            self.assertFalse(result)
        finally:
            self.avwap.find_valid_swing = original_find_swing
    
    def test_hysteresis_v1_disabled(self):
        """Тест: V1 - hysteresis отключён"""
        df = self.create_candles(100)
        anchor = {
            'index': 50,
            'price': 100.0,
            'timestamp': df.index[50],
            'direction': 'up',
            'impulse': 3.0
        }
        
        result = self.avwap.check_hysteresis_v2(
            'BTCUSDT', df, '1h', anchor, self.parent_config_v1
        )
        # V1 → возвращает False (отключено)
        self.assertFalse(result)
    
    # ==================== ANTI-DITHER TESTS ====================
    
    def test_anti_dither_first_reanchor(self):
        """Тест: первое переякорение → разрешено"""
        new_time = datetime(2025, 1, 15, 10, 0)
        
        result = self.avwap.check_anti_dither_v2(
            'BTCUSDT', '1h', new_time, self.parent_config_v2
        )
        
        self.assertTrue(result)  # Нет истории → OK
    
    def test_anti_dither_too_soon(self):
        """Тест: переякорение < 1 день → запрещено"""
        # Первое переякорение
        first_time = datetime(2025, 1, 15, 10, 0)
        self.avwap.reanchor_history = {
            'BTCUSDT': {
                '1h': [first_time]
            }
        }
        
        # Второе через 12 часов
        second_time = first_time + timedelta(hours=12)
        
        result = self.avwap.check_anti_dither_v2(
            'BTCUSDT', '1h', second_time, self.parent_config_v2
        )
        
        self.assertFalse(result)  # < 1 день → блокировать
    
    def test_anti_dither_after_1_day(self):
        """Тест: переякорение > 1 день → разрешено"""
        # Первое переякорение
        first_time = datetime(2025, 1, 15, 10, 0)
        self.avwap.reanchor_history = {
            'BTCUSDT': {
                '1h': [first_time]
            }
        }
        
        # Второе через 2 дня
        second_time = first_time + timedelta(days=2)
        
        result = self.avwap.check_anti_dither_v2(
            'BTCUSDT', '1h', second_time, self.parent_config_v2
        )
        
        self.assertTrue(result)  # >= 1 день → OK
    
    def test_anti_dither_v1_disabled(self):
        """Тест: V1 - анти-дребезг отключён"""
        new_time = datetime(2025, 1, 15, 10, 0)
        
        result = self.avwap.check_anti_dither_v2(
            'BTCUSDT', '1h', new_time, self.parent_config_v1
        )
        
        self.assertTrue(result)  # V1 → всегда True (без ограничений)
    
    # ==================== INTEGRATION TESTS ====================
    
    def test_get_avwap_v2_uses_hysteresis(self):
        """Тест: get_avwap V2 использует hysteresis и записывает историю"""
        df = self.create_candles(100, base_price=100)
        
        # Первый вызов с force_recalc
        avwap_v2 = self.avwap.get_avwap(
            'BTCUSDT_V2', df, '1h', force_recalc=True,
            parent_config=self.parent_config_v2
        )
        
        # Проверяем что V2 записал историю
        self.assertIn('BTCUSDT_V2', self.avwap.reanchor_history,
                      "V2 должен записать историю переякорений")
        self.assertIsNotNone(avwap_v2)
    
    def test_get_avwap_v1_uses_old_logic(self):
        """Тест: get_avwap V1 НЕ записывает историю (старая логика)"""
        df = self.create_candles(100, base_price=100)
        
        # V1 вызов с force_recalc
        avwap_v1 = self.avwap.get_avwap(
            'BTCUSDT_V1', df, '1h', force_recalc=True,
            parent_config=self.parent_config_v1
        )
        
        # V1 НЕ должен записывать историю
        self.assertNotIn('BTCUSDT_V1', self.avwap.reanchor_history,
                        "V1 НЕ должен записывать историю переякорений")
        self.assertIsNotNone(avwap_v1)
    
    def test_reanchor_history_recorded(self):
        """Тест: история переякорений записывается"""
        df = self.create_candles(100, base_price=100)
        
        # Принудительное переякорение
        self.avwap.get_avwap(
            'ETHUSDT', df, '1h', force_recalc=True, 
            parent_config=self.parent_config_v2
        )
        
        # Проверяем что история ТОЧНО записана
        self.assertIn('ETHUSDT', self.avwap.reanchor_history, 
                      "Symbol должен быть в истории")
        self.assertIn('1h', self.avwap.reanchor_history['ETHUSDT'], 
                      "Timeframe должен быть в истории")
        self.assertGreater(len(self.avwap.reanchor_history['ETHUSDT']['1h']), 0,
                          "История должна содержать записи")


if __name__ == '__main__':
    unittest.main()
