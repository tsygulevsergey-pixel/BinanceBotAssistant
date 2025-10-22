"""
Cross-TF Arbitrator - Арбитраж между M15 и H1 сигналами

Применяет правила:
- Block M15 против H1 (встречные сигналы)
- Allow piggyback (M15 + H1 в одну сторону)
- Per-TF signal/position locks
- Front-run защита
"""

from typing import Dict, List, Tuple, Set


class CrossTFArbitrator:
    """
    Арбитратор для управления конфликтами между M15 и H1 сигналами
    
    Основные правила:
    1. M15 НЕ спорит с H1 (встречные блокируются)
    2. M15 + H1 одна сторона = piggyback (разрешено)
    3. Per-TF locks (раздельные для каждого TF)
    4. Front-run защита (слишком близко к HTF "стене")
    """
    
    def __init__(self, config: Dict):
        """
        Args:
            config: Cross-TF policy configuration
        """
        self.config = config
        
        # Policy settings
        self.block_m15_against_h1 = config.get('block_m15_against_h1', True)
        self.allow_same_direction_stack = config.get('allow_same_direction_stack', True)
        self.daily_cap_total = config.get('daily_cap_total', 0.03)
        
        # Active signals tracking (for live mode)
        self._active_m15_signals: Dict[str, Dict] = {}  # signal_id -> signal
        self._active_h1_signals: Dict[str, Dict] = {}
        
        # Position tracking (for live mode)
        self._m15_positions: Set[str] = set()  # Set of active position signal_ids
        self._h1_positions: Set[str] = set()
    
    def filter(self,
              signals_m15: List[Dict],
              signals_h1: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Apply cross-TF arbitration rules
        
        Args:
            signals_m15: M15 signals from engine
            signals_h1: H1 signals from engine
        
        Returns:
            (filtered_m15, filtered_h1) - signals that passed arbitration
        """
        filtered_m15 = []
        filtered_h1 = []
        
        # H1 signals have priority (no filtering)
        filtered_h1 = signals_h1.copy()
        
        # Register H1 signals and directions
        h1_directions = self._get_signal_directions(signals_h1)
        
        # Also check active H1 positions/signals
        active_h1_directions = self._get_active_directions('h1')
        h1_directions.update(active_h1_directions)
        
        # Filter M15 signals
        for m15_signal in signals_m15:
            m15_direction = m15_signal['direction']
            
            # [1] Check if M15 opposes H1
            if self.block_m15_against_h1:
                # Get opposite direction
                opposite_direction = 'SHORT' if m15_direction == 'LONG' else 'LONG'
                
                # If H1 has active signal in opposite direction, BLOCK M15
                if opposite_direction in h1_directions:
                    m15_signal['_blocked_reason'] = f'M15_{m15_direction}_blocked_by_H1_{opposite_direction}'
                    continue  # Skip this M15 signal
            
            # [2] Check if M15 aligns with H1 (piggyback)
            if self.allow_same_direction_stack and m15_direction in h1_directions:
                # Find corresponding H1 signal
                h1_signal = self._find_h1_signal_by_direction(
                    signals_h1, self._active_h1_signals, m15_direction
                )
                
                if h1_signal:
                    # Set piggyback flag
                    m15_signal['relations']['piggyback_on'] = h1_signal['signal_id']
                    m15_signal['risk']['stacking'] = 'piggyback'
                    m15_signal['reasons'].append('piggyback_h1')
                    m15_signal['confidence'] = min(100, m15_signal['confidence'] + 10)
            
            # [3] Front-run protection (already done in engines, but double-check)
            htf_distance = m15_signal['context'].get('distance_to_htf_edge_atr')
            if htf_distance is not None and htf_distance < 1.2:
                m15_signal['_blocked_reason'] = f'frontrun_htf_too_close_{htf_distance:.2f}atr'
                continue
            
            # Passed all filters
            filtered_m15.append(m15_signal)
        
        return filtered_m15, filtered_h1
    
    def _get_signal_directions(self, signals: List[Dict]) -> Set[str]:
        """
        Extract unique directions from signals
        
        Args:
            signals: List of signals
        
        Returns:
            Set of directions ('LONG', 'SHORT')
        """
        return {sig['direction'] for sig in signals}
    
    def _get_active_directions(self, tf: str) -> Set[str]:
        """
        Get directions of active signals/positions for a TF
        
        Args:
            tf: 'm15' or 'h1'
        
        Returns:
            Set of active directions
        """
        directions = set()
        
        if tf == 'm15':
            for signal in self._active_m15_signals.values():
                directions.add(signal['direction'])
        elif tf == 'h1':
            for signal in self._active_h1_signals.values():
                directions.add(signal['direction'])
        
        return directions
    
    def _find_h1_signal_by_direction(self,
                                     new_h1_signals: List[Dict],
                                     active_h1_signals: Dict[str, Dict],
                                     direction: str) -> Dict:
        """
        Find H1 signal matching direction
        
        Args:
            new_h1_signals: Newly generated H1 signals
            active_h1_signals: Active H1 signals (from previous ticks)
            direction: Direction to match
        
        Returns:
            H1 signal dict or None
        """
        # First check new signals
        for signal in new_h1_signals:
            if signal['direction'] == direction:
                return signal
        
        # Then check active signals
        for signal in active_h1_signals.values():
            if signal['direction'] == direction:
                return signal
        
        return None
    
    def register_signal(self, signal: Dict, tf: str):
        """
        Register signal as active (for position tracking in live mode)
        
        Args:
            signal: Signal dict
            tf: 'm15' or 'h1'
        """
        signal_id = signal['signal_id']
        
        if tf == 'm15':
            self._active_m15_signals[signal_id] = signal
        elif tf == 'h1':
            self._active_h1_signals[signal_id] = signal
    
    def unregister_signal(self, signal_id: str, tf: str):
        """
        Unregister signal (closed or cancelled)
        
        Args:
            signal_id: Signal ID
            tf: 'm15' or 'h1'
        """
        if tf == 'm15':
            self._active_m15_signals.pop(signal_id, None)
        elif tf == 'h1':
            self._active_h1_signals.pop(signal_id, None)
    
    def get_active_signals_count(self, tf: str = None) -> int:
        """
        Get count of active signals
        
        Args:
            tf: Specific TF or None for total
        
        Returns:
            Count of active signals
        """
        if tf == 'm15':
            return len(self._active_m15_signals)
        elif tf == 'h1':
            return len(self._active_h1_signals)
        else:
            return len(self._active_m15_signals) + len(self._active_h1_signals)
    
    def get_stats(self) -> Dict:
        """
        Get arbitration statistics
        
        Returns:
            Stats dict
        """
        return {
            'active_m15_count': len(self._active_m15_signals),
            'active_h1_count': len(self._active_h1_signals),
            'm15_directions': list(self._get_active_directions('m15')),
            'h1_directions': list(self._get_active_directions('h1')),
        }
