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
        # Передаём entry_config + parent version для v2 логики
        entry_config = config['entry'].copy()
        entry_config['version'] = config.get('version', 'v1')
        self.risk_manager = ActionPriceRiskManager(entry_config)
        self.cooldown = ActionPriceCooldown(config['cooldown'])
        
        # Daily VWAP расчёт
        from src.indicators.vwap import VWAPCalculator
        self.daily_vwap = VWAPCalculator()
    
    def _check_super_chop_filter_v2(self, symbol: str, df_1h: pd.DataFrame) -> bool:
        """
        V2: Проверить фильтр super-chop (низкая волатильность)
        
        Блокировать если ВСЕ 3 условия выполнены:
        - ADX(H1) < 14
        - ATR%(H1) < p30
        - BBW(H1) < p30
        
        Args:
            df_1h: Часовые свечи
            
        Returns:
            True если супер-пила (блокировать сигнал)
        """
        if self.config.get('version') != 'v2':
            return False  # V1 - фильтр отключён
        
        v2_filters = self.config.get('filters', {}).get('v2', {})
        adx_threshold = v2_filters.get('adx_threshold_1h', 14)
        atr_pct_percentile = v2_filters.get('atr_pct_percentile', 30)
        bbw_percentile = v2_filters.get('bbw_percentile', 30)
        lookback_days = v2_filters.get('percentile_lookback_days', 90)
        
        # Рассчитать ADX на H1
        import pandas_ta as ta
        adx = ta.adx(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
        if adx is None or len(adx) == 0:
            return False
        
        current_adx = adx['ADX_14'].iloc[-1]
        
        # Рассчитать ATR% на H1
        atr = ta.atr(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
        if atr is None or len(atr) == 0:
            return False
        
        current_price = df_1h['close'].iloc[-1]
        atr_pct = (atr.iloc[-1] / current_price) * 100
        
        # Рассчитать BBW на H1
        bb = ta.bbands(df_1h['close'], length=20, std=2)
        if bb is None or len(bb) == 0:
            return False
        
        # Найти правильные названия колонок (pandas_ta может использовать разные форматы)
        bb_cols = bb.columns.tolist()
        upper_col = [c for c in bb_cols if 'BBU' in c][0] if any('BBU' in c for c in bb_cols) else None
        lower_col = [c for c in bb_cols if 'BBL' in c][0] if any('BBL' in c for c in bb_cols) else None
        middle_col = [c for c in bb_cols if 'BBM' in c][0] if any('BBM' in c for c in bb_cols) else None
        
        if not (upper_col and lower_col and middle_col):
            return False  # BB колонки не найдены
        
        bb_upper = bb[upper_col]
        bb_lower = bb[lower_col]
        bb_middle = bb[middle_col]
        
        current_bbw = ((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_middle.iloc[-1]) * 100
        
        # Рассчитать перцентили за lookback_days
        lookback_bars = lookback_days * 24  # H1 → 24 бара в день
        lookback_bars = min(lookback_bars, len(df_1h) - 1)
        
        if lookback_bars < 100:
            return False  # Недостаточно данных
        
        # ATR% перцентиль
        atr_pct_series = (atr.tail(lookback_bars) / df_1h['close'].tail(lookback_bars)) * 100
        atr_pct_p30 = atr_pct_series.quantile(atr_pct_percentile / 100)
        
        # BBW перцентиль
        bbw_series = ((bb_upper - bb_lower) / bb_middle * 100).tail(lookback_bars)
        bbw_p30 = bbw_series.quantile(bbw_percentile / 100)
        
        # Проверка всех 3 условий
        condition_adx = current_adx < adx_threshold
        condition_atr = atr_pct < atr_pct_p30
        condition_bbw = current_bbw < bbw_p30
        
        is_super_chop = condition_adx and condition_atr and condition_bbw
        
        if is_super_chop:
            logger.info(
                f"🚫 Super-chop filter: {symbol} blocked "
                f"(ADX={current_adx:.1f}<{adx_threshold}, "
                f"ATR%={atr_pct:.3f}<{atr_pct_p30:.3f}, "
                f"BBW={current_bbw:.2f}<{bbw_p30:.2f})"
            )
        
        return is_super_chop
    
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
        
        # V2: Проверка super-chop фильтра
        if self._check_super_chop_filter_v2(symbol, df_1h):
            return []  # Блокировать symbol из-за низкой волатильности
        
        # 1. Получить зоны S/R
        zones = self.zone_builder.get_zones(symbol, df_1d, df_4h, current_price)
        if not zones:
            return []
        
        # 2. Получить Anchored VWAP
        df_primary = df_1h if timeframe == '15m' else df_4h
        df_secondary = df_4h if timeframe == '15m' else df_1d
        
        avwap_data = self.avwap_calc.get_dual_avwap(symbol, df_primary, 
                                                     df_secondary, timeframe,
                                                     parent_config=self.config)
        
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
                pattern_zone, mtr_1h, direction
            )
            
            # Рассчитать EMA score
            ema_score = ema_score_long if direction == 'LONG' else ema_score_short
            
            # V2: Рассчитать pattern quality (нужно для total score)
            pattern_quality = 0.0
            if self.config.get('version') == 'v2':
                candle_data = pattern.get('candle_data', {})
                if candle_data:
                    # Извлекаем последнюю свечу в зависимости от типа паттерна
                    pattern_type = pattern['type']
                    
                    if pattern_type in ('pin_bar', 'engulfing'):
                        # Плоский dict с OHLC
                        candle_dict = candle_data
                    elif pattern_type == 'inside_bar':
                        # Используем inside bar (последняя свеча)
                        candle_dict = candle_data.get('inside', {})
                    elif pattern_type == 'fakey':
                        # Используем fakey свечу (последняя свеча)
                        candle_dict = candle_data.get('fakey', {})
                    elif pattern_type == 'ppr':
                        # Используем current свечу
                        candle_dict = candle_data.get('current', {})
                    else:
                        candle_dict = {}
                    
                    if candle_dict and 'open' in candle_dict:
                        # Создаём Series из dict для calculate_pattern_quality_v2
                        import pandas as pd
                        candle_series = pd.Series(candle_dict)
                        pattern_quality = self.patterns.calculate_pattern_quality_v2(
                            candle_series, direction, mtr_exec, self.config
                        )
            
            # Рассчитать score
            if self.config.get('version') == 'v2':
                # V2: Нормализованный total score 0-10
                vwap_bonus = confluence_flags.get('vwap_bonus', 0.0)
                confidence = self.calculate_total_score_v2(
                    pattern_zone, pattern_quality, vwap_bonus, ema_score
                )
                
                # Проверка минимального порога V2
                min_score_v2 = self.config.get('filters', {}).get('v2', {}).get('min_total_score', 6.5)
                if confidence < min_score_v2:
                    continue  # Слишком низкий score - пропускаем
            else:
                # V1: Старая логика
                confidence = self.calculate_confidence(confluence_flags, pattern_zone, ema_score)
                
                # Проверка минимального порога V1
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
                'pattern_quality': pattern_quality,  # V2: pattern quality [0..1]
                
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
                         mtr_1h: float, direction: Optional[str] = None) -> Dict:
        """
        Проверить конфлюэнсы для сигнала
        
        V1: Проксимальность к VWAP без проверки вектора
        V2: Проверка вектора + cap +1.2 для VWAP-семейства
        
        Args:
            price: Текущая цена
            avwap_data: Данные AVWAP
            daily_vwap: Daily VWAP
            zone: Зона S/R
            mtr_1h: mTR для 1H
            direction: Направление сделки (для V2 проверки вектора)
            
        Returns:
            Dict с флагами конфлюэнсов
        """
        flags = {
            'avwap_primary': False,
            'avwap_secondary': False,
            'daily_vwap': False,
            'zone_sr': True,  # Всегда True т.к. мы в зоне
            'count': 1,  # Зона уже +1
            'vwap_bonus': 0.0  # V2: суммарный бонус от VWAP-семейства
        }
        
        version = self.config.get('version', 'v1')
        
        if version == 'v2' and direction is not None:
            # V2: Проверка вектора + cap бонуса
            v2_config = self.config.get('avwap', {}).get('v2', {})
            proximity_beta = v2_config.get('vwap_proximity_beta', 1.0)
            vwap_cap = v2_config.get('vwap_family_bonus_cap', 1.2)
            
            vwap_bonus = 0.0
            
            # AVWAP Primary с вектором
            if avwap_data['primary'] is not None:
                if self._check_vwap_vector_v2(price, avwap_data['primary'], direction, proximity_beta, mtr_1h):
                    flags['avwap_primary'] = True
                    flags['count'] += 1
                    vwap_bonus += 0.5
            
            # AVWAP Secondary с вектором
            if avwap_data['secondary'] is not None:
                if self._check_vwap_vector_v2(price, avwap_data['secondary'], direction, proximity_beta, mtr_1h):
                    flags['avwap_secondary'] = True
                    flags['count'] += 1
                    vwap_bonus += 0.4
            
            # Daily VWAP с вектором
            if daily_vwap is not None:
                if self._check_vwap_vector_v2(price, daily_vwap, direction, proximity_beta, mtr_1h):
                    flags['daily_vwap'] = True
                    flags['count'] += 1
                    vwap_bonus += 0.3
            
            # Cap суммарного бонуса
            flags['vwap_bonus'] = min(vwap_bonus, vwap_cap)
            
        else:
            # V1: старая логика без вектора
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
    
    def _check_vwap_vector_v2(self, price: float, vwap: Optional[float], 
                             direction: str, proximity_beta: float, 
                             mtr: float) -> bool:
        """
        V2: Проверить VWAP конфлюэнс с учётом вектора
        
        Args:
            price: Текущая цена
            vwap: Значение VWAP
            direction: Направление сделки
            proximity_beta: Множитель для проверки близости
            mtr: MTR для расчёта толерантности
            
        Returns:
            True если вектор правильный И цена близко к VWAP
        """
        if vwap is None:
            return False
        
        # Проверка близости: |price - vwap| <= beta × MTR
        distance = abs(price - vwap)
        tolerance = proximity_beta * mtr
        
        if distance > tolerance:
            return False  # Слишком далеко
        
        # Проверка вектора
        if direction == 'LONG':
            # LONG: цена должна быть выше VWAP (поддержка снизу)
            return price >= vwap
        else:  # SHORT
            # SHORT: цена должна быть ниже VWAP (сопротивление сверху)
            return price <= vwap
    
    def calculate_total_score_v2(self, zone: Dict, pattern_quality: float, 
                                 vwap_bonus: float, ema_score: float) -> float:
        """
        V2: Рассчитать нормализованный total score 0-10
        
        Компоненты:
        - zone_score: 4.0 (max)
        - pattern_quality: 3.0 (max)
        - vwap_bonus: 1.2 (max)
        - proximity: 1.0 (max)
        - ema: 0.8 (max)
        
        Args:
            zone: Зона S/R (содержит score и proximity_score)
            pattern_quality: Качество паттерна [0..1]
            vwap_bonus: VWAP бонус (уже с cap 1.2)
            ema_score: EMA score (0.8/0.4/0)
            
        Returns:
            Total score [0..10]
        """
        score = 0.0
        
        # Zone strength (max 4.0)
        zone_score = zone.get('score', 0.0)
        score += min(zone_score, 4.0)
        
        # Pattern quality (max 3.0)
        pattern_score = pattern_quality * 3.0
        score += min(pattern_score, 3.0)
        
        # VWAP bonus (max 1.2, уже capped)
        score += min(vwap_bonus, 1.2)
        
        # Proximity (max 1.0)
        proximity_score = zone.get('proximity_score', 0.0)
        score += min(proximity_score, 1.0)
        
        # EMA (max 0.8)
        score += min(ema_score, 0.8)
        
        return round(score, 2)
    
    def calculate_confidence(self, confluence_flags: Dict, zone: Dict, ema_score: float = 0.8) -> float:
        """
        Рассчитать confidence score для сигнала
        
        V1: Старая логика с count*0.5 + primary +1.0
        V2: Использует vwap_bonus с cap +1.2
        
        Args:
            confluence_flags: Флаги конфлюэнсов (с vwap_bonus для V2)
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
        
        # Проверяем V2 через наличие vwap_bonus
        if 'vwap_bonus' in confluence_flags and confluence_flags['vwap_bonus'] > 0:
            # V2: Используем vwap_bonus с cap
            score += confluence_flags['vwap_bonus']
        else:
            # V1: Старая логика
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
