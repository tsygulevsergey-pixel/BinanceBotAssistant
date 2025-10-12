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
