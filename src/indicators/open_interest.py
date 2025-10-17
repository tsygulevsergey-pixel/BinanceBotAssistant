import pandas as pd
from typing import Dict, Optional
from src.utils.logger import logger


class OpenInterestCalculator:
    """
    Расчёт метрик Open Interest для торговых стратегий
    
    Open Interest Delta (OI Delta) - изменение открытого интереса
    - Положительное: новые позиции открываются (бычий сигнал)
    - Отрицательное: позиции закрываются (медвежий сигнал)
    
    DOI% (Delta OI Percentage) - процентное изменение OI за период
    """
    
    @staticmethod
    def calculate_oi_delta(current_oi: float, previous_oi: float) -> float:
        """
        Рассчитать абсолютное изменение Open Interest
        
        Args:
            current_oi: Текущий Open Interest
            previous_oi: Предыдущий Open Interest
        
        Returns:
            Delta OI (изменение)
        """
        return current_oi - previous_oi
    
    @staticmethod
    def calculate_doi_pct(current_oi: float, previous_oi: float) -> float:
        """
        Рассчитать процентное изменение Open Interest (DOI%)
        
        Args:
            current_oi: Текущий Open Interest
            previous_oi: Предыдущий Open Interest
        
        Returns:
            DOI% (процентное изменение)
        """
        if previous_oi == 0:
            return 0.0
        
        delta = current_oi - previous_oi
        doi_pct = (delta / previous_oi) * 100
        
        return doi_pct
    
    @staticmethod
    def calculate_oi_metrics_from_hist(oi_hist: list, lookback: int = 5) -> Dict[str, float]:
        """
        Рассчитать метрики OI из исторических данных
        
        Args:
            oi_hist: Список словарей с Open Interest историей
                     [{'openInterest': float, 'timestamp': int}, ...]
            lookback: Количество периодов назад для сравнения
        
        Returns:
            Dict с метриками: {'oi_delta': float, 'doi_pct': float, 'current_oi': float}
        """
        if not oi_hist or len(oi_hist) < 2:
            return {
                'oi_delta': 0.0,
                'doi_pct': 0.0,
                'current_oi': 0.0,
                'data_valid': False  # Флаг что данные - fallback
            }
        
        # Сортируем по timestamp (от старых к новым)
        sorted_hist = sorted(oi_hist, key=lambda x: x.get('timestamp', 0))
        
        # Текущий OI (последний)
        current_oi = float(sorted_hist[-1].get('openInterest', 0))
        
        # Предыдущий OI (lookback периодов назад)
        lookback_idx = max(0, len(sorted_hist) - 1 - lookback)
        previous_oi = float(sorted_hist[lookback_idx].get('openInterest', 0))
        
        # Рассчитываем метрики
        oi_delta = OpenInterestCalculator.calculate_oi_delta(current_oi, previous_oi)
        doi_pct = OpenInterestCalculator.calculate_doi_pct(current_oi, previous_oi)
        
        return {
            'oi_delta': oi_delta,
            'doi_pct': doi_pct,
            'current_oi': current_oi,
            'previous_oi': previous_oi,
            'data_valid': True  # Флаг что данные реальные
        }
    
    @staticmethod
    async def fetch_and_calculate_oi(client, symbol: str, period: str = '5m', 
                                     limit: int = 30, lookback: int = 5) -> Dict[str, float]:
        """
        Получить OI данные из API и рассчитать метрики
        
        Args:
            client: BinanceClient instance
            symbol: Trading symbol (e.g., 'BTCUSDT')
            period: Period for OI history ('5m', '15m', '30m', '1h', etc.)
            limit: Number of data points to fetch
            lookback: Periods to look back for delta calculation
        
        Returns:
            Dict с метриками OI
        """
        try:
            # Получаем историю Open Interest
            oi_hist = await client.get_open_interest_hist(
                symbol=symbol,
                period=period,
                limit=limit
            )
            
            if not oi_hist:
                logger.debug(f"No OI history data for {symbol}")
                return {
                    'oi_delta': 0.0,
                    'doi_pct': 0.0,
                    'current_oi': 0.0,
                    'data_valid': False  # Флаг что данные - fallback
                }
            
            # Рассчитываем метрики
            metrics = OpenInterestCalculator.calculate_oi_metrics_from_hist(
                oi_hist, 
                lookback=lookback
            )
            
            # КРИТИЧНО: INFO логирование для видимости реальных значений
            logger.info(f"📊 {symbol} OI: Current={metrics['current_oi']:.0f}, "
                       f"Delta={metrics['oi_delta']:.0f}, DOI%={metrics['doi_pct']:.2f}%")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error fetching OI for {symbol}: {e}")
            return {
                'oi_delta': 0.0,
                'doi_pct': 0.0,
                'current_oi': 0.0,
                'data_valid': False  # Флаг что данные - fallback
            }


def calculate_oi_delta(current_oi: float, previous_oi: float) -> float:
    """Standalone функция для совместимости"""
    return OpenInterestCalculator.calculate_oi_delta(current_oi, previous_oi)


def calculate_doi_pct(current_oi: float, previous_oi: float) -> float:
    """Standalone функция для совместимости"""
    return OpenInterestCalculator.calculate_doi_pct(current_oi, previous_oi)
