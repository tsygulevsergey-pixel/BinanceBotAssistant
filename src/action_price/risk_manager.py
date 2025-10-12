"""
Risk Management для Action Price: расчёт стопов, целей, R:R
"""
import pandas as pd
from typing import Dict, Optional, List, Tuple
from .utils import calculate_buffer, calculate_rr_ratio


class ActionPriceRiskManager:
    """Управление рисками для Action Price сигналов"""
    
    def __init__(self, config: dict):
        """
        Args:
            config: Конфигурация из config.yaml['action_price']['entry']
        """
        self.config = config
        self.buffer_atr_mult = config.get('buffer_atr_mult', 0.25)
        self.buffer_min_pct = config.get('buffer_min_pct', 0.05)
        
        self.tp1_rr = config.get('tp1_rr', 1.0)
        self.tp2_rr = config.get('tp2_rr', 2.0)
        self.partial_tp1 = config.get('partial_tp1', 0.5)
        self.partial_tp2 = config.get('partial_tp2', 0.5)
        
        self.min_rr_zone = config.get('min_rr_zone', 1.0)
        self.breakeven_rr = config.get('breakeven_rr', 1.0)
    
    def calculate_stop_loss(self, direction: str, zone: Dict, mtr: float, 
                           current_price: float) -> float:
        """
        Рассчитать стоп-лосс ЗА ЗОНОЙ с буфером
        
        Args:
            direction: Направление сделки
            zone: Зона S/R от которой идет сигнал
            mtr: median True Range
            current_price: Текущая цена
            
        Returns:
            Уровень стоп-лосс
        """
        buffer = calculate_buffer(mtr, current_price, 
                                 self.buffer_atr_mult, 
                                 self.buffer_min_pct)
        
        if direction == 'LONG':
            # Стоп ниже зоны поддержки (demand) с буфером
            stop_loss = zone['low'] - buffer
        else:  # SHORT
            # Стоп выше зоны сопротивления (supply) с буфером
            stop_loss = zone['high'] + buffer
        
        return stop_loss
    
    def find_nearest_opposite_zone(self, entry: float, direction: str, 
                                   zones: List[Dict]) -> Optional[Dict]:
        """
        Найти ближайшую противоположную зону
        
        Args:
            entry: Цена входа
            direction: Направление сделки
            zones: Список зон S/R
            
        Returns:
            Ближайшая противоположная зона или None
        """
        opposite_zones = []
        
        for zone in zones:
            zone_center = (zone['low'] + zone['high']) / 2
            
            if direction == 'LONG':
                # Ищем supply зоны выше entry
                if zone['type'] == 'supply' and zone_center > entry:
                    distance = zone_center - entry
                    opposite_zones.append({'zone': zone, 'distance': distance})
            else:  # SHORT
                # Ищем demand зоны ниже entry
                if zone['type'] == 'demand' and zone_center < entry:
                    distance = entry - zone_center
                    opposite_zones.append({'zone': zone, 'distance': distance})
        
        if not opposite_zones:
            return None
        
        # Возвращаем ближайшую
        nearest = min(opposite_zones, key=lambda x: x['distance'])
        return nearest['zone']
    
    def calculate_targets(self, entry: float, stop_loss: float, 
                         direction: str, zones: List[Dict]) -> Tuple[float, Optional[float]]:
        """
        Рассчитать TP1 и TP2
        
        Args:
            entry: Цена входа
            stop_loss: Стоп-лосс
            direction: Направление
            zones: Зоны S/R
            
        Returns:
            (TP1, TP2) - цены целей
        """
        risk = abs(entry - stop_loss)
        
        # TP1 = entry + RR × risk
        if direction == 'LONG':
            tp1 = entry + self.tp1_rr * risk
            tp2_rr = entry + self.tp2_rr * risk
        else:  # SHORT
            tp1 = entry - self.tp1_rr * risk
            tp2_rr = entry - self.tp2_rr * risk
        
        # TP2: берём ближайшую зону или 2R (что ближе)
        nearest_zone = self.find_nearest_opposite_zone(entry, direction, zones)
        
        if nearest_zone:
            zone_target = (nearest_zone['low'] + nearest_zone['high']) / 2
            
            if direction == 'LONG':
                tp2 = min(tp2_rr, zone_target)  # Что ближе
            else:  # SHORT
                tp2 = max(tp2_rr, zone_target)  # Что ближе
        else:
            tp2 = tp2_rr
        
        return tp1, tp2
    
    def validate_rr_to_zone(self, entry: float, stop_loss: float,
                           direction: str, zones: List[Dict]) -> bool:
        """
        Проверить что до противоположной зоны >= min_rr_zone
        
        Args:
            entry: Цена входа
            stop_loss: Стоп-лосс
            direction: Направление
            zones: Зоны S/R
            
        Returns:
            True если R:R достаточен
        """
        nearest_zone = self.find_nearest_opposite_zone(entry, direction, zones)
        
        if not nearest_zone:
            return True  # Нет противоположной зоны - разрешаем
        
        zone_center = (nearest_zone['low'] + nearest_zone['high']) / 2
        rr = calculate_rr_ratio(entry, stop_loss, zone_center)
        
        return rr >= self.min_rr_zone
    
    def calculate_entry_stop_targets(self, direction: str, zone: Dict, mtr: float,
                                     current_price: float, 
                                     zones: List[Dict]) -> Optional[Dict]:
        """
        Рассчитать полную информацию о входе, стопе и целях
        
        Args:
            direction: Направление сделки
            zone: Зона S/R от которой идет сигнал
            mtr: median True Range
            current_price: Текущая актуальная цена (используется как ENTRY!)
            zones: Все зоны S/R
            
        Returns:
            Dict с entry/stop/tp1/tp2 или None если не проходит фильтры
        """
        # ENTRY = ТЕКУЩАЯ ЦЕНА (не историческая!)
        entry = current_price
        
        # Рассчитываем стоп ЗА ЗОНОЙ
        stop_loss = self.calculate_stop_loss(direction, zone, mtr, current_price)
        
        # Валидация минимального R:R до противоположной зоны
        if not self.validate_rr_to_zone(entry, stop_loss, direction, zones):
            return None  # Слишком близко к противоположной зоне
        
        # Рассчитываем цели от ТЕКУЩЕЙ цены
        tp1, tp2 = self.calculate_targets(entry, stop_loss, direction, zones)
        
        # Рассчитываем R:R соотношения
        rr1 = calculate_rr_ratio(entry, stop_loss, tp1)
        rr2 = calculate_rr_ratio(entry, stop_loss, tp2) if tp2 else None
        
        return {
            'entry': entry,
            'stop_loss': stop_loss,
            'take_profit_1': tp1,
            'take_profit_2': tp2,
            'risk': abs(entry - stop_loss),
            'rr1': rr1,
            'rr2': rr2,
            'partial_tp1_pct': self.partial_tp1,
            'partial_tp2_pct': self.partial_tp2
        }
