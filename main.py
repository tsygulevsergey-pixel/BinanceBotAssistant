import asyncio
import signal
import sys
from typing import List, Optional, Dict
from src.utils.logger import logger
from src.utils.strategy_logger import strategy_logger
from src.utils.config import config
from src.binance.client import BinanceClient
from src.binance.data_loader import DataLoader
from src.strategies.strategy_manager import StrategyManager
from src.scoring.signal_scorer import SignalScorer
from src.filters.btc_filter import BTCFilter
from src.detectors.market_regime import MarketRegimeDetector

# Импорт всех стратегий
from src.strategies.donchian_breakout import DonchianBreakoutStrategy
from src.strategies.squeeze_breakout import SqueezeBreakoutStrategy
from src.strategies.orb_strategy import ORBStrategy
from src.strategies.ma_vwap_pullback import MAVWAPPullbackStrategy
from src.strategies.break_retest import BreakRetestStrategy
from src.strategies.atr_momentum import ATRMomentumStrategy
from src.strategies.vwap_mean_reversion import VWAPMeanReversionStrategy
from src.strategies.range_fade import RangeFadeStrategy
from src.strategies.rsi_stoch_mr import RSIStochMRStrategy
from src.strategies.volume_profile import VolumeProfileStrategy
from src.strategies.liquidity_sweep import LiquiditySweepStrategy
from src.strategies.cvd_divergence import CVDDivergenceStrategy
from src.strategies.time_of_day import TimeOfDayStrategy
from src.strategies.order_flow import OrderFlowStrategy
from src.strategies.cash_and_carry import CashAndCarryStrategy
from src.strategies.market_making import MarketMakingStrategy
from src.telegram.bot import TelegramBot
from src.utils.symbol_load_coordinator import SymbolLoadCoordinator
from src.utils.signal_lock import SignalLockManager
from src.utils.signal_tracker import SignalPerformanceTracker
from src.utils.entry_manager import EntryManager
from src.utils.strategy_validator import StrategyValidator
from src.utils.timeframe_sync import TimeframeSync
from src.utils.indicator_validator import IndicatorValidator
from src.database.db import db
from src.database.models import Signal
from sqlalchemy import and_
from src.indicators.cache import IndicatorCache
from src.indicators.common import calculate_common_indicators
from src.indicators.swing_levels import calculate_swing_levels
from src.indicators.open_interest import OpenInterestCalculator
from src.indicators.orderbook import OrderbookAnalyzer
import hashlib
from datetime import datetime
import pytz


