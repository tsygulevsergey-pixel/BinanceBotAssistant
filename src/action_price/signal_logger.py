"""
JSONL Signal Logger для детального логирования Action Price сигналов
"""
import json
import os
from datetime import datetime
from typing import Dict, Optional, Any
import pytz


class ActionPriceSignalLogger:
    """JSONL логгер для детального логирования каждого сигнала"""
    
    def __init__(self):
        """Инициализация логгера с созданием нового файла"""
        # Создать директорию logs если не существует
        os.makedirs('logs', exist_ok=True)
        
        # Создать новый файл с timestamp запуска
        timestamp = datetime.now(tz=pytz.UTC).strftime('%Y%m%d_%H%M%S')
        self.log_filename = f"logs/action_price_signals_{timestamp}.jsonl"
        
        # Создать файл и записать header comment
        with open(self.log_filename, 'w', encoding='utf-8') as f:
            header = {
                "_comment": "Action Price Signal Log",
                "_format": "JSONL - one JSON object per line",
                "_timezone": "UTC (ISO-8601 ...Z format)",
                "_started_at": datetime.now(tz=pytz.UTC).isoformat()
            }
            f.write(json.dumps(header, ensure_ascii=False) + '\n')
        
        print(f"📊 JSONL Signal Logger initialized: {self.log_filename}")
    
    def log_signal(self, signal_data: Dict[str, Any]) -> None:
        """
        Записать сигнал в JSONL файл
        
        Args:
            signal_data: Словарь с данными сигнала (все поля из спецификации)
        """
        # Ensure timestamp is ISO-8601 UTC
        if 'timestamp_open' in signal_data and isinstance(signal_data['timestamp_open'], datetime):
            signal_data['timestamp_open'] = signal_data['timestamp_open'].isoformat()
        
        if 'timestamp_exit' in signal_data and isinstance(signal_data['timestamp_exit'], datetime):
            signal_data['timestamp_exit'] = signal_data['timestamp_exit'].isoformat()
        
        # Write as single line JSON
        with open(self.log_filename, 'a', encoding='utf-8') as f:
            f.write(json.dumps(signal_data, ensure_ascii=False) + '\n')
    
    def create_signal_entry(
        self,
        # Метаданные
        signal_id: str,
        timestamp_open: datetime,
        symbol: str,
        timeframe: str,
        direction: str,
        pattern: str,
        mode: str,
        score_total: float,
        score_components: Dict[str, float],
        
        # Цена/уровни
        entry_price: float,
        sl_price: float,
        tp1_price: float,
        tp2_price: Optional[float],
        risk_r: float,
        spread_at_entry: Optional[float] = None,
        slippage_entry: Optional[float] = None,
        
        # EMA/ATR на инициаторе (бар [2])
        initiator_ema5: float,
        initiator_ema9: float,
        initiator_ema13: float,
        initiator_ema21: float,
        initiator_ema200: float,
        initiator_atr: float,
        initiator_atr_upper_band: float,
        initiator_atr_lower_band: float,
        
        # EMA/ATR на подтверждении (бар [1])
        confirm_ema5: float,
        confirm_ema9: float,
        confirm_ema13: float,
        confirm_ema21: float,
        confirm_ema200: float,
        confirm_atr: float,
        confirm_atr_upper_band: float,
        confirm_atr_lower_band: float,
        slope_ema200_norm: float,
        ema_fan_state: str,
        ema_fan_spread_norm: float,
        
        # Свечные метрики - инициатор
        initiator_open: float,
        initiator_high: float,
        initiator_low: float,
        initiator_close: float,
        initiator_body_size_atr: float,
        initiator_upper_wick_atr: float,
        initiator_lower_wick_atr: float,
        initiator_body_cross_type: str,
        
        # Свечные метрики - подтверждение
        confirm_open: float,
        confirm_high: float,
        confirm_low: float,
        confirm_close: float,
        confirm_body_size_atr: float,
        confirm_upper_wick_atr: float,
        confirm_lower_wick_atr: float,
        confirm_depth_atr: float,
        confirm_color: str,
        touch_ema200: bool,
        close_vs_ema_fan: str,
        gap_to_outer_band_atr: float,
        
        # Контекст/структура
        touches_ema200_last5: int,
        trend_tag: str,
        retest_tag: bool,
        break_and_base_tag: bool,
        swing_high_price: Optional[float],
        swing_high_index: Optional[int],
        swing_low_price: Optional[float],
        swing_low_index: Optional[int],
        
        # Результат (будет обновлено при выходе)
        exit_reason: Optional[str] = None,
        timestamp_exit: Optional[datetime] = None,
        exit_price: Optional[float] = None,
        time_to_tp1_bars: Optional[int] = None,
        time_to_tp1_mins: Optional[float] = None,
        time_to_exit_bars: Optional[int] = None,
        time_to_exit_mins: Optional[float] = None,
        mfe_r: Optional[float] = None,
        mae_r: Optional[float] = None,
        bars_in_trade: Optional[int] = None,
        
        # Опциональные
        initiator_volume: Optional[float] = None,
        confirm_volume: Optional[float] = None,
        atr_regime: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Создать полную запись сигнала согласно спецификации
        
        Returns:
            Словарь с данными сигнала готовый для логирования
        """
        signal_entry = {
            # Метаданные
            "signal_id": signal_id,
            "timestamp_open": timestamp_open.isoformat() if isinstance(timestamp_open, datetime) else timestamp_open,
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": direction,
            "pattern": pattern,
            "mode": mode,
            "score_total": score_total,
            "score_components": score_components,
            
            # Цена/уровни
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "risk_r": risk_r,
            "spread_at_entry": spread_at_entry,
            "slippage_entry": slippage_entry,
            
            # EMA/ATR на инициаторе
            "initiator_ema5": initiator_ema5,
            "initiator_ema9": initiator_ema9,
            "initiator_ema13": initiator_ema13,
            "initiator_ema21": initiator_ema21,
            "initiator_ema200": initiator_ema200,
            "initiator_atr": initiator_atr,
            "initiator_atr_upper_band": initiator_atr_upper_band,
            "initiator_atr_lower_band": initiator_atr_lower_band,
            
            # EMA/ATR на подтверждении
            "confirm_ema5": confirm_ema5,
            "confirm_ema9": confirm_ema9,
            "confirm_ema13": confirm_ema13,
            "confirm_ema21": confirm_ema21,
            "confirm_ema200": confirm_ema200,
            "confirm_atr": confirm_atr,
            "confirm_atr_upper_band": confirm_atr_upper_band,
            "confirm_atr_lower_band": confirm_atr_lower_band,
            "slope_ema200_norm": slope_ema200_norm,
            "ema_fan_state": ema_fan_state,
            "ema_fan_spread_norm": ema_fan_spread_norm,
            
            # Свечные метрики - инициатор
            "initiator_open": initiator_open,
            "initiator_high": initiator_high,
            "initiator_low": initiator_low,
            "initiator_close": initiator_close,
            "initiator_body_size_atr": initiator_body_size_atr,
            "initiator_upper_wick_atr": initiator_upper_wick_atr,
            "initiator_lower_wick_atr": initiator_lower_wick_atr,
            "initiator_body_cross_type": initiator_body_cross_type,
            
            # Свечные метрики - подтверждение
            "confirm_open": confirm_open,
            "confirm_high": confirm_high,
            "confirm_low": confirm_low,
            "confirm_close": confirm_close,
            "confirm_body_size_atr": confirm_body_size_atr,
            "confirm_upper_wick_atr": confirm_upper_wick_atr,
            "confirm_lower_wick_atr": confirm_lower_wick_atr,
            "confirm_depth_atr": confirm_depth_atr,
            "confirm_color": confirm_color,
            "touch_ema200": touch_ema200,
            "close_vs_ema_fan": close_vs_ema_fan,
            "gap_to_outer_band_atr": gap_to_outer_band_atr,
            
            # Контекст/структура
            "touches_ema200_last5": touches_ema200_last5,
            "trend_tag": trend_tag,
            "retest_tag": retest_tag,
            "break_and_base_tag": break_and_base_tag,
            "swing_high_price": swing_high_price,
            "swing_high_index": swing_high_index,
            "swing_low_price": swing_low_price,
            "swing_low_index": swing_low_index,
            
            # Результат
            "exit_reason": exit_reason,
            "timestamp_exit": timestamp_exit.isoformat() if isinstance(timestamp_exit, datetime) else timestamp_exit,
            "exit_price": exit_price,
            "time_to_tp1_bars": time_to_tp1_bars,
            "time_to_tp1_mins": time_to_tp1_mins,
            "time_to_exit_bars": time_to_exit_bars,
            "time_to_exit_mins": time_to_exit_mins,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "bars_in_trade": bars_in_trade,
            
            # Опциональные
            "initiator_volume": initiator_volume,
            "confirm_volume": confirm_volume,
            "atr_regime": atr_regime
        }
        
        return signal_entry
    
    def update_signal_exit(
        self,
        signal_id: str,
        exit_reason: str,
        timestamp_exit: datetime,
        exit_price: float,
        time_to_tp1_bars: Optional[int] = None,
        time_to_tp1_mins: Optional[float] = None,
        time_to_exit_bars: Optional[int] = None,
        time_to_exit_mins: Optional[float] = None,
        mfe_r: Optional[float] = None,
        mae_r: Optional[float] = None,
        bars_in_trade: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Создать запись обновления выхода из сделки
        
        Returns:
            Словарь с данными выхода
        """
        exit_data = {
            "_update_type": "exit",
            "signal_id": signal_id,
            "exit_reason": exit_reason,
            "timestamp_exit": timestamp_exit.isoformat() if isinstance(timestamp_exit, datetime) else timestamp_exit,
            "exit_price": exit_price,
            "time_to_tp1_bars": time_to_tp1_bars,
            "time_to_tp1_mins": time_to_tp1_mins,
            "time_to_exit_bars": time_to_exit_bars,
            "time_to_exit_mins": time_to_exit_mins,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "bars_in_trade": bars_in_trade
        }
        
        return exit_data
