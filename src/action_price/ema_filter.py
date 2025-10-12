"""
EMA фильтры для определения тренда в Action Price
"""
import pandas as pd
from typing import Optional, Dict


class EMAFilter:
    """EMA фильтр для проверки тренда"""
    
    def __init__(self, config: dict):
        """
        Args:
            config: Конфигурация из config.yaml['action_price']['ema']
        """
        self.config = config
        self.periods = config.get('periods', [50, 200])
        self.timeframes = config.get('timeframes', ['4h', '1h'])
        self.strict_mode = config.get('strict_mode', True)
        self.aggressive_mode = config.get('aggressive_mode', False)
    
    def calculate_ema(self, df: pd.DataFrame, period: int) -> Optional[float]:
        """
        Рассчитать EMA для таймфрейма
        
        Args:
            df: DataFrame с close ценами
            period: Период EMA
            
        Returns:
            Текущее значение EMA или None
        """
        if len(df) < period:
            return None
        
        ema = df['close'].ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1])
    
    def get_ema_values(self, df_4h: pd.DataFrame, df_1h: pd.DataFrame) -> Dict:
        """
        Получить все EMA значения для обоих таймфреймов
        
        Args:
            df_4h: 4H свечи
            df_1h: 1H свечи
            
        Returns:
            Dict с EMA значениями
        """
        ema_50_4h = self.calculate_ema(df_4h, 50)
        ema_200_4h = self.calculate_ema(df_4h, 200)
        ema_50_1h = self.calculate_ema(df_1h, 50)
        ema_200_1h = self.calculate_ema(df_1h, 200)
        
        return {
            'ema_50_4h': ema_50_4h,
            'ema_200_4h': ema_200_4h,
            'ema_50_1h': ema_50_1h,
            'ema_200_1h': ema_200_1h,
            'close_4h': float(df_4h['close'].iloc[-1]) if len(df_4h) > 0 else None,
            'close_1h': float(df_1h['close'].iloc[-1]) if len(df_1h) > 0 else None
        }
    
    def check_trend(self, df_4h: pd.DataFrame, df_1h: pd.DataFrame, 
                    direction: str) -> tuple[bool, Dict]:
        """
        Проверить разрешён ли тренд для направления
        
        Args:
            df_4h: 4H свечи
            df_1h: 1H свечи
            direction: 'LONG' или 'SHORT'
            
        Returns:
            (allowed, ema_values) - разрешён ли и значения EMA
        """
        emas = self.get_ema_values(df_4h, df_1h)
        
        # Проверка наличия данных
        if None in [emas['ema_50_4h'], emas['ema_200_4h'], 
                    emas['ema_50_1h'], emas['ema_200_1h'],
                    emas['close_4h'], emas['close_1h']]:
            return False, emas
        
        # Условия для LONG
        if direction == 'LONG':
            h4_bullish = emas['close_4h'] > emas['ema_200_4h']
            h1_bullish = emas['ema_50_1h'] > emas['ema_200_1h']
            
            if self.strict_mode:
                # Строгий режим: оба ТФ должны быть bullish
                allowed = h4_bullish and h1_bullish
            else:
                # Aggressive режим: достаточно одного
                allowed = h4_bullish or h1_bullish if self.aggressive_mode else h4_bullish and h1_bullish
            
            return allowed, emas
        
        # Условия для SHORT
        elif direction == 'SHORT':
            h4_bearish = emas['close_4h'] < emas['ema_200_4h']
            h1_bearish = emas['ema_50_1h'] < emas['ema_200_1h']
            
            if self.strict_mode:
                # Строгий режим: оба ТФ должны быть bearish
                allowed = h4_bearish and h1_bearish
            else:
                # Aggressive режим: достаточно одного
                allowed = h4_bearish or h1_bearish if self.aggressive_mode else h4_bearish and h1_bearish
            
            return allowed, emas
        
        return False, emas
    
    def check_trend_v2(self, df_4h: pd.DataFrame, df_1h: pd.DataFrame, 
                      direction: str, parent_config: dict = None) -> tuple[bool, float, Dict]:
        """
        V2: Проверить тренд с pullback exception
        
        Логика:
        - H4 + H1 OK → allowed=True, score=0.8 (strict_score)
        - H4 OK, H1 pullback → allowed=True, score=0.4 (pullback_score)
        - Иначе → allowed=False, score=0
        
        Args:
            df_4h: 4H свечи
            df_1h: 1H свечи
            direction: 'LONG' или 'SHORT'
            parent_config: Полная конфигурация action_price для v2 параметров
            
        Returns:
            (allowed, score, ema_values)
        """
        emas = self.get_ema_values(df_4h, df_1h)
        
        # Проверка наличия данных
        if None in [emas['ema_50_4h'], emas['ema_200_4h'], 
                    emas['ema_50_1h'], emas['ema_200_1h'],
                    emas['close_4h'], emas['close_1h']]:
            return False, 0.0, emas
        
        # Параметры v2 из parent_config (или fallback на self.config)
        if parent_config:
            v2_config = parent_config.get('ema', {}).get('v2', {})
        else:
            v2_config = self.config.get('v2', {})
        
        strict_score = v2_config.get('strict_score', 0.8)
        pullback_score = v2_config.get('pullback_score', 0.4)
        
        # Проверка трендов
        h4_bullish = emas['close_4h'] > emas['ema_200_4h']
        h4_bearish = emas['close_4h'] < emas['ema_200_4h']
        h1_bullish = emas['ema_50_1h'] > emas['ema_200_1h']
        h1_bearish = emas['ema_50_1h'] < emas['ema_200_1h']
        
        if direction == 'LONG':
            # Строгое совпадение: H4 bullish + H1 bullish
            if h4_bullish and h1_bullish:
                return True, strict_score, emas
            
            # Pullback exception: H4 bullish, H1 делает pullback (bearish)
            if h4_bullish and h1_bearish:
                return True, pullback_score, emas
            
            return False, 0.0, emas
        
        elif direction == 'SHORT':
            # Строгое совпадение: H4 bearish + H1 bearish
            if h4_bearish and h1_bearish:
                return True, strict_score, emas
            
            # Pullback exception: H4 bearish, H1 делает pullback (bullish)
            if h4_bearish and h1_bullish:
                return True, pullback_score, emas
            
            return False, 0.0, emas
        
        return False, 0.0, emas