class TradingBot:
    def __init__(self):
        self.running = False
        self.client: Optional[BinanceClient] = None
        self.data_loader: Optional[DataLoader] = None
        self.symbols: List[str] = []
        self.ready_symbols: List[str] = []  # Symbols with loaded data, ready for analysis
        self.symbols_with_active_signals: set = set()  # Символы с активными сигналами (блокированы от анализа)
        self.coordinator: Optional[SymbolLoadCoordinator] = None
        self.performance_tracker: Optional[SignalPerformanceTracker] = None
        
        # Компоненты бота
        self.strategy_manager = StrategyManager(binance_client=None)  # Will be set after client init
        self.signal_scorer = SignalScorer(config)  # Config object supports dot notation
        self.btc_filter = BTCFilter(config)  # Config object supports dot notation
        self.regime_detector = MarketRegimeDetector()
        self.telegram_bot = TelegramBot(binance_client=None)  # Will be set after client init
        self.signal_lock_manager = SignalLockManager()
        self.entry_manager = EntryManager()  # Управление MARKET/LIMIT входами
        self.indicator_cache = IndicatorCache()  # Кеш для индикаторов
        
        self._register_strategies()
    
    async def start(self):
        logger.info("=" * 60)
        logger.info("Trading Bot Starting...")
        logger.info("=" * 60)
        
        # Проверка режима работы
        signals_only = config.get('binance.signals_only_mode', False)
        if signals_only:
            logger.warning("🔔 SIGNALS-ONLY MODE: Bot will generate signals without real trading")
            logger.warning("🔔 No API keys required in this mode")
        
        self.running = True
        
        try:
            # Создаём клиента и не закрываем сессию автоматически
            self.client = BinanceClient()
            await self.client.__aenter__()  # Открываем сессию
            
            # Загрузить информацию о символах (precision) для правильного форматирования цен
            await self.client.load_symbols_info()
            
            self.data_loader = DataLoader(self.client, self.telegram_bot)
            
            # Передаем binance_client в StrategyManager и TelegramBot
            self.strategy_manager.binance_client = self.client
            self.telegram_bot.binance_client = self.client
            
            await self._initialize()
            await self._run_main_loop()
        
        except KeyboardInterrupt:
            logger.info("Shutdown signal received")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            await self.stop()
    
    async def _fetch_symbols_by_volume(self) -> List[str]:
        """Получить список символов по минимальному объему"""
        if not config.get('universe.fetch_all_pairs', True):
            symbols = config.get('universe.initial_symbols', ['BTCUSDT', 'ETHUSDT'])
            logger.info(f"Using configured symbols: {symbols}")
            return symbols
        
        logger.info("Fetching USDT-M futures pairs by volume...")
        all_pairs = await self.client.get_futures_pairs()
        
        min_volume = config.get('universe.min_volume_24h', 10000000)
        ticker_data = await self.client.get_24h_ticker()
        
        if isinstance(ticker_data, dict):
            ticker_data = [ticker_data]
        
        volume_map = {t['symbol']: float(t['quoteVolume']) for t in ticker_data}
        
        symbols = [s for s in all_pairs if volume_map.get(s, 0) >= min_volume]
        logger.info(f"Filtered to {len(symbols)} pairs with volume >= ${min_volume:,.0f}")
        return symbols
    
    async def _initialize(self):
        logger.info("Initializing bot...")
        
        if not self.client:
            raise Exception("Client not initialized")
        
        rate_limit_status = self.client.get_rate_limit_status()
        logger.info(f"Rate limit status: {rate_limit_status['current_weight']}/{rate_limit_status['limit']}")
        
        # Загрузить активные сигналы из БД и заблокировать символы
        self._load_active_signals_on_startup()
        
        # Получаем начальный список символов
        self.symbols = await self._fetch_symbols_by_volume()
        
        logger.info(f"Starting parallel data loading for {len(self.symbols)} symbols...")
        
        self.coordinator = SymbolLoadCoordinator(total_symbols=len(self.symbols), queue_max_size=50)
        
        loader_task = asyncio.create_task(self._symbol_loader_task())
        analyzer_task = asyncio.create_task(self._symbol_analyzer_task())
        update_symbols_task = asyncio.create_task(self._update_symbols_task())
        
        logger.info("Background tasks started (loader + analyzer + symbol updater running in parallel)")
        logger.info("Bot will start analyzing symbols as soon as their data is loaded")
        
        # Запуск системы трекинга производительности
        check_interval = config.get('performance.tracking_interval_seconds', 60)
        self.performance_tracker = SignalPerformanceTracker(
            binance_client=self.client,
            db=db,
            lock_manager=self.signal_lock_manager,
            check_interval=check_interval,
            on_signal_closed_callback=self._unblock_symbol
        )
        asyncio.create_task(self.performance_tracker.start())
        logger.info(f"📊 Signal Performance Tracker started (check interval: {check_interval}s)")
        
        # Создание валидатора стратегий
        strategy_validator = StrategyValidator(
            strategy_manager=self.strategy_manager,
            data_loader=self.data_loader
        )
        
        # Запуск Telegram бота
        await self.telegram_bot.start()
        
        # Связываем компоненты с Telegram ботом для команд
        self.telegram_bot.set_performance_tracker(self.performance_tracker)
        self.telegram_bot.set_validator(strategy_validator)
        
        # Отправка приветственного сообщения
        signals_only = config.get('binance.signals_only_mode', False)
        mode = "Signals-Only" if signals_only else "Live Trading"
        strategies_count = len(self.strategy_manager.strategies)
        await self.telegram_bot.send_startup_message(
            pairs_count=len(self.symbols),
            strategies_count=strategies_count,
            mode=mode
        )
        
        logger.info("Initialization complete")
    
    def _register_strategies(self):
        """Регистрация всех стратегий согласно мануалу"""
        strategies = [
            DonchianBreakoutStrategy(),          # Стратегия #1
            SqueezeBreakoutStrategy(),           # Стратегия #2
            ORBStrategy(),                       # Стратегия #3
            MAVWAPPullbackStrategy(),            # Стратегия #4
            BreakRetestStrategy(),               # Стратегия #5
            ATRMomentumStrategy(),               # Стратегия #6
            VWAPMeanReversionStrategy(),         # Стратегия #7
            RangeFadeStrategy(),                 # Стратегия #8
            VolumeProfileStrategy(),             # Стратегия #9
            RSIStochMRStrategy(),                # Стратегия #10
            LiquiditySweepStrategy(),            # Стратегия #11
            OrderFlowStrategy(),                 # Стратегия #12
            CVDDivergenceStrategy(),             # Стратегия #13
            TimeOfDayStrategy(),                 # Стратегия #14
            CashAndCarryStrategy(),              # Стратегия #19 (требует funding данных)
            MarketMakingStrategy(),              # Стратегия #26 (требует HFT orderbook)
        ]
        
        self.strategy_manager.register_all(strategies)
        logger.info(f"Registered {len(strategies)} strategies")
        logger.info(f"Active strategies: {self.strategy_manager.get_enabled_count()}")
    
    async def _run_main_loop(self):
        logger.info("Starting main loop...")
        logger.info(f"All {len(self.strategy_manager.strategies)} strategies will run simultaneously")
        
        # Показать расписание обновлений
        now = datetime.now(pytz.UTC)
        logger.info(f"📅 Current time: {now.strftime('%H:%M:%S UTC')}")
        logger.info(f"📅 Next 15m update: {TimeframeSync.get_next_update_time('15m', now).strftime('%H:%M UTC')}")
        logger.info(f"📅 Next 1h update: {TimeframeSync.get_next_update_time('1h', now).strftime('%H:%M UTC')}")
        logger.info(f"📅 Next 4h update: {TimeframeSync.get_next_update_time('4h', now).strftime('%H:%M UTC')}")
        
        iteration = 0
        check_interval = config.get('scanning.check_interval_seconds', 60)
        
        while self.running:
            iteration += 1
            
            # Каждые check_interval секунд проверяем сигналы
            if iteration % check_interval == 0 and len(self.ready_symbols) > 0:
                await self._check_signals()
            
            # Статус каждую минуту или каждые 10 сек если загрузка идёт
            status_interval = 10 if self.coordinator and not self.coordinator.is_loading_complete() else 60
            if iteration % status_interval == 0 and self.client:
                rate_status = self.client.get_rate_limit_status()
                total_signals = self.strategy_manager.get_total_signals_count()
                
                if self.coordinator:
                    coord_status = self.coordinator.get_status_summary()
                    logger.info(
                        f"📊 {coord_status} | "
                        f"{self.strategy_manager.get_enabled_count()} strategies | "
                        f"{total_signals} signals | "
                        f"Rate: {rate_status['percent_used']:.1f}%"
                    )
                else:
                    logger.info(
                        f"Status: {len(self.symbols)} symbols | "
                        f"{self.strategy_manager.get_enabled_count()} strategies active | "
                        f"{total_signals} total signals | "
                        f"Rate limit: {rate_status['percent_used']:.1f}%"
                    )
            
            await asyncio.sleep(1)
    
    async def _check_signals(self):
        """Проверить сигналы для всех готовых символов"""
        if not self.data_loader:
            return
        
        symbols_to_check = self.ready_symbols.copy()
        if not symbols_to_check:
            logger.debug("No symbols ready for analysis yet...")
            return
        
        logger.debug(f"Checking signals for {len(symbols_to_check)} ready symbols...")
        
        # Обновить BTC данные только если свеча закрылась
        now = datetime.now(pytz.UTC)
        if TimeframeSync.should_update_timeframe('1h'):
            try:
                await self.data_loader.update_missing_candles('BTCUSDT', '1h')
                logger.info(f"✅ Updated BTCUSDT 1h data (candle closed at {now.strftime('%H:%M UTC')})")
            except Exception as e:
                logger.debug(f"Could not update BTCUSDT: {e}")
        
        btc_data = self.data_loader.get_candles('BTCUSDT', '1h', limit=100)
        
        # Проверяем все готовые символы
        for symbol in symbols_to_check:
            # Пропускаем символы с активными сигналами
            if symbol in self.symbols_with_active_signals:
                logger.debug(f"⏭️  {symbol} skipped - has active signal")
                continue
            
            try:
                await self._check_symbol_signals(symbol, btc_data)
            except Exception as e:
                logger.error(f"Error checking {symbol}: {e}")
            
            await asyncio.sleep(0.05)  # Небольшая пауза между символами
    
    async def _check_symbol_signals(self, symbol: str, btc_data):
        """Проверить сигналы для одного символа"""
        if not self.data_loader:
            return
        
        # Обновить актуальные свечи ТОЛЬКО если свеча закрылась
        for tf in ['15m', '1h', '4h']:
            if TimeframeSync.should_update_timeframe(tf):
                try:
                    await self.data_loader.update_missing_candles(symbol, tf)
                except Exception as e:
                    logger.debug(f"Could not update {symbol} {tf}: {e}")
        
        # Загрузить данные для всех таймфреймов
        # Лимиты рассчитаны на основе максимальных требований стратегий:
        # - 15m: RSI/Stoch MR требует 90 дней × 24 × 4 = 8,640 баров
        # - 1h: Donchian требует ~87 дней × 24 = 2,100 баров
        # - 4h: 60 дней × 6 = 360 баров
        tf_limits = {
            '15m': 8640,  # 90 дней для RSI/Stoch MR
            '1h': 2100,   # ~87 дней для Donchian
            '4h': 360     # 60 дней
        }
        
        timeframe_data = {}
        for tf in ['15m', '1h', '4h']:
            limit = tf_limits.get(tf, 200)
            df = self.data_loader.get_candles(symbol, tf, limit=limit)
            if df is not None and len(df) > 0:
                timeframe_data[tf] = df
        
        # Проверить pending LIMIT orders для этого символа
        if '15m' in timeframe_data:
            executed_limits = self.entry_manager.check_pending_limits(symbol, timeframe_data['15m'])
            for limit_signal in executed_limits:
                strategy_logger.info(
                    f"✅ LIMIT FILLED: {limit_signal.symbol} {limit_signal.direction} @ "
                    f"{limit_signal.entry_price:.4f} (target was {limit_signal.target_entry_price:.4f})"
                )
                
                # Обновить entry_price в БД (PENDING → ACTIVE)
                self._update_limit_entry_in_db(limit_signal)
                
                # Отправить уведомление об исполнении
                await self.telegram_bot.send_signal({
                    'strategy_name': limit_signal.strategy_name,
                    'symbol': limit_signal.symbol,
                    'direction': limit_signal.direction.upper(),
                    'entry_price': limit_signal.entry_price,  # Фактическая цена
                    'stop_loss': limit_signal.stop_loss,
                    'tp1': limit_signal.take_profit_1,
                    'tp2': limit_signal.take_profit_2,
                    'score': limit_signal.final_score,
                    'regime': limit_signal.regime,
                    'entry_type': 'LIMIT FILLED'
                })
        
        if not timeframe_data:
            logger.debug(f"❌ {symbol}: No timeframe data available")
            return
        
        # Определить режим рынка и bias
        h4_data = timeframe_data.get('4h')
        if h4_data is None or len(h4_data) < 200:
            logger.debug(f"❌ {symbol}: Insufficient H4 data ({len(h4_data) if h4_data is not None else 0} bars, требуется 200)")
            return
        
        regime_data = self.regime_detector.detect_regime(h4_data)
        regime = regime_data['regime'].value  # Convert ENUM to string
        bias = self.regime_detector.get_h4_bias(h4_data)
        
        logger.debug(f"🔍 Analyzing {symbol} | Regime: {regime} | Bias: {bias}")
        strategy_logger.info(f"\n{'='*80}")
        strategy_logger.info(f"🔍 АНАЛИЗ: {symbol} | Режим: {regime} | Bias: {bias}")
        
        # Рассчитать H4 swings для confluence проверки
        # Используем fractal patterns (локальные экстремумы) вместо простого max/min
        # lookback=5 означает 5 баров с каждой стороны для подтверждения swing
        h4_swing_high, h4_swing_low = calculate_swing_levels(h4_data, lookback=5) if h4_data is not None and len(h4_data) >= 20 else (None, None)
        
        # Рассчитать общие индикаторы (с кешированием)
        # Проверяем кеш для каждого таймфрейма
        cached_indicators = {}
        for tf, df in timeframe_data.items():
            last_bar_time = df.index[-1]
            cached = self.indicator_cache.get(symbol, tf, last_bar_time)
            
            if cached is None:
                # Кеша нет или устарел - рассчитываем заново
                common_indicators = calculate_common_indicators(df, tf)
                self.indicator_cache.set(symbol, tf, last_bar_time, common_indicators)
                cached_indicators[tf] = common_indicators
            else:
                # Используем закешированные индикаторы
                cached_indicators[tf] = cached
        
        # Получить реальные данные Open Interest из API
        oi_metrics = await OpenInterestCalculator.fetch_and_calculate_oi(
            client=self.client,
            symbol=symbol,
            period='5m',
            limit=30,
            lookback=5
        )
        
        # Получить реальные данные Orderbook Depth из API
        depth_metrics = await OrderbookAnalyzer.fetch_and_calculate_depth(
            client=self.client,
            symbol=symbol,
            limit=20,
            use_weighted=True  # Используем взвешенный расчёт
        )
        
        # Indicators для стратегий (объединяем кешированные + дополнительные)
        # NOTE: CVD теперь берется из indicators[self.timeframe]['cvd'] в каждой стратегии
        indicators = {
            **cached_indicators,  # Все закешированные индикаторы по таймфреймам (включая CVD)
            'doi_pct': oi_metrics['doi_pct'],  # Реальные данные Open Interest Delta %
            'oi_delta': oi_metrics['oi_delta'],  # Абсолютное изменение OI
            'oi_data_valid': oi_metrics.get('data_valid', False),  # Флаг валидности OI данных
            'depth_imbalance': depth_metrics['depth_imbalance'],  # Реальный дисбаланс orderbook
            'bid_volume': depth_metrics['bid_volume'],  # Bid ликвидность
            'ask_volume': depth_metrics['ask_volume'],  # Ask ликвидность
            'spread_pct': depth_metrics['spread_pct'],  # Спред в %
            'depth_data_valid': depth_metrics.get('data_valid', False),  # Флаг валидности depth данных
            'late_trend': regime_data.get('late_trend', False),
            'h4_adx': regime_data.get('details', {}).get('adx', 0),  # H4 ADX для ORB стратегии
            'funding_extreme': False,  # TODO: Рассчитать из API Funding Rate
            'btc_bias': self.btc_filter.get_btc_bias(btc_data) if btc_data is not None else 'Neutral',
            'h4_swing_high': h4_swing_high,
            'h4_swing_low': h4_swing_low
        }
        
        # Валидация индикаторов (только для первого символа или периодически)
        if symbol == self.ready_symbols[0] if self.ready_symbols else True:
            validation = IndicatorValidator.validate_indicators(indicators, symbol=symbol)
            IndicatorValidator.log_validation_results(validation, symbol=symbol)
        
        # Проверка MR блокировки по BTC
        btc_block_mr = False
        if btc_data is not None:
            btc_block_mr = self.btc_filter.should_block_mean_reversion(btc_data)
            if btc_block_mr:
                logger.debug(f"{symbol}: MR strategies blocked due to BTC volatility")
                strategy_logger.warning(f"⚠️  BTC импульс обнаружен - Mean Reversion стратегии ЗАБЛОКИРОВАНЫ")
        
        # Получить сигналы от всех стратегий
        strategy_logger.info(f"📋 Проверка {len(self.strategy_manager.strategies)} стратегий...")
        
        signals = await self.strategy_manager.check_all_signals(
            symbol=symbol,
            timeframe_data=timeframe_data,
            regime=regime,
            bias=bias,
            indicators=indicators
        )
        
        if signals:
            logger.debug(f"📊 {symbol}: {len(signals)} signals from strategies: {[s.strategy_name for s in signals]}")
            strategy_logger.info(f"✅ Получено {len(signals)} сигналов: {', '.join([s.strategy_name for s in signals])}")
        else:
            logger.debug(f"⚪ {symbol}: No signals from any strategy")
            strategy_logger.info(f"⚪ Ни одна стратегия не дала сигнал")
        
        # ШАГ 1: Рассчитать final_score для ВСЕХ сигналов
        scored_signals = []
        for signal in signals:
            strategy_logger.info(f"\n📊 СКОРИНГ: {signal.strategy_name} | {signal.direction}")
            
            final_score = self.signal_scorer.score_signal(
                signal=signal,
                market_data={'df': timeframe_data.get(signal.timeframe)},
                indicators=indicators,
                btc_data=btc_data
            )
            
            # Детальная информация о скоринге
            score_breakdown = (
                f"  • Base Score: {signal.base_score:.1f}\n"
                f"  • Volume Ratio: {signal.volume_ratio:.2f}x\n"
                f"  • CVD Direction: {signal.cvd_direction}\n"
                f"  • Late Trend: {'Да' if signal.late_trend else 'Нет'}\n"
                f"  • BTC Against: {'Да' if signal.btc_against else 'Нет'}\n"
                f"  • ИТОГОВЫЙ SCORE: {final_score:.1f}"
            )
            strategy_logger.info(score_breakdown)
            
            # Сохраняем сигнал с его score
            scored_signals.append((signal, final_score))
        
        # ШАГ 2: Сортировка по final_score (от большего к меньшему)
        # Это гарантирует, что лучший сигнал обработается первым
        scored_signals.sort(key=lambda x: x[1], reverse=True)
        
        if scored_signals:
            strategy_logger.info(f"\n🎯 ПРИОРИТИЗАЦИЯ: Сигналы отсортированы по score:")
            for idx, (sig, score) in enumerate(scored_signals, 1):
                strategy_logger.info(f"  {idx}. {sig.strategy_name} {sig.direction} - Score: {score:.1f}")
        
        # ШАГ 3: Обработка сигналов в порядке приоритета (highest score first)
        for signal, final_score in scored_signals:
            # Проверить порог входа
            if self.signal_scorer.should_enter(final_score):
                logger.debug(f"✅ {signal.strategy_name} | {symbol} {signal.direction} | Score: {final_score:.1f} PASSED threshold")
                strategy_logger.info(f"\n✅ ПРОШЕЛ ПОРОГ (≥2.0) - ВАЛИДНЫЙ СИГНАЛ!")
                
                # Проверить блокировку (политика "1 сигнал на направление на символ")
                lock_acquired = self.signal_lock_manager.acquire_lock(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    strategy_name=signal.strategy_name
                )
                
                if not lock_acquired:
                    logger.warning(
                        f"⏭️  Signal skipped (locked): {signal.strategy_name} | "
                        f"{signal.symbol} {signal.direction}"
                    )
                    strategy_logger.warning(f"⏭️  ПРОПУЩЕН: {signal.direction} уже заблокирован другим сигналом")
                    continue
                
                logger.info(
                    f"✅ VALID SIGNAL: {signal.strategy_name} | "
                    f"{signal.symbol} {signal.direction} @ {signal.entry_price:.4f} | "
                    f"Score: {final_score:.1f} | SL: {signal.stop_loss:.4f} | "
                    f"TP1: {signal.take_profit_1:.4f} | TP2: {signal.take_profit_2:.4f} | "
                    f"Entry Type: {signal.entry_type}"
                )
                
                # Обработать гибридный вход через EntryManager
                action, processed_signal = self.entry_manager.process_signal(signal)
                
                if action == "EXECUTE":
                    # MARKET entry → немедленное исполнение
                    # Отправить сигнал в Telegram
                    telegram_msg_id = await self.telegram_bot.send_signal({
                        'strategy_name': signal.strategy_name,
                        'symbol': signal.symbol,
                        'direction': signal.direction.upper(),
                        'entry_price': signal.entry_price,
                        'stop_loss': signal.stop_loss,
                        'tp1': signal.take_profit_1,
                        'tp2': signal.take_profit_2,
                        'score': final_score,
                        'regime': regime,
                        'entry_type': 'MARKET'
                    })
                    
                    # Сохранить сигнал в БД
                    self._save_signal_to_db(
                        signal=signal,
                        final_score=final_score,
                        regime=regime,
                        telegram_msg_id=telegram_msg_id
                    )
                    
                    # Заблокировать символ от дальнейшего анализа
                    self._block_symbol(signal.symbol)
                
                elif action == "PENDING":
                    # LIMIT entry → отложенный ордер
                    strategy_logger.info(
                        f"⏳ LIMIT order pending: {signal.symbol} {signal.direction} | "
                        f"Target: {signal.target_entry_price:.4f}, Timeout: {signal.entry_timeout} bars"
                    )
                    
                    # Отправить уведомление о LIMIT ордере
                    telegram_msg_id = await self.telegram_bot.send_signal({
                        'strategy_name': signal.strategy_name,
                        'symbol': signal.symbol,
                        'direction': signal.direction.upper(),
                        'entry_price': signal.target_entry_price,  # Целевая цена
                        'stop_loss': signal.stop_loss,
                        'tp1': signal.take_profit_1,
                        'tp2': signal.take_profit_2,
                        'score': final_score,
                        'regime': regime,
                        'entry_type': 'LIMIT (pending)',
                        'current_price': signal.entry_price
                    })
                    
                    # Сохранить как pending в БД
                    self._save_signal_to_db(
                        signal=signal,
                        final_score=final_score,
                        regime=regime,
                        telegram_msg_id=telegram_msg_id,
                        status='PENDING'
                    )
                    
                    # Заблокировать символ от дальнейшего анализа
                    self._block_symbol(signal.symbol)
                
                else:
                    # SKIP - уже есть активный LIMIT ордер
                    strategy_logger.debug(f"⏭️  Signal skipped - duplicate LIMIT order")
            else:
                logger.debug(
                    f"❌ {signal.strategy_name} | {symbol} {signal.direction} | "
                    f"Score: {final_score:.1f} < threshold 2.0 | "
                    f"Base: {signal.base_score:.1f}, Vol: {signal.volume_ratio:.1f}x, "
                    f"CVD: {signal.cvd_direction}, Late: {signal.late_trend}, BTC: {signal.btc_against}"
                )
                strategy_logger.warning(f"❌ НЕ ПРОШЕЛ ПОРОГ: Score {final_score:.1f} < 2.0")
                continue  # Пропустить сигналы с score < threshold
    
    async def _symbol_loader_task(self):
        """Background task to load symbol data and add to ready queue"""
        if not self.coordinator or not self.data_loader:
            return
        
        logger.info("Symbol loader task started")
        max_retries = 3
        retry_delays = [5, 15, 30]
        
        for idx, symbol in enumerate(self.symbols, 1):
            if self.coordinator.is_shutdown_requested():
                logger.info("Loader task shutting down...")
                break
            
            try:
                self.coordinator.increment_loading_count()
                
                # Всегда вызываем load_warm_up_data - она умная и сама решит что делать
                # (догрузить gap или загрузить все данные)
                logger.info(f"[{idx}/{len(self.symbols)}] Checking {symbol}... ({(idx/len(self.symbols))*100:.1f}%)")
                
                success = False
                for attempt in range(max_retries):
                    try:
                        success = await self.data_loader.load_warm_up_data(symbol, silent=False)
                        if success:
                            break
                        
                        if attempt < max_retries - 1:
                            delay = retry_delays[attempt]
                            logger.warning(f"Retry {attempt + 1}/{max_retries} for {symbol} in {delay}s...")
                            await asyncio.sleep(delay)
                    except Exception as retry_error:
                        if attempt < max_retries - 1:
                            delay = retry_delays[attempt]
                            logger.warning(f"Retry {attempt + 1}/{max_retries} for {symbol} after error: {retry_error}")
                            await asyncio.sleep(delay)
                        else:
                            raise
                
                if success:
                    await self.coordinator.add_ready_symbol(symbol)
                    logger.info(f"✓ {symbol} loaded and ready for analysis")
                else:
                    self.coordinator.mark_symbol_failed(symbol, f"Loading failed after {max_retries} attempts")
                
            except Exception as e:
                logger.error(f"Error loading {symbol} after {max_retries} retries: {e}")
                self.coordinator.mark_symbol_failed(symbol, str(e))
            finally:
                self.coordinator.decrement_loading_count()
            
            await asyncio.sleep(0.1)
        
        logger.info(f"Loader task complete. Loaded {self.coordinator.get_progress().loaded_count}/{len(self.symbols)} symbols")
    
    async def _symbol_analyzer_task(self):
        """Background task to consume ready symbols and add them to analysis list"""
        if not self.coordinator:
            return
        
        logger.info("Symbol analyzer task started")
        
        while not self.coordinator.is_shutdown_requested() or not self.coordinator.ready_queue.empty():
            symbol = await self.coordinator.get_next_symbol()
            
            if symbol:
                self.ready_symbols.append(symbol)
                logger.info(f"✅ {symbol} ready for analysis ({len(self.ready_symbols)} symbols analyzing)")
                self.coordinator.mark_symbol_analyzed(symbol)
            elif self.coordinator.is_loading_complete():
                logger.info("All symbols processed, analyzer task complete")
                break
            
            await asyncio.sleep(0.5)
        
        logger.info(f"Analyzer task stopped. {len(self.ready_symbols)} symbols ready for analysis")
    
    async def _update_symbols_task(self):
        """Background task to update symbol list every hour based on volume"""
        if not config.get('universe.fetch_all_pairs', True):
            logger.info("Symbol auto-update disabled (using configured symbols)")
            return
        
        update_interval = config.get('universe.update_interval_hours', 1) * 3600  # Convert to seconds
        logger.info(f"📊 Symbol auto-update started (interval: {update_interval/3600:.0f}h)")
        
        while self.running:
            await asyncio.sleep(update_interval)
            
            if not self.running:
                break
            
            try:
                logger.info("🔄 Updating symbol list by volume...")
                new_symbols = await self._fetch_symbols_by_volume()
                
                # Найти новые символы (которых нет в текущем списке)
                current_set = set(self.symbols)
                new_set = set(new_symbols)
                
                added_symbols = new_set - current_set
                removed_symbols = current_set - new_set
                
                if added_symbols:
                    logger.info(f"➕ Adding {len(added_symbols)} new symbols: {', '.join(list(added_symbols)[:5])}{'...' if len(added_symbols) > 5 else ''}")
                    
                    # Добавляем новые символы и загружаем данные
                    for symbol in added_symbols:
                        self.symbols.append(symbol)
                        
                        # Загружаем данные напрямую (loader task уже завершен)
                        if self.data_loader:
                            try:
                                logger.info(f"Loading data for new symbol: {symbol}")
                                success = await self.data_loader.load_warm_up_data(symbol, silent=False)
                                if success:
                                    # Добавляем в ready_symbols для анализа
                                    if symbol not in self.ready_symbols:
                                        self.ready_symbols.append(symbol)
                                        logger.info(f"✅ {symbol} loaded and ready for analysis ({len(self.ready_symbols)} symbols)")
                            except Exception as e:
                                logger.error(f"Error loading new symbol {symbol}: {e}")
                
                if removed_symbols:
                    logger.info(f"➖ Removing {len(removed_symbols)} symbols (low volume): {', '.join(list(removed_symbols)[:5])}{'...' if len(removed_symbols) > 5 else ''}")
                    # Удаляем из обоих списков
                    self.symbols = [s for s in self.symbols if s not in removed_symbols]
                    self.ready_symbols = [s for s in self.ready_symbols if s not in removed_symbols]
                
                if not added_symbols and not removed_symbols:
                    logger.info(f"✓ Symbol list unchanged ({len(self.symbols)} pairs)")
                    
            except Exception as e:
                logger.error(f"Error updating symbols: {e}", exc_info=True)
        
        logger.info("Symbol auto-update task stopped")
    
    def _save_signal_to_db(self, signal, final_score: float, regime: str, telegram_msg_id: Optional[int] = None, status: str = 'ACTIVE'):
        """Сохранить сигнал в базу данных"""
        session = db.get_session()
        try:
            # Генерировать уникальный context_hash для сигнала
            context_str = f"{signal.symbol}_{signal.strategy_name}_{signal.direction}_{signal.entry_price}_{regime}"
            context_hash = hashlib.sha256(context_str.encode()).hexdigest()[:64]
            
            # Генерировать стабильный strategy_id из имени (CRC32 always positive)
            import zlib
            strategy_id = zlib.crc32(signal.strategy_name.encode()) & 0x7FFFFFFF  # Ensure positive 31-bit int
            
            # Создать запись сигнала
            db_signal = Signal(
                context_hash=context_hash,
                symbol=signal.symbol,
                strategy_id=strategy_id,
                strategy_name=signal.strategy_name,
                direction=signal.direction,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit_1=signal.take_profit_1,
                take_profit_2=signal.take_profit_2 if signal.take_profit_2 else signal.take_profit_1,
                score=final_score,
                market_regime=regime,
                timeframe=signal.timeframe,
                created_at=datetime.now(pytz.UTC),
                status=status,  # ACTIVE или PENDING
                telegram_message_id=telegram_msg_id,
                meta_data={
                    'base_score': signal.base_score,
                    'volume_ratio': signal.volume_ratio,
                    'cvd_direction': signal.cvd_direction,
                    'oi_delta_percent': signal.oi_delta_percent,
                    'imbalance_detected': signal.imbalance_detected,
                    'late_trend': signal.late_trend,
                    'btc_against': signal.btc_against,
                    'bias': signal.bias
                }
            )
            
            session.add(db_signal)
            session.commit()
            logger.info(f"💾 Signal saved to DB: {signal.symbol} {signal.direction} (ID: {db_signal.id}, Strategy ID: {strategy_id})")
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save signal to DB: {e}", exc_info=True)
        finally:
            session.close()
    
    def _update_limit_entry_in_db(self, signal):
        """Обновить entry_price в БД после исполнения LIMIT ордера"""
        session = db.get_session()
        try:
            db_signal = session.query(Signal).filter(
                and_(
                    Signal.symbol == signal.symbol,
                    Signal.direction == signal.direction,
                    Signal.strategy_name == signal.strategy_name,
                    Signal.status == 'PENDING'
                )
            ).first()
            
            if db_signal:
                db_signal.entry_price = signal.entry_price
                db_signal.status = 'ACTIVE'
                session.commit()
                logger.info(
                    f"💾 Updated LIMIT entry in DB: {signal.symbol} {signal.direction} "
                    f"entry_price={signal.entry_price:.4f}"
                )
            else:
                logger.warning(
                    f"⚠️  Could not find PENDING signal in DB for {signal.symbol} {signal.direction}"
                )
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update LIMIT entry in DB: {e}", exc_info=True)
        finally:
            session.close()
    
    def _load_active_signals_on_startup(self):
        """Загрузить активные сигналы из БД при старте и заблокировать символы"""
        session = db.get_session()
        try:
            # Получить все активные и pending сигналы
            active_signals = session.query(Signal).filter(
                Signal.status.in_(['ACTIVE', 'PENDING'])
            ).all()
            
            if active_signals:
                # Добавить уникальные символы в блокировку
                for signal in active_signals:
                    self.symbols_with_active_signals.add(str(signal.symbol))
                
                logger.info(
                    f"🔒 Loaded {len(active_signals)} active signals, "
                    f"blocked {len(self.symbols_with_active_signals)} symbols from analysis"
                )
                logger.debug(f"Blocked symbols: {', '.join(sorted(self.symbols_with_active_signals))}")
            else:
                logger.info("✅ No active signals in DB - all symbols available for analysis")
                
        except Exception as e:
            logger.error(f"Error loading active signals on startup: {e}", exc_info=True)
        finally:
            session.close()
    
    def _block_symbol(self, symbol: str):
        """Заблокировать символ от анализа (есть активный сигнал)"""
        self.symbols_with_active_signals.add(symbol)
        logger.info(f"🔒 {symbol} blocked from analysis (active signal)")
    
    def _unblock_symbol(self, symbol: str):
        """Разблокировать символ для анализа (сигнал закрыт)"""
        try:
            if symbol in self.symbols_with_active_signals:
                self.symbols_with_active_signals.remove(symbol)
                logger.info(f"🔓 {symbol} unblocked for analysis (signal closed)")
        except Exception as e:
            logger.error(f"Error unblocking symbol {symbol}: {e}", exc_info=True)
    
    async def stop(self):
        import traceback
        logger.info("Stopping bot...")
        logger.debug(f"Stop called from: {''.join(traceback.format_stack()[-3:-1])}")
        self.running = False
        
        # Ждём завершения координатора если он ещё работает
        if self.coordinator and not self.coordinator.is_loading_complete():
            logger.info("Waiting for coordinator to finish loading...")
            await asyncio.sleep(2)  # Даём время на graceful shutdown
        
        if self.coordinator:
            self.coordinator.signal_shutdown()
        
        if self.performance_tracker:
            await self.performance_tracker.stop()
        
        await self.telegram_bot.stop()
        
        # Закрываем сессию BinanceClient
        if self.client:
            try:
                await self.client.__aexit__(None, None, None)
                logger.info("BinanceClient session closed")
            except Exception as e:
                logger.error(f"Error closing BinanceClient session: {e}")
        
        logger.info("Bot stopped")


def main():
    bot = TradingBot()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        loop.create_task(bot.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        loop.run_until_complete(bot.start())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
