from typing import Dict, List, Optional
from src.utils.logger import logger


class OrderbookAnalyzer:
    """
    Анализ Orderbook для определения дисбаланса ликвидности
    
    Depth Imbalance - показывает баланс между bid и ask ликвидностью
    Значения от -1 до +1:
    - Положительное (> 0): больше bid ликвидности (давление покупателей)
    - Отрицательное (< 0): больше ask ликвидности (давление продавцов)
    - Около 0: сбалансированный orderbook
    """
    
    @staticmethod
    def calculate_depth_imbalance(bids: List[List], asks: List[List], 
                                   depth_levels: int = 10) -> float:
        """
        Рассчитать дисбаланс глубины orderbook
        
        Args:
            bids: Список bid уровней [[price, quantity], ...]
            asks: Список ask уровней [[price, quantity], ...]
            depth_levels: Количество уровней для анализа (default=10)
        
        Returns:
            Depth imbalance от -1 до +1
        """
        if not bids or not asks:
            return 0.0
        
        # Суммируем объёмы на N уровнях
        bid_volume = sum(float(bid[1]) for bid in bids[:depth_levels])
        ask_volume = sum(float(ask[1]) for ask in asks[:depth_levels])
        
        # Формула: (bid_vol - ask_vol) / (bid_vol + ask_vol)
        total_volume = bid_volume + ask_volume
        
        if total_volume == 0:
            return 0.0
        
        imbalance = (bid_volume - ask_volume) / total_volume
        
        return imbalance
    
    @staticmethod
    def calculate_weighted_depth_imbalance(bids: List[List], asks: List[List],
                                           current_price: float,
                                           depth_levels: int = 10) -> float:
        """
        Рассчитать взвешенный дисбаланс (с учётом расстояния от цены)
        Уровни ближе к текущей цене имеют больший вес
        
        Args:
            bids: Список bid уровней [[price, quantity], ...]
            asks: Список ask уровней [[price, quantity], ...]
            current_price: Текущая рыночная цена
            depth_levels: Количество уровней для анализа
        
        Returns:
            Weighted depth imbalance от -1 до +1
        """
        if not bids or not asks or current_price == 0:
            return 0.0
        
        weighted_bid_volume = 0.0
        weighted_ask_volume = 0.0
        
        # Взвешиваем bid уровни
        for i, bid in enumerate(bids[:depth_levels]):
            price = float(bid[0])
            quantity = float(bid[1])
            # Вес уменьшается с расстоянием от цены
            distance_pct = abs(current_price - price) / current_price
            weight = 1.0 / (1.0 + distance_pct * 10)  # Экспоненциальное затухание
            weighted_bid_volume += quantity * weight
        
        # Взвешиваем ask уровни
        for i, ask in enumerate(asks[:depth_levels]):
            price = float(ask[0])
            quantity = float(ask[1])
            distance_pct = abs(price - current_price) / current_price
            weight = 1.0 / (1.0 + distance_pct * 10)
            weighted_ask_volume += quantity * weight
        
        total_volume = weighted_bid_volume + weighted_ask_volume
        
        if total_volume == 0:
            return 0.0
        
        imbalance = (weighted_bid_volume - weighted_ask_volume) / total_volume
        
        return imbalance
    
    @staticmethod
    async def fetch_and_calculate_depth(client, symbol: str, 
                                        limit: int = 20,
                                        use_weighted: bool = False) -> Dict[str, float]:
        """
        Получить orderbook из API и рассчитать метрики
        
        Args:
            client: BinanceClient instance
            symbol: Trading symbol (e.g., 'BTCUSDT')
            limit: Depth limit (5, 10, 20, 50, 100, 500, 1000)
            use_weighted: Использовать взвешенный расчёт
        
        Returns:
            Dict с метриками: {
                'depth_imbalance': float,
                'bid_volume': float,
                'ask_volume': float,
                'spread_pct': float
            }
        """
        try:
            # Получаем orderbook
            orderbook = await client.get_orderbook(symbol=symbol, limit=limit)
            
            if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
                logger.debug(f"No orderbook data for {symbol}")
                return {
                    'depth_imbalance': 0.0,
                    'bid_volume': 0.0,
                    'ask_volume': 0.0,
                    'spread_pct': 0.0,
                    'data_valid': False  # Флаг что данные - fallback
                }
            
            bids = orderbook['bids']
            asks = orderbook['asks']
            
            if not bids or not asks:
                return {
                    'depth_imbalance': 0.0,
                    'bid_volume': 0.0,
                    'ask_volume': 0.0,
                    'spread_pct': 0.0,
                    'data_valid': False  # Флаг что данные - fallback
                }
            
            # Рассчитываем imbalance
            if use_weighted and bids and asks:
                best_bid = float(bids[0][0])
                best_ask = float(asks[0][0])
                mid_price = (best_bid + best_ask) / 2
                
                depth_imbalance = OrderbookAnalyzer.calculate_weighted_depth_imbalance(
                    bids, asks, mid_price, depth_levels=min(10, limit)
                )
            else:
                depth_imbalance = OrderbookAnalyzer.calculate_depth_imbalance(
                    bids, asks, depth_levels=min(10, limit)
                )
            
            # Дополнительные метрики
            bid_volume = sum(float(bid[1]) for bid in bids[:10])
            ask_volume = sum(float(ask[1]) for ask in asks[:10])
            
            # Spread в процентах
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            spread_pct = ((best_ask - best_bid) / best_bid) * 100 if best_bid > 0 else 0
            
            logger.debug(f"{symbol} Depth: Imbalance={depth_imbalance:.3f}, "
                        f"Bid Vol={bid_volume:.0f}, Ask Vol={ask_volume:.0f}, "
                        f"Spread={spread_pct:.4f}%")
            
            return {
                'depth_imbalance': depth_imbalance,
                'bid_volume': bid_volume,
                'ask_volume': ask_volume,
                'spread_pct': spread_pct,
                'data_valid': True  # Флаг что данные реальные
            }
            
        except Exception as e:
            logger.error(f"Error fetching orderbook for {symbol}: {e}")
            return {
                'depth_imbalance': 0.0,
                'bid_volume': 0.0,
                'ask_volume': 0.0,
                'spread_pct': 0.0,
                'data_valid': False  # Флаг что данные - fallback
            }


def calculate_depth_imbalance(bids: List[List], asks: List[List], depth_levels: int = 10) -> float:
    """Standalone функция для совместимости"""
    return OrderbookAnalyzer.calculate_depth_imbalance(bids, asks, depth_levels)
