"""
Action Price Engine - основной движок стратегии
"""
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime
import hashlib
import pytz
import logging

logger = logging.getLogger(__name__)

from .zones import SRZoneBuilder
from .avwap import AnchoredVWAP
from .ema_filter import EMAFilter
from .patterns import PriceActionPatterns
from .risk_manager import ActionPriceRiskManager
from .cooldown import ActionPriceCooldown
from .utils import calculate_mtr, is_price_in_zone


class ActionPriceEngine:
    """Главный движок Action Price стратегии"""
    
    def __init__(self, config: dict, binance_client=None):
        """
        Args:
            config: Полная конфигурация из config.yaml['action_price']
            binance_client: BinanceClient для получения актуальной цены
        """
        self.config = config
        self.enabled = config.get('enabled', True)
        self.client = binance_client
        
        # Инициализация компонентов (передаём parent_config для version)
        self.zone_builder = SRZoneBuilder(config['zones'], parent_config=config)
        self.avwap_calc = AnchoredVWAP(config['avwap'])
        self.ema_filter = EMAFilter(config['ema'])
        self.patterns = PriceActionPatterns(config['patterns'])
        self.risk_manager = ActionPriceRiskManager(config['entry'])
        self.cooldown = ActionPriceCooldown(config['cooldown'])
        
        # Daily VWAP расчёт
        from src.indicators.vwap import VWAPCalculator
        self.daily_vwap = VWAPCalculator()
    
    async def analyze_symbol(self, symbol: str, df_1d: pd.DataFrame, 
                       df_4h: pd.DataFrame, df_1h: pd.DataFrame, 
                       df_15m: pd.DataFrame, timeframe: str,
                       current_time: datetime) -> List[Dict]:
        """
        Анализ символа на паттерны Action Price
        
        Args:
            symbol: Символ
            df_1d: Дневные свечи
            df_4h: 4-часовые свечи
            df_1h: Часовые свечи
            df_15m: 15-минутные свечи
            timeframe: Таймфрейм исполнения ('15m' или '1h')
            current_time: Текущее время UTC
            
        Returns:
            Список сигналов Action Price
        """
        if not self.enabled:
            return []
        
        signals = []
        
        # Определяем execution DataFrame
        df_exec = df_1h if timeframe == '1h' else df_15m
        
        if len(df_exec) < 3 or len(df_4h) < 50 or len(df_1h) < 50:
            return []
        
        # Получаем АКТУАЛЬНУЮ цену с Binance (mark price)
        if self.client:
            try:
                price_data = await self.client.get_mark_price(symbol)
                current_price = float(price_data['markPrice'])
            except Exception as e:
                logger.error(f"Failed to get current price for {symbol}: {e}")
                # Fallback на последнюю закрытую свечу (лучше чем краш)
                current_price = float(df_exec['close'].iloc[-1])
        else:
            # Client не передан (backtesting/тесты) - используем close свечи
            current_price = float(df_exec['close'].iloc[-1])
        
        # 1. Получить зоны S/R
        zones = self.zone_builder.get_zones(symbol, df_1d, df_4h, current_price)
        if not zones:
            return []
        
        # 2. Получить Anchored VWAP
        df_primary = df_1h if timeframe == '15m' else df_4h
        df_secondary = df_4h if timeframe == '15m' else df_1d
        
        avwap_data = self.avwap_calc.get_dual_avwap(symbol, df_primary, 
                                                     df_secondary, timeframe)
        
        # 3. Получить Daily VWAP
        daily_vwap_series = self.daily_vwap.calculate_daily_vwap(df_1h)
        daily_vwap_value = float(daily_vwap_series.iloc[-1]) if daily_vwap_series is not None and len(daily_vwap_series) > 0 else None
        
        # 4. Получить EMA значения и проверить тренд
        if self.config.get('version') == 'v2':
            # V2: возвращает (allowed, score, emas)
            ema_allowed_long, ema_score_long, emas = self.ema_filter.check_trend_v2(df_4h, df_1h, 'LONG', self.config)
            ema_allowed_short, ema_score_short, _ = self.ema_filter.check_trend_v2(df_4h, df_1h, 'SHORT', self.config)
        else:
            # V1: возвращает (allowed, emas)
            ema_allowed_long, emas = self.ema_filter.check_trend(df_4h, df_1h, 'LONG')
            ema_allowed_short, _ = self.ema_filter.check_trend(df_4h, df_1h, 'SHORT')
            ema_score_long = 0.8 if ema_allowed_long else 0.0
            ema_score_short = 0.8 if ema_allowed_short else 0.0
        
        # Определяем направление тренда для inside-bar
        if ema_allowed_long:
            trend_direction = 'LONG'
        elif ema_allowed_short:
            trend_direction = 'SHORT'
        else:
            trend_direction = None
        
        # 5. Детектировать паттерны
        detected_patterns = self.patterns.detect_all_patterns(df_exec, trend_direction)
        
        if not detected_patterns:
            return []
        
        # 6. Обработать каждый паттерн
        mtr_exec = calculate_mtr(df_exec, period=20)
        mtr_1h = calculate_mtr(df_1h, period=20)
        
        for pattern in detected_patterns:
            direction = pattern['direction']
            
            # Проверка EMA фильтра
            if direction == 'LONG' and not ema_allowed_long:
                continue
            if direction == 'SHORT' and not ema_allowed_short:
                continue
            
            # Найти зону для паттерна (проверка близости!)
            pattern_zone = self.find_zone_for_pattern(pattern, zones, current_price, mtr_1h)
            if not pattern_zone:
                continue  # Паттерн далеко от зон - пропускаем!
            
            # Рассчитать риск/цели (используя ТЕКУЩУЮ цену и ЗОНУ)
            risk_data = self.risk_manager.calculate_entry_stop_targets(
                direction, pattern_zone, mtr_exec, current_price, zones
            )
            
            if not risk_data:
                continue  # Не прошёл R:R фильтр
            
            # Примечание: Entry price теперь = current_price (всегда актуальная!)
            # Проверка устаревания больше не требуется
            
            # Проверка cooldown
            if self.cooldown.is_duplicate(symbol, direction, pattern_zone['id'],
                                          pattern['type'], timeframe, current_time):
                continue  # Дубликат - пропускаем
            
            # Проверка конфлюэнсов
            confluence_flags = self.check_confluences(
                current_price, avwap_data, daily_vwap_value, 
                pattern_zone, mtr_1h
            )
            
            # Рассчитать confidence score (передаём ema_score для v2)
            ema_score = ema_score_long if direction == 'LONG' else ema_score_short
            confidence = self.calculate_confidence(confluence_flags, pattern_zone, ema_score)
            
            # Проверка минимального порога confidence
            min_confidence = self.config.get('filters', {}).get('min_confidence_score', 0)
            if confidence < min_confidence:
                continue  # Слишком низкая уверенность - пропускаем
            
            # Создать контекстный хеш
            context_hash = self.generate_context_hash(
                symbol, pattern['type'], direction, pattern_zone['id'], 
                timeframe, current_time
            )
            
            # Собрать сигнал
            signal = {
                'symbol': symbol,
                'pattern_type': pattern['type'],
                'direction': direction,
                'timeframe': timeframe,
                'context_hash': context_hash,
                
                # Зона
                'zone_id': pattern_zone['id'],
                'zone_low': pattern_zone['low'],
                'zone_high': pattern_zone['high'],
                'zone_type': pattern_zone['type'],
                
                # Вход/стопы/цели
                'entry_price': risk_data['entry'],
                'stop_loss': risk_data['stop_loss'],
                'take_profit_1': risk_data['take_profit_1'],
                'take_profit_2': risk_data['take_profit_2'],
                
                # VWAP/EMA
                'avwap_primary': avwap_data['primary'],
                'avwap_secondary': avwap_data['secondary'],
                'daily_vwap': daily_vwap_value,
                
                'ema_50_4h': emas.get('ema_50_4h'),
                'ema_200_4h': emas.get('ema_200_4h'),
                'ema_50_1h': emas.get('ema_50_1h'),
                'ema_200_1h': emas.get('ema_200_1h'),
                
                # Конфлюэнсы и score
                'confidence_score': confidence,
                'confluence_flags': confluence_flags,
                
                # Метаданные
                'meta_data': {
                    'pattern_candle_data': pattern.get('candle_data'),
                    'rr1': risk_data.get('rr1'),
                    'rr2': risk_data.get('rr2'),
                    'risk': risk_data.get('risk'),
                    'zone_score': pattern_zone.get('score'),
                    'zone_touches': pattern_zone.get('touches_recent', 0),
                    'avwap_tf_primary': avwap_data.get('primary_tf'),
                    'avwap_tf_secondary': avwap_data.get('secondary_tf')
                },
                
                'created_at': current_time
            }
            
            signals.append(signal)
        
        return signals
    
    def find_zone_for_pattern(self, pattern: Dict, zones: List[Dict], 
                              current_price: float, mtr: float) -> Optional[Dict]:
        """
        Найти зону S/R для паттерна - ТОЛЬКО если цена возле зоны!
        
        Args:
            pattern: Данные паттерна
            zones: Список зон
            current_price: Текущая цена
            mtr: Median True Range для определения "близости"
            
        Returns:
            Зона или None (если паттерн далеко от зон)
        """
        direction = pattern['direction']
        
        # Для LONG ищем demand зоны, для SHORT - supply
        required_zone_type = 'demand' if direction == 'LONG' else 'supply'
        
        # Проверяем находится ли midpoint свечи в зоне
        candle_data = pattern.get('candle_data', {})
        
        if isinstance(candle_data, dict) and 'high' in candle_data:
            midpoint = (candle_data['high'] + candle_data['low']) / 2
            candle_low = candle_data['low']
            candle_high = candle_data['high']
        else:
            midpoint = current_price
            candle_low = current_price
            candle_high = current_price
        
        # V2 логика (формальная proximity)
        if self.config.get('version') == 'v2':
            from .utils import calculate_proximity_v2
            
            proximity_config = self.config.get('zones', {}).get('v2', {})
            min_overlap = proximity_config.get('overlap_ratio_inside', 0.3)
            max_dist_mult = proximity_config.get('proximity_distance_mult', 1.5)
            
            suitable_zones = [z for z in zones if z['type'] == required_zone_type]
            
            for zone in suitable_zones:
                prox_type, prox_value, prox_score = calculate_proximity_v2(
                    candle_low, candle_high,
                    zone['low'], zone['high'],
                    mtr, min_overlap, max_dist_mult
                )
                
                if prox_type in ('inside', 'near'):
                    zone['proximity_type'] = prox_type
                    zone['proximity_value'] = prox_value
                    zone['proximity_score'] = prox_score
                    return zone
            
            return None
        
        # V1 логика (оригинальная)
        # Ищем подходящую зону
        for zone in zones:
            if zone['type'] == required_zone_type:
                if is_price_in_zone(midpoint, zone['low'], zone['high']):
                    return zone  # Паттерн ВНУТРИ зоны - идеально!
        
        # Если не в зоне, проверяем БЛИЗОСТЬ к ГРАНИЦЕ зоны (макс 2×MTR)
        max_distance = 2.0 * mtr
        suitable_zones = [z for z in zones if z['type'] == required_zone_type]
        
        for zone in suitable_zones:
            # Расстояние до БЛИЖАЙШЕЙ ГРАНИЦЫ зоны (не центра!)
            distance_to_low = abs(midpoint - zone['low'])
            distance_to_high = abs(midpoint - zone['high'])
            distance_to_zone = min(distance_to_low, distance_to_high)
            
            # Паттерн должен быть БЛИЗКО к границе зоны (в пределах 2×MTR)
            if distance_to_zone <= max_distance:
                return zone
        
        # Паттерн далеко от всех зон - отбрасываем!
        return None
    
    def check_confluences(self, price: float, avwap_data: Dict, 
                         daily_vwap: Optional[float], zone: Dict,
                         mtr_1h: float) -> Dict:
        """
        Проверить конфлюэнсы для сигнала
        
        Args:
            price: Текущая цена
            avwap_data: Данные AVWAP
            daily_vwap: Daily VWAP
            zone: Зона S/R
            mtr_1h: mTR для 1H
            
        Returns:
            Dict с флагами конфлюэнсов
        """
        flags = {
            'avwap_primary': False,
            'avwap_secondary': False,
            'daily_vwap': False,
            'zone_sr': True,  # Всегда True т.к. мы в зоне
            'count': 1  # Зона уже +1
        }
        
        # AVWAP Primary
        if self.avwap_calc.check_confluence(price, avwap_data['primary'], mtr_1h):
            flags['avwap_primary'] = True
            flags['count'] += 1
        
        # AVWAP Secondary
        if self.avwap_calc.check_confluence(price, avwap_data['secondary'], mtr_1h):
            flags['avwap_secondary'] = True
            flags['count'] += 1
        
        # Daily VWAP
        if self.avwap_calc.check_confluence(price, daily_vwap, mtr_1h):
            flags['daily_vwap'] = True
            flags['count'] += 1
        
        return flags
    
    def calculate_confidence(self, confluence_flags: Dict, zone: Dict, ema_score: float = 0.8) -> float:
        """
        Рассчитать confidence score для сигнала
        
        Args:
            confluence_flags: Флаги конфлюэнсов
            zone: Зона S/R
            ema_score: EMA score (0.8 для strict, 0.4 для pullback, 0 для reject)
            
        Returns:
            Confidence score
        """
        score = 0.0
        
        # Базовый score от зоны
        score += zone.get('score', 1.0)
        
        # EMA score (0.8 strict, 0.4 pullback, 0 rejected)
        score += ema_score
        
        # Бонус за конфлюэнсы
        score += confluence_flags['count'] * 0.5
        
        # Бонус за AVWAP Primary (важнее)
        if confluence_flags['avwap_primary']:
            score += 1.0
        
        # Бонус за количество касаний зоны
        score += min(zone.get('touches_recent', 0) * 0.2, 1.0)
        
        return round(score, 2)
    
    def generate_context_hash(self, symbol: str, pattern_type: str, 
                              direction: str, zone_id: str, 
                              timeframe: str, timestamp: datetime) -> str:
        """
        Генерировать уникальный хеш для сигнала
        
        Returns:
            MD5 хеш
        """
        hash_string = (
            f"{symbol}_{pattern_type}_{direction}_{zone_id}_"
            f"{timeframe}_{timestamp.strftime('%Y%m%d%H%M')}"
        )
        return hashlib.md5(hash_string.encode()).hexdigest()
