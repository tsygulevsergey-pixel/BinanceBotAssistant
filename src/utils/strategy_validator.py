"""
Strategy Validation Tool - проверка корректности работы стратегий
"""
import pandas as pd
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class StrategyValidator:
    """Валидатор для проверки корректности работы стратегий"""
    
    def __init__(self, strategy_manager, data_loader):
        self.strategy_manager = strategy_manager
        self.data_loader = data_loader
        
    def validate_all_strategies(self, symbol: str = 'BTCUSDT') -> Dict:
        """
        Проверить все стратегии на тестовых данных
        
        Returns:
            Dict с результатами проверки
        """
        results = {
            'symbol': symbol,
            'strategies_tested': 0,
            'strategies_passed': 0,
            'strategies_failed': 0,
            'details': []
        }
        
        # Загрузить данные для всех таймфреймов
        timeframe_data = {}
        for tf in ['15m', '1h', '4h']:
            df = self.data_loader.get_candles(symbol, tf, limit=200)
            if df is not None and not df.empty:
                timeframe_data[tf] = df
        
        if not timeframe_data:
            logger.error(f"No data available for {symbol}")
            return results
        
        # Mock индикаторы для тестирования
        mock_indicators = {
            'cvd': 0.0,
            'oi_delta': 0.0,
            'depth_imbalance': 0.0,
            'btc_bias': 'neutral',
            'h4_swing_high': None,
            'h4_swing_low': None
        }
        
        # Тестировать каждую стратегию
        for strategy in self.strategy_manager.strategies:
            results['strategies_tested'] += 1
            
            validation_result = self._validate_strategy(
                strategy, 
                symbol, 
                timeframe_data,
                mock_indicators
            )
            
            results['details'].append(validation_result)
            
            if validation_result['status'] == 'PASS':
                results['strategies_passed'] += 1
            else:
                results['strategies_failed'] += 1
        
        return results
    
    def _validate_strategy(self, strategy, symbol: str, 
                          timeframe_data: Dict, indicators: Dict) -> Dict:
        """Проверить одну стратегию"""
        
        result = {
            'strategy': strategy.name,
            'timeframe': strategy.timeframe,
            'status': 'PASS',
            'issues': [],
            'warnings': []
        }
        
        # 1. Проверка доступности данных
        tf = strategy.timeframe
        df = timeframe_data.get(tf)
        
        if df is None:
            result['status'] = 'FAIL'
            result['issues'].append(f"No data for timeframe {tf}")
            return result
        
        if len(df) < 50:
            result['status'] = 'FAIL'
            result['issues'].append(f"Insufficient data: {len(df)} bars (need 50+)")
            return result
        
        result['data_bars'] = len(df)
        
        # 2. Проверка OHLCV данных
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            result['status'] = 'FAIL'
            result['issues'].append(f"Missing columns: {missing_cols}")
            return result
        
        # 3. Проверка на NaN значения
        nan_cols = df[required_cols].isna().sum()
        if nan_cols.any():
            result['warnings'].append(f"NaN values found: {nan_cols[nan_cols > 0].to_dict()}")
        
        # 4. Проверка логики цен (high >= low, close между high/low)
        invalid_bars = (df['high'] < df['low']).sum()
        if invalid_bars > 0:
            result['status'] = 'FAIL'
            result['issues'].append(f"Invalid bars: {invalid_bars} (high < low)")
        
        close_out_of_range = ((df['close'] > df['high']) | (df['close'] < df['low'])).sum()
        if close_out_of_range > 0:
            result['status'] = 'FAIL'
            result['issues'].append(f"Close out of range: {close_out_of_range} bars")
        
        # 5. Тест генерации сигнала для разных режимов
        test_regimes = ['TREND', 'RANGE', 'SQUEEZE']
        test_biases = ['Bullish', 'Bearish', 'Neutral']
        
        signals_generated = []
        errors = []
        
        for regime in test_regimes:
            for bias in test_biases:
                try:
                    signal = strategy.check_signal(symbol, df, regime, bias, indicators)
                    if signal:
                        signals_generated.append({
                            'regime': regime,
                            'bias': bias,
                            'direction': signal.direction,
                            'entry': signal.entry_price,
                            'sl': signal.stop_loss,
                            'tp1': signal.take_profit_1
                        })
                        
                        # Проверка корректности уровней
                        if signal.direction == 'LONG':
                            if signal.stop_loss >= signal.entry_price:
                                result['issues'].append(f"Invalid SL for LONG: SL={signal.stop_loss} >= Entry={signal.entry_price}")
                            if signal.take_profit_1 <= signal.entry_price:
                                result['issues'].append(f"Invalid TP for LONG: TP={signal.take_profit_1} <= Entry={signal.entry_price}")
                        else:  # SHORT
                            if signal.stop_loss <= signal.entry_price:
                                result['issues'].append(f"Invalid SL for SHORT: SL={signal.stop_loss} <= Entry={signal.entry_price}")
                            if signal.take_profit_1 >= signal.entry_price:
                                result['issues'].append(f"Invalid TP for SHORT: TP={signal.take_profit_1} >= Entry={signal.entry_price}")
                        
                except Exception as e:
                    errors.append(f"{regime}/{bias}: {str(e)}")
        
        if errors:
            result['status'] = 'FAIL'
            result['issues'].extend(errors)
        
        result['signals_tested'] = len(test_regimes) * len(test_biases)
        result['signals_generated'] = len(signals_generated)
        result['sample_signals'] = signals_generated[:2] if signals_generated else []
        
        if result['issues']:
            result['status'] = 'FAIL'
        elif not signals_generated:
            result['warnings'].append("No signals generated in any test scenario")
        
        return result
    
    def print_validation_report(self, results: Dict):
        """Красивый вывод результатов валидации"""
        
        print("\n" + "="*80)
        print(f"STRATEGY VALIDATION REPORT - {results['symbol']}")
        print("="*80)
        print(f"Total Strategies: {results['strategies_tested']}")
        print(f"✅ PASSED: {results['strategies_passed']}")
        print(f"❌ FAILED: {results['strategies_failed']}")
        print("="*80)
        
        for detail in results['details']:
            status_icon = "✅" if detail['status'] == 'PASS' else "❌"
            print(f"\n{status_icon} {detail['strategy']} ({detail['timeframe']})")
            print(f"   Status: {detail['status']}")
            
            if 'data_bars' in detail:
                print(f"   Data: {detail['data_bars']} bars")
            
            if 'signals_tested' in detail:
                print(f"   Tested: {detail['signals_tested']} scenarios")
                print(f"   Generated: {detail['signals_generated']} signals")
            
            if detail.get('issues'):
                print("   ⚠️ ISSUES:")
                for issue in detail['issues']:
                    print(f"      - {issue}")
            
            if detail.get('warnings'):
                print("   ⚡ WARNINGS:")
                for warning in detail['warnings']:
                    print(f"      - {warning}")
            
            if detail.get('sample_signals'):
                print("   📊 Sample Signals:")
                for sig in detail['sample_signals']:
                    print(f"      - {sig['regime']}/{sig['bias']}: {sig['direction']} @ {sig['entry']:.2f}")
        
        print("\n" + "="*80)
