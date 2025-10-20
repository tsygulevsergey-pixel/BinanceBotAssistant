import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional


class VolumeProfile:
    @staticmethod
    def calculate_profile(df: pd.DataFrame, num_bins: int = 50, 
                         bin_size_percent: float = 0.1) -> Dict:
        """
        ВЕКТОРИЗОВАННАЯ версия Volume Profile (50-100x faster!)
        
        Args:
            df: DataFrame with OHLCV data
            num_bins: Number of price bins (default: 50)
            bin_size_percent: Alternative bin sizing (% of close price)
        
        Returns:
            Dict with POC, VAH, VAL, and volume profile data
        """
        if df.empty:
            return {}
        
        price_range = df['high'].max() - df['low'].min()
        if bin_size_percent:
            bin_size = df['close'].iloc[-1] * (bin_size_percent / 100)
            num_bins = int(price_range / bin_size) if bin_size > 0 else 50
        
        num_bins = max(10, min(num_bins, 200))
        
        min_price = df['low'].min()
        max_price = df['high'].max()
        bins = np.linspace(min_price, max_price, num_bins + 1)
        
        # ВЕКТОРИЗАЦИЯ: Конвертируем DataFrame в numpy arrays
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        volumes = df['volume'].values
        
        # Создаем массив для объемов по ценам
        volume_by_price = np.zeros(num_bins)
        
        # Расчет candle_range для всех свечей сразу (векторизованно)
        candle_ranges = highs - lows
        
        # ОПТИМИЗАЦИЯ 1: Обработка свечей с нулевым диапазоном (векторизованно)
        zero_range_mask = candle_ranges == 0
        if zero_range_mask.any():
            # Для свечей с zero range используем close price
            zero_range_closes = closes[zero_range_mask]
            zero_range_volumes = volumes[zero_range_mask]
            
            # Находим bins для этих свечей
            bin_indices = np.digitize(zero_range_closes, bins) - 1
            bin_indices = np.clip(bin_indices, 0, num_bins - 1)
            
            # Добавляем объемы в соответствующие bins
            for bin_idx, vol in zip(bin_indices, zero_range_volumes):
                volume_by_price[bin_idx] += vol
        
        # ОПТИМИЗАЦИЯ 2: Обработка обычных свечей (векторизованно с broadcasting)
        normal_mask = ~zero_range_mask
        if normal_mask.any():
            normal_highs = highs[normal_mask]
            normal_lows = lows[normal_mask]
            normal_volumes = volumes[normal_mask]
            normal_ranges = candle_ranges[normal_mask]
            
            # Создаем массивы bin границ (broadcasting)
            bin_lows = bins[:-1].reshape(-1, 1)  # (num_bins, 1)
            bin_highs = bins[1:].reshape(-1, 1)  # (num_bins, 1)
            
            # Broadcasting: вычисляем overlap для всех bins и всех свечей одновременно
            # Shapes: bin_lows/highs (num_bins, 1), candle lows/highs (1, n_candles)
            overlap_lows = np.maximum(bin_lows, normal_lows.reshape(1, -1))  # (num_bins, n_candles)
            overlap_highs = np.minimum(bin_highs, normal_highs.reshape(1, -1))  # (num_bins, n_candles)
            
            # Рассчитываем overlap (где overlap_high > overlap_low)
            overlaps = np.maximum(0, overlap_highs - overlap_lows)  # (num_bins, n_candles)
            
            # Рассчитываем ratios для каждого bin и свечи
            overlap_ratios = overlaps / normal_ranges.reshape(1, -1)  # (num_bins, n_candles)
            
            # Умножаем на объемы и суммируем по свечам для каждого bin
            volume_contributions = overlap_ratios * normal_volumes.reshape(1, -1)  # (num_bins, n_candles)
            volume_by_price += volume_contributions.sum(axis=1)  # Sum across candles
        
        # Расчет bin centers
        bin_centers = (bins[:-1] + bins[1:]) / 2
        
        # Находим VPOC (Point of Control)
        vpoc_idx = np.argmax(volume_by_price)
        vpoc = bin_centers[vpoc_idx]
        
        total_volume = volume_by_price.sum()
        value_area_volume = total_volume * 0.70
        
        # Строим Value Area НЕПРЕРЫВНО вокруг VPOC
        value_area_indices = {vpoc_idx}
        cumulative_volume = volume_by_price[vpoc_idx]
        
        left_idx = vpoc_idx - 1
        right_idx = vpoc_idx + 1
        
        # Расширяемся, добавляя bin с большим объемом
        while cumulative_volume < value_area_volume:
            left_vol = volume_by_price[left_idx] if left_idx >= 0 else 0
            right_vol = volume_by_price[right_idx] if right_idx < num_bins else 0
            
            if left_vol == 0 and right_vol == 0:
                break
            
            if left_vol >= right_vol and left_idx >= 0:
                value_area_indices.add(left_idx)
                cumulative_volume += left_vol
                left_idx -= 1
            elif right_idx < num_bins:
                value_area_indices.add(right_idx)
                cumulative_volume += right_vol
                right_idx += 1
        
        # VAH/VAL = края непрерывной зоны
        vah = bin_centers[max(value_area_indices)]
        val = bin_centers[min(value_area_indices)]
        
        return {
            'poc': vpoc,
            'vpoc': vpoc,
            'vah': vah,
            'val': val,
            'profile': {
                'prices': bin_centers.tolist(),
                'volumes': volume_by_price.tolist()
            },
            'total_volume': total_volume
        }
    
    @staticmethod
    def is_price_in_value_area(price: float, vah: float, val: float) -> bool:
        """Check if price is within Value Area (VAL to VAH)"""
        return val <= price <= vah
    
    @staticmethod
    def calculate_poc_distance(price: float, vpoc: float, atr: float = None) -> float:
        """Calculate distance from price to POC (optionally in ATR units)"""
        distance = abs(price - vpoc)
        if atr and atr > 0:
            return distance / atr
        return distance


# Standalone функция для совместимости
def calculate_volume_profile(df: pd.DataFrame, num_bins: int = 50) -> Dict:
    """Calculate volume profile with VAH, VAL, VPOC"""
    return VolumeProfile.calculate_profile(df, num_bins=num_bins)
