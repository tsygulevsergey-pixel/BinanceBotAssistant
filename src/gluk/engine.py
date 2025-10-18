"""
Gluk Engine (Legacy Action Price System)

КРИТИЧНО: Это копия Action Price логики 15-16 октября 2025!
- Использует индексы -2/-1 (confirm = НЕЗАКРЫТАЯ свеча с промежуточными данными!)
- НЕ требует отрезания последней свечи в main.py
- EMA200 пересчитывается с промежуточными данными текущей свечи
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
import hashlib
from datetime import datetime
import pytz
import logging

logger = logging.getLogger('gluk')


class GlukEngine:
    """
    LEGACY Action Price Engine - точная копия старой логики
    
    Win Rate был 82.98% с этой версией!
    """
    
    def __init__(self, config: dict, binance_client=None):
        """
        Args:
            config: Конфигурация из config.yaml['gluk']
            binance_client: BinanceClient для получения актуальной цены
        """
        self.config = config
        self.enabled = config.get('enabled', True)
        self.client = binance_client
        self.timeframe = config.get('timeframe', '15m')
        
        # TP/SL параметры (как в старой AP)
        self.tp1_rr = config.get('tp1_rr', 1.0)
        self.tp2_rr = config.get('tp2_rr', 2.0)
        
        logger.info(f"🟡 Gluk Engine initialized (LEGACY logic with -2/-1 indices, TF={self.timeframe})")
    
    async def analyze(self, symbol: str, df: pd.DataFrame) -> Optional[Dict]:
        """
        LEGACY анализ - использует промежуточные данные незакрытой свечи
        
        КРИТИЧНО:
        - df должен включать текущую НЕЗАКРЫТУЮ свечу!
        - Индексы -2/-1 (confirm = незакрытая с промежуточными OHLC!)
        - EMA200 пересчитывается с промежуточным close
        
        Args:
            symbol: Символ
            df: Данные 15m С НЕЗАКРЫТОЙ ПОСЛЕДНЕЙ СВЕЧОЙ!
            
        Returns:
            Сигнал или None
        """
        if not self.enabled:
            return None
        
        if len(df) < 250:
            logger.debug(f"[Gluk] {symbol} - Insufficient data: {len(df)} bars")
            return None
        
        try:
            # Валидация - убрать timezone для совместимости с unclosed candle
            df = df.copy()
            
            # Конвертировать open_time в timezone-naive если нужно
            if pd.api.types.is_datetime64tz_dtype(df['open_time']):
                df['open_time'] = df['open_time'].dt.tz_localize(None)
            
            df = df.sort_values('open_time', ascending=True).reset_index(drop=True)
            
            # Расчет EMA200 (используя ВСЕ данные, включая незакрытую свечу!)
            df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
            
            # Проверка последней свечи (должна быть незакрытой!)
            last_candle_time = df['open_time'].iloc[-1]
            now = datetime.now(pytz.UTC)
            
            # last_candle_time теперь timezone-naive, сделать его aware для сравнения
            if not hasattr(last_candle_time, 'tzinfo') or last_candle_time.tzinfo is None:
                last_candle_time = pytz.UTC.localize(last_candle_time)
            
            time_diff = (now - last_candle_time).total_seconds()
            
            # Если последняя свеча старше 16 минут - она закрыта (не то что нужно!)
            if time_diff > 960:  # 16 минут
                logger.warning(f"[Gluk] {symbol} - Last candle is CLOSED ({time_diff/60:.1f}min old), need UNCLOSED!")
                return None
            
            # КРИТИЧНО: Индексы -2 (инициатор) и -1 (подтверждение = НЕЗАКРЫТАЯ!)
            if len(df) < 2:
                return None
            
            init_idx = -2
            conf_idx = -1
            
            # Данные инициатора (закрытая свеча)
            init_open = df['open'].iloc[init_idx]
            init_close = df['close'].iloc[init_idx]
            ema200_init = df['ema200'].iloc[init_idx]
            
            # Данные подтверждения (НЕЗАКРЫТАЯ свеча с промежуточными данными!)
            conf_close = df['close'].iloc[conf_idx]  # ПРОМЕЖУТОЧНЫЙ close!
            conf_low = df['low'].iloc[conf_idx]      # ПРОМЕЖУТОЧНЫЙ low!
            conf_high = df['high'].iloc[conf_idx]    # ПРОМЕЖУТОЧНЫЙ high!
            ema200_conf = df['ema200'].iloc[conf_idx]  # EMA200 с промежуточным close!
            
            logger.info(
                f"[Gluk] {symbol} | "
                f"Init[-2]: O:{init_open:.5f} C:{init_close:.5f} EMA:{ema200_init:.5f} | "
                f"Confirm[-1 UNCLOSED]: H:{conf_high:.5f} L:{conf_low:.5f} C:{conf_close:.5f} EMA:{ema200_conf:.5f}"
            )
            
            # Определение паттерна LONG
            long_initiator = (init_close > ema200_init and init_open < ema200_init)
            long_confirm = (conf_close > ema200_conf and conf_low > ema200_conf)
            
            # Определение паттерна SHORT
            short_initiator = (init_close < ema200_init and init_open > ema200_init)
            short_confirm = (conf_close < ema200_conf and conf_high < ema200_conf)
            
            direction = None
            if long_initiator and long_confirm:
                direction = 'long'
            elif short_initiator and short_confirm:
                direction = 'short'
            
            if not direction:
                return None
            
            # Расчет SL/TP (упрощенная версия)
            entry_price = await self._get_entry_price(symbol)
            if not entry_price:
                return None
            
            if direction == 'long':
                sl = ema200_conf * 0.998  # SL ниже EMA200
                risk = entry_price - sl
                tp1 = entry_price + risk * self.tp1_rr
                tp2 = entry_price + risk * self.tp2_rr
            else:  # short
                sl = ema200_conf * 1.002  # SL выше EMA200
                risk = sl - entry_price
                tp1 = entry_price - risk * self.tp1_rr
                tp2 = entry_price - risk * self.tp2_rr
            
            # Генерация уникального хеша
            signal_id = hashlib.md5(
                f"{symbol}_{direction}_{df['open_time'].iloc[conf_idx]}_{entry_price}".encode()
            ).hexdigest()
            
            logger.info(
                f"[Gluk] 🟡 SIGNAL: {symbol} {direction.upper()} | "
                f"Entry: {entry_price:.5f} | SL: {sl:.5f} | TP1: {tp1:.5f} | TP2: {tp2:.5f}"
            )
            
            return {
                'context_hash': signal_id,
                'symbol': symbol,
                'direction': direction,
                'pattern_type': 'gluk_body_cross',
                'timeframe': self.timeframe,
                'entry_price': float(entry_price),
                'stop_loss': float(sl),
                'take_profit_1': float(tp1),
                'take_profit_2': float(tp2),
                'confidence_score': 5.0,  # Фиксированный score
                'zone_id': 'gluk_ema200',
                'zone_low': float(sl),
                'zone_high': float(entry_price),
                'confluence_flags': {'legacy': True},
                'meta_data': {
                    'mode': 'LEGACY',
                    'unclosed_candle': True,
                    'confirm_close': float(conf_close),
                    'confirm_ema200': float(ema200_conf)
                }
            }
            
        except Exception as e:
            logger.error(f"[Gluk] Error analyzing {symbol}: {e}", exc_info=True)
            return None
    
    async def _get_entry_price(self, symbol: str) -> Optional[float]:
        """Получить актуальную цену входа через REST API"""
        try:
            if self.client:
                price_data = await self.client.get_mark_price(symbol)
                return float(price_data['markPrice'])
            return None
        except Exception as e:
            logger.error(f"[Gluk] Error getting entry price for {symbol}: {e}")
            return None
