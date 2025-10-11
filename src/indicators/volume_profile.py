import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional


class VolumeProfile:
    @staticmethod
    def calculate_profile(df: pd.DataFrame, num_bins: int = 50, 
                         bin_size_percent: float = 0.1) -> Dict:
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
        
        volume_by_price = np.zeros(num_bins)
        
        for idx, row in df.iterrows():
            candle_range = row['high'] - row['low']
            if candle_range == 0:
                bin_idx = np.digitize(row['close'], bins) - 1
                bin_idx = min(max(bin_idx, 0), num_bins - 1)
                volume_by_price[bin_idx] += row['volume']
            else:
                for i in range(num_bins):
                    bin_low = bins[i]
                    bin_high = bins[i + 1]
                    
                    overlap_low = max(bin_low, row['low'])
                    overlap_high = min(bin_high, row['high'])
                    
                    if overlap_high > overlap_low:
                        overlap_ratio = (overlap_high - overlap_low) / candle_range
                        volume_by_price[i] += row['volume'] * overlap_ratio
        
        bin_centers = (bins[:-1] + bins[1:]) / 2
        
        vpoc_idx = np.argmax(volume_by_price)
        vpoc = bin_centers[vpoc_idx]
        
        total_volume = volume_by_price.sum()
        value_area_volume = total_volume * 0.70
        
        # Строим Value Area НЕПРЕРЫВНО вокруг VPOC
        # Начинаем с VPOC bin и расширяемся в обе стороны
        value_area_indices = {vpoc_idx}
        cumulative_volume = volume_by_price[vpoc_idx]
        
        left_idx = vpoc_idx - 1
        right_idx = vpoc_idx + 1
        
        # Расширяемся, добавляя bin с большим объемом (левый или правый)
        while cumulative_volume < value_area_volume:
            left_vol = volume_by_price[left_idx] if left_idx >= 0 else 0
            right_vol = volume_by_price[right_idx] if right_idx < num_bins else 0
            
            # Если оба края закончились, прерываем
            if left_vol == 0 and right_vol == 0:
                break
            
            # Добавляем bin с большим объемом
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
        return val <= price <= vah
    
    @staticmethod
    def calculate_poc_distance(price: float, vpoc: float, atr: float = None) -> float:
        distance = abs(price - vpoc)
        if atr and atr > 0:
            return distance / atr
        return distance


# Standalone функция для совместимости
def calculate_volume_profile(df: pd.DataFrame, num_bins: int = 50) -> Dict:
    """Calculate volume profile with VAH, VAL, VPOC"""
    return VolumeProfile.calculate_profile(df, num_bins=num_bins)
