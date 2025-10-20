"""
V3 S/R JSONL Signal Logger

Writes detailed signal data to JSONL files for analysis and backtesting.
Each signal is logged as a single JSON object per line with complete context.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
import pytz


class V3SRSignalLogger:
    """JSONL logger for V3 S/R Flip-Retest and Sweep-Return signals"""
    
    def __init__(self, log_dir: str = 'logs'):
        """
        Initialize logger with new timestamped file
        
        Args:
            log_dir: Directory for log files
        """
        # Create directory if needed
        os.makedirs(log_dir, exist_ok=True)
        
        # Create new file with timestamp
        timestamp = datetime.now(tz=pytz.UTC).strftime('%Y%m%d_%H%M%S')
        self.log_filename = os.path.join(log_dir, f"v3_sr_signals_{timestamp}.jsonl")
        
        # Write header comment
        with open(self.log_filename, 'w', encoding='utf-8') as f:
            header = {
                "_comment": "V3 S/R Strategy Signal Log",
                "_format": "JSONL - one JSON object per line",
                "_timezone": "UTC (ISO-8601 ...Z format)",
                "_strategy": "Flip-Retest & Sweep-Return",
                "_started_at": datetime.now(tz=pytz.UTC).isoformat()
            }
            f.write(json.dumps(header, ensure_ascii=False) + '\n')
        
        print(f"📊 V3 S/R JSONL Logger initialized: {self.log_filename}")
    
    def log_signal(self, signal_data: Dict[str, Any]) -> None:
        """
        Write signal to JSONL file
        
        Args:
            signal_data: Dictionary with signal data
        """
        # Convert datetime objects to ISO-8601 strings
        for key in ['timestamp_open', 'timestamp_exit', 'valid_until', 'created_at', 
                    'tp1_hit_at', 'tp2_hit_at', 'moved_to_be_at', 'closed_at']:
            if key in signal_data and isinstance(signal_data[key], datetime):
                signal_data[key] = signal_data[key].isoformat()
        
        # Write as single line JSON
        with open(self.log_filename, 'a', encoding='utf-8') as f:
            f.write(json.dumps(signal_data, ensure_ascii=False) + '\n')
    
    def create_signal_entry(
        self,
        # Signal ID & Basic Info
        signal_id: str,
        symbol: str,
        setup_type: str,  # "FlipRetest" or "SweepReturn"
        direction: str,  # "LONG" or "SHORT"
        entry_tf: str,  # "15m" or "1h"
        timestamp_open: datetime,
        
        # Zone Context (primary zone)
        zone_id: str,
        zone_tf: str,
        zone_kind: str,  # "S" or "R"
        zone_low: float,
        zone_high: float,
        zone_mid: float,
        zone_strength: float,
        zone_class: str,  # "key", "strong", "normal", "weak"
        zone_state: str,  # "normal", "weakening", "flipped"
        
        # Nearest Zones (for context)
        nearest_support: Optional[Dict[str, Any]],
        nearest_resistance: Optional[Dict[str, Any]],
        
        # HTF Context
        htf_context: List[str],  # ["D:KeyR", "H4:StrongS", ...]
        
        # VWAP Bias
        vwap_bias: str,  # "BULL", "BEAR", "NEUTRAL"
        vwap_value: float,
        price_vs_vwap_atr: float,
        
        # Price Levels
        entry_price: float,
        entry_price_raw: float,
        stop_loss: float,
        stop_loss_raw: float,
        take_profit_1: float,
        tp1_raw: float,
        take_profit_2: float,
        tp2_raw: float,
        
        # Risk/Reward
        risk_r: float,
        tp1_r_multiple: float,
        tp2_r_multiple: float,
        
        # Quality & Confidence
        confidence: float,
        quality_tags: List[str],
        
        # Setup-specific params
        setup_params: Dict[str, Any],
        
        # Market Context
        market_regime: str,
        volatility_regime: str,
        atr_value: float,
        
        # Validity
        valid_until: datetime,
        
        # Exit data (will be updated later)
        exit_reason: Optional[str] = None,
        timestamp_exit: Optional[datetime] = None,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None,
        pnl_percent: Optional[float] = None,
        final_r_multiple: Optional[float] = None,
        
        # Performance metrics
        mfe_r: Optional[float] = None,
        mae_r: Optional[float] = None,
        tp1_hit: Optional[bool] = None,
        tp2_hit: Optional[bool] = None,
        bars_to_tp1: Optional[int] = None,
        bars_to_tp2: Optional[int] = None,
        bars_to_exit: Optional[int] = None,
        duration_minutes: Optional[int] = None,
        
        # Zone reaction
        zone_reaction_occurred: Optional[bool] = None,
        zone_reaction_atr: Optional[float] = None,
        
        # Additional metadata
        meta_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create signal entry dictionary
        
        Returns:
            Dictionary ready for JSONL logging
        """
        return {
            # ═══════════════════════════════════════════════════════════
            # SIGNAL IDENTIFICATION
            # ═══════════════════════════════════════════════════════════
            "signal_id": signal_id,
            "symbol": symbol,
            "setup_type": setup_type,
            "direction": direction,
            "entry_tf": entry_tf,
            "timestamp_open": timestamp_open.isoformat() if isinstance(timestamp_open, datetime) else timestamp_open,
            
            # ═══════════════════════════════════════════════════════════
            # ZONE CONTEXT
            # ═══════════════════════════════════════════════════════════
            "zone": {
                "zone_id": zone_id,
                "tf": zone_tf,
                "kind": zone_kind,
                "low": zone_low,
                "high": zone_high,
                "mid": zone_mid,
                "strength": zone_strength,
                "class": zone_class,
                "state": zone_state
            },
            
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            
            "htf_context": htf_context,
            
            # ═══════════════════════════════════════════════════════════
            # VWAP BIAS
            # ═══════════════════════════════════════════════════════════
            "vwap": {
                "bias": vwap_bias,
                "value": vwap_value,
                "distance_atr": price_vs_vwap_atr
            },
            
            # ═══════════════════════════════════════════════════════════
            # PRICE LEVELS
            # ═══════════════════════════════════════════════════════════
            "prices": {
                "entry": entry_price,
                "entry_raw": entry_price_raw,
                "sl": stop_loss,
                "sl_raw": stop_loss_raw,
                "tp1": take_profit_1,
                "tp1_raw": tp1_raw,
                "tp2": take_profit_2,
                "tp2_raw": tp2_raw
            },
            
            # ═══════════════════════════════════════════════════════════
            # RISK/REWARD
            # ═══════════════════════════════════════════════════════════
            "risk_reward": {
                "risk_r": risk_r,
                "tp1_r": tp1_r_multiple,
                "tp2_r": tp2_r_multiple
            },
            
            # ═══════════════════════════════════════════════════════════
            # QUALITY & CONFIDENCE
            # ═══════════════════════════════════════════════════════════
            "quality": {
                "confidence": confidence,
                "tags": quality_tags
            },
            
            # ═══════════════════════════════════════════════════════════
            # SETUP-SPECIFIC PARAMETERS
            # ═══════════════════════════════════════════════════════════
            "setup_params": setup_params,
            
            # ═══════════════════════════════════════════════════════════
            # MARKET CONTEXT
            # ═══════════════════════════════════════════════════════════
            "market": {
                "regime": market_regime,
                "volatility": volatility_regime,
                "atr": atr_value
            },
            
            # ═══════════════════════════════════════════════════════════
            # VALIDITY
            # ═══════════════════════════════════════════════════════════
            "valid_until": valid_until.isoformat() if isinstance(valid_until, datetime) else valid_until,
            
            # ═══════════════════════════════════════════════════════════
            # EXIT & PERFORMANCE (updated later)
            # ═══════════════════════════════════════════════════════════
            "exit": {
                "reason": exit_reason,
                "timestamp": timestamp_exit.isoformat() if isinstance(timestamp_exit, datetime) else timestamp_exit if timestamp_exit else None,
                "price": exit_price,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "final_r": final_r_multiple
            },
            
            "performance": {
                "mfe_r": mfe_r,
                "mae_r": mae_r,
                "tp1_hit": tp1_hit,
                "tp2_hit": tp2_hit,
                "bars_to_tp1": bars_to_tp1,
                "bars_to_tp2": bars_to_tp2,
                "bars_to_exit": bars_to_exit,
                "duration_minutes": duration_minutes
            },
            
            "zone_reaction": {
                "occurred": zone_reaction_occurred,
                "magnitude_atr": zone_reaction_atr
            },
            
            # ═══════════════════════════════════════════════════════════
            # METADATA
            # ═══════════════════════════════════════════════════════════
            "meta_data": meta_data or {}
        }
    
    def update_signal_exit(
        self,
        signal_id: str,
        exit_reason: str,
        timestamp_exit: datetime,
        exit_price: float,
        pnl: float,
        pnl_percent: float,
        final_r_multiple: float,
        mfe_r: float,
        mae_r: float,
        tp1_hit: bool,
        tp2_hit: bool,
        bars_to_exit: int,
        duration_minutes: int,
        zone_reaction_occurred: Optional[bool] = None,
        zone_reaction_atr: Optional[float] = None
    ) -> None:
        """
        Update signal with exit information
        
        This creates a new log entry with the exit data.
        
        Args:
            signal_id: Signal ID to update
            exit_reason: Reason for exit
            timestamp_exit: Exit timestamp
            exit_price: Exit price
            pnl: P&L in currency
            pnl_percent: P&L percentage
            final_r_multiple: Final R-multiple
            mfe_r: Max Favorable Excursion (R)
            mae_r: Max Adverse Excursion (R)
            tp1_hit: TP1 hit flag
            tp2_hit: TP2 hit flag
            bars_to_exit: Bars until exit
            duration_minutes: Trade duration in minutes
            zone_reaction_occurred: Whether zone reaction occurred
            zone_reaction_atr: Zone reaction magnitude in ATR
        """
        exit_update = {
            "_update_type": "EXIT",
            "signal_id": signal_id,
            "timestamp_exit": timestamp_exit.isoformat() if isinstance(timestamp_exit, datetime) else timestamp_exit,
            "exit_reason": exit_reason,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "final_r_multiple": final_r_multiple,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "bars_to_exit": bars_to_exit,
            "duration_minutes": duration_minutes,
            "zone_reaction_occurred": zone_reaction_occurred,
            "zone_reaction_atr": zone_reaction_atr
        }
        
        self.log_signal(exit_update)
