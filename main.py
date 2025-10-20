import asyncio
import signal
import sys
from typing import List, Optional, Dict
from src.utils.logger import logger
from src.utils.strategy_logger import strategy_logger
from src.utils.config import config
from src.binance.client import BinanceClient
from src.binance.data_loader import DataLoader
from src.data.fast_catchup import FastCatchupLoader
from src.data.periodic_gap_refill import PeriodicGapRefill
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
from datetime import datetime, timedelta
import pytz

# Action Price imports
from src.action_price.engine import ActionPriceEngine
from src.action_price.performance_tracker import ActionPricePerformanceTracker
from src.action_price.logger import ap_logger
from src.action_price.signal_logger import ActionPriceSignalLogger
from src.database.models import ActionPriceSignal


class TradingBot:
    def __init__(self):
        self.running = False
        self.client: Optional[BinanceClient] = None
        self.data_loader: Optional[DataLoader] = None
        self.fast_catchup: Optional[FastCatchupLoader] = None
        self.symbols: List[str] = []
        self.ready_symbols: List[str] = []  # Symbols with loaded data, ready for analysis
        
        # Раздельные блокировки для независимой работы систем
        # dict[strategy_name, set(symbols)] - каждая стратегия независимо блокирует символы
        self.symbols_blocked_main: dict = {}  # {strategy_name: {symbol1, symbol2, ...}}
        self.symbols_blocked_action_price: set = set()  # Заблокированы для Action Price
        
        self.catchup_done_symbols: set = set()  # Символы обработанные в fast catchup
        self.coordinator: Optional[SymbolLoadCoordinator] = None
        self.performance_tracker: Optional[SignalPerformanceTracker] = None
        
        # Action Price components (only enabled when use_testnet=false)
        self.action_price_engine: Optional[ActionPriceEngine] = None
        self.ap_performance_tracker: Optional[ActionPricePerformanceTracker] = None
        self.ap_signal_logger: Optional[ActionPriceSignalLogger] = None
        self.action_price_enabled = False
        
        # Компоненты бота
        self.strategy_manager = StrategyManager(binance_client=None)  # Will be set after client init
        self.signal_scorer = SignalScorer(config)  # Config object supports dot notation
        self.btc_filter = BTCFilter(config)  # Config object supports dot notation
        self.regime_detector = MarketRegimeDetector()
        self.telegram_bot = TelegramBot(binance_client=None)  # Will be set after client init
        self.signal_lock_manager = SignalLockManager()
        self.indicator_cache = IndicatorCache()  # Кеш для индикаторов
        
        self._check_signals_lock = asyncio.Lock()
        self._check_signals_task: Optional[asyncio.Task] = None
        self._is_checking_signals = False  # Флаг для индикации работы (без блокировки)
        
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
            
            # Задержка на старте для защиты от rate limit (только если кеш отсутствует)
            import os
            cache_file = 'data/exchange_info_cache.json'
            if not os.path.exists(cache_file):
                startup_delay = config.get('binance.startup_delay_seconds', 30)
                if startup_delay > 0:
                    logger.info(f"⏱️ Initial startup delay: {startup_delay}s (rate limit protection)")
                    await asyncio.sleep(startup_delay)
            
            # Загрузить информацию о символах (precision) для правильного форматирования цен
            await self.client.load_symbols_info()
            
            self.data_loader = DataLoader(self.client, self.telegram_bot)
            
            # Инициализация Fast Catchup Loader
            self.fast_catchup = FastCatchupLoader(self.data_loader, db)
            
            # Инициализация Periodic Gap Refill
            timezone_str = config.get('timezone', 'Europe/Kyiv')
            self.periodic_gap_refill = PeriodicGapRefill(self.data_loader, config, timezone_str)
            
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
        
        # Фильтр стейблкоинов (нулевая волатильность)
        if config.get('universe.exclude_stablecoins', True):
            stablecoins = config.get('universe.stablecoins', [])
            before_count = len(symbols)
            symbols = [s for s in symbols if s not in stablecoins]
            excluded_count = before_count - len(symbols)
            if excluded_count > 0:
                logger.info(f"Excluded {excluded_count} stablecoins: {', '.join([s for s in stablecoins if s in volume_map])}")
        
        # Фильтр по возрасту монет (минимум 90 дней на рынке)
        min_age_days = config.get('universe.min_coin_age_days', 90)
        if min_age_days > 0:
            logger.info(f"Filtering coins by minimum age ({min_age_days} days)...")
            aged_symbols = []
            young_symbols = []
            
            for symbol in symbols:
                age = await self.client.get_symbol_age_days(symbol)
                if age >= min_age_days:
                    aged_symbols.append(symbol)
                elif age > 0:
                    young_symbols.append((symbol, age))
            
            excluded_count = len(symbols) - len(aged_symbols)
            if excluded_count > 0:
                young_list = ', '.join([f"{s} ({age}d)" for s, age in sorted(young_symbols, key=lambda x: x[1])[:10]])
                logger.info(f"Excluded {excluded_count} young coins (age < {min_age_days} days): {young_list}{'...' if len(young_symbols) > 10 else ''}")
            
            symbols = aged_symbols
        
        return symbols
    
    async def _refresh_recent_data(self):
        """Обновить последние данные свечей в БД (за 10 дней)"""
        days = config.get('data_refresh.days', 10)
        enabled = config.get('data_refresh.enabled', True)
        
        if not enabled:
            logger.info("📊 Data refresh disabled in config - skipping")
            return
        
        logger.info(f"📊 Refreshing recent candle data ({days} days)...")
        
        # Получить все символы из БД
        session = db.get_session()
        try:
            from src.database.models import Candle
            result = session.query(Candle.symbol).distinct().all()
            db_symbols = [row[0] for row in result]
        finally:
            session.close()
        
        if not db_symbols:
            logger.info("📊 No symbols in DB - skipping data refresh")
            return
        
        logger.info(f"📊 Found {len(db_symbols)} symbols in DB - updating recent data...")
        
        success_count = 0
        error_count = 0
        
        for idx, symbol in enumerate(db_symbols, 1):
            try:
                # Проверить rate limit
                rate_status = self.client.get_rate_limit_status()
                usage_percent = rate_status['percent_used']
                
                # Если использование > 80%, подождать
                if usage_percent > 80:
                    wait_time = 5
                    logger.warning(f"⚠️ Rate limit {usage_percent:.1f}% - паузa {wait_time}s...")
                    await asyncio.sleep(wait_time)
                
                # Обновить данные для символа
                await self.data_loader.refresh_recent_candles(symbol, days=days)
                success_count += 1
                
                # Показать прогресс каждые 50 символов
                if idx % 50 == 0:
                    logger.info(f"📊 Progress: {idx}/{len(db_symbols)} symbols updated...")
                
                # Небольшая задержка между символами
                await asyncio.sleep(0.1)
                
            except Exception as e:
                error_count += 1
                logger.error(f"Error refreshing {symbol}: {e}")
                
                # Если rate limit error - увеличить задержку
                if "rate limit" in str(e).lower() or "429" in str(e):
                    logger.warning(f"⚠️ Rate limit error - пауза 10s...")
                    await asyncio.sleep(10)
        
        logger.info(
            f"✅ Data refresh complete: {success_count} success, {error_count} errors "
            f"({len(db_symbols)} total symbols)"
        )
    
    async def _initialize(self):
        logger.info("Initializing bot...")
        
        if not self.client:
            raise Exception("Client not initialized")
        
        rate_limit_status = self.client.get_rate_limit_status()
        logger.info(
            f"Rate limit status: {rate_limit_status['current_weight']}/{rate_limit_status['safe_limit']} "
            f"(90% threshold) | Hard limit: {rate_limit_status['hard_limit']} | "
            f"Usage: {rate_limit_status['percent_used']:.1f}%"
        )
        
        # Загрузить активные сигналы из БД и заблокировать символы
        self._load_active_signals_on_startup()
        
        # Получаем начальный список символов
        self.symbols = await self._fetch_symbols_by_volume()
        
        # Обновить последние данные свечей в БД (за 10 дней)
        await self._refresh_recent_data()
        
        logger.info(f"Starting parallel data loading for {len(self.symbols)} symbols...")
        
        self.coordinator = SymbolLoadCoordinator(total_symbols=len(self.symbols), queue_max_size=50)
        
        # ВАЖНО: Запустить analyzer ДО Fast Catchup, чтобы он мог потреблять символы из очереди
        # Иначе очередь переполнится и Fast Catchup зависнет на await ready_queue.put()
        analyzer_task = asyncio.create_task(self._symbol_analyzer_task())
        logger.info("Analyzer task started - ready to consume symbols from queue")
        
        # Сначала FAST CATCHUP для existing symbols с gaps
        await self._fast_catchup_phase()
        
        # Потом нормальный loader для новых символов
        loader_task = asyncio.create_task(self._symbol_loader_task())
        update_symbols_task = asyncio.create_task(self._update_symbols_task())
        periodic_gap_refill_task = asyncio.create_task(self._periodic_gap_refill_task())
        
        logger.info("Background tasks started (loader + analyzer + symbol updater + periodic gap refill running in parallel)")
        logger.info("Bot will start analyzing symbols as soon as their data is loaded")
        
        # Запуск системы трекинга производительности
        check_interval = config.get('performance.tracking_interval_seconds', 60)
        self.performance_tracker = SignalPerformanceTracker(
            binance_client=self.client,
            db=db,
            lock_manager=self.signal_lock_manager,
            check_interval=check_interval,
            on_signal_closed_callback=self._unblock_symbol_main  # Разблокировка для ОСНОВНЫХ стратегий
        )
        asyncio.create_task(self.performance_tracker.start())
        logger.info(f"📊 Signal Performance Tracker started (check interval: {check_interval}s)")
        
        # Action Price Engine (только для production режима)
        use_testnet = config.get('binance.use_testnet', True)
        ap_enabled = config.get('action_price.enabled', True)
        
        if not use_testnet and ap_enabled:
            self.action_price_enabled = True
            ap_config = config.get('action_price', {})
            
            # Создать JSONL logger для детального логирования
            self.ap_signal_logger = ActionPriceSignalLogger()
            
            # Создать engine с переданным logger
            self.action_price_engine = ActionPriceEngine(ap_config, self.client, self.ap_signal_logger)
            
            # Запуск Action Price Performance Tracker
            self.ap_performance_tracker = ActionPricePerformanceTracker(
                self.client,
                db,
                check_interval,
                self._unblock_symbol_action_price,  # Разблокировка для ACTION PRICE
                self.ap_signal_logger  # JSONL logger
            )
            asyncio.create_task(self.ap_performance_tracker.start())
            ap_logger.info("🎯 Action Price Engine initialized (Production mode)")
            ap_logger.info(f"🎯 Execution timeframes: {ap_config.get('execution_timeframes', ['15m', '1h'])}")
        else:
            reason = "testnet mode" if use_testnet else "disabled in config"
            logger.info(f"⏸️  Action Price disabled ({reason})")
        
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
        
        # Связать Action Price tracker если активирован
        if self.ap_performance_tracker:
            self.telegram_bot.set_ap_performance_tracker(self.ap_performance_tracker)
        
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
        
        # Вывести детальный статус стратегий
        status = self.strategy_manager.get_strategies_status()
        logger.info(f"\n{status}")
    
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
        
        while self.running:
            iteration += 1
            current_time = datetime.now(pytz.UTC)
            
            # Вычислить следующее время закрытия свечи для каждого таймфрейма
            next_15m = TimeframeSync.get_next_update_time('15m', current_time)
            next_1h = TimeframeSync.get_next_update_time('1h', current_time)
            next_4h = TimeframeSync.get_next_update_time('4h', current_time)
            next_1d = TimeframeSync.get_next_update_time('1d', current_time)
            
            # Найти самое раннее закрытие
            next_candle_close = min(next_15m, next_1h, next_4h, next_1d)
            
            # Добавить 6 секунд задержки для стабилизации данных Binance (1-3s обработка + 3s запас)
            target_time = next_candle_close + timedelta(seconds=6)
            
            # Вычислить время ожидания
            wait_seconds = (target_time - current_time).total_seconds()
            
            # Определить какие таймфреймы закроются
            closing_tfs = []
            if next_candle_close == next_15m:
                closing_tfs.append('15m')
            if next_candle_close == next_1h:
                closing_tfs.append('1h')
            if next_candle_close == next_4h:
                closing_tfs.append('4h')
            if next_candle_close == next_1d:
                closing_tfs.append('1d')
            
            if wait_seconds > 0:
                logger.info(
                    f"⏰ Next candle close: {', '.join(closing_tfs)} at {next_candle_close.strftime('%H:%M UTC')} "
                    f"(+6s = {target_time.strftime('%H:%M:%S')}) | Waiting {wait_seconds:.0f}s"
                )
                
                # Ждать до target_time, но показывать статус каждые 60 секунд
                while self.running:
                    current_time = datetime.now(pytz.UTC)
                    remaining = (target_time - current_time).total_seconds()
                    
                    if remaining <= 0:
                        break
                    
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
                                f"Rate: {rate_status['percent_used']:.1f}% | "
                                f"Next check in {remaining:.0f}s"
                            )
                        else:
                            logger.info(
                                f"Status: {len(self.symbols)} symbols | "
                                f"{self.strategy_manager.get_enabled_count()} strategies active | "
                                f"{total_signals} total signals | "
                                f"Rate limit: {rate_status['percent_used']:.1f}% | "
                                f"Next check in {remaining:.0f}s"
                            )
                    
                    iteration += 1
                    await asyncio.sleep(1)
            
            # Время пришло - запустить проверку сигналов (если есть готовые символы)
            if len(self.ready_symbols) > 0:
                # Запускаем только если предыдущая проверка завершена
                # Используем флаг вместо lock.locked() для проверки
                if not self._is_checking_signals:
                    logger.info(f"🚀 Candles closed: {', '.join(closing_tfs)} - starting signal check...")
                    self._check_signals_task = asyncio.create_task(self._check_signals_wrapper())
                else:
                    logger.warning("⏳ Previous signal check still running, skipping this cycle")
            
            await asyncio.sleep(1)
    
    async def _parallel_update_candles(self, symbols: list, timeframes: list):
        """
        Параллельная загрузка свечей для всех символов (Runtime Fast Catchup)
        
        Args:
            symbols: Список символов для обновления
            timeframes: Список таймфреймов для обновления
            
        Returns:
            Dict[str, List[str]]: Словарь {timeframe: [успешно обновленные символы]}
        """
        start_time = datetime.now()
        
        # Semaphore для контроля параллелизма (max 50 одновременно)
        # Предотвращает массовый поток запросов в 00:00/02:00 когда закрываются все таймфреймы
        semaphore = asyncio.Semaphore(50)
        
        async def update_symbol_tf(symbol: str, tf: str):
            """Обновить один символ на одном таймфрейме"""
            async with semaphore:  # Контроль параллелизма
                try:
                    await self.data_loader.update_missing_candles(symbol, tf)
                    return (symbol, tf, True)
                except Exception as e:
                    logger.debug(f"Could not update {symbol} {tf}: {e}")
                    return (symbol, tf, False)
        
        # Создать задачи для всех символов и таймфреймов
        tasks = []
        for symbol in symbols:
            for tf in timeframes:
                tasks.append(update_symbol_tf(symbol, tf))
        
        # Запустить все параллельно (Semaphore ограничивает до 50 одновременно)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Собрать успешно обновленные символы по таймфреймам
        updated_by_tf = {tf: [] for tf in timeframes}
        for result in results:
            if isinstance(result, tuple) and len(result) == 3:
                symbol, tf, success = result
                if success:
                    updated_by_tf[tf].append(symbol)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        success_count = sum(len(symbols) for symbols in updated_by_tf.values())
        total_requests = len(symbols) * len(timeframes)
        
        logger.info(
            f"⚡ Runtime Fast Catchup: {success_count}/{total_requests} updates "
            f"in {elapsed:.2f}s ({total_requests/elapsed:.1f} req/s) | "
            f"{len(symbols)} symbols × {len(timeframes)} TFs"
        )
        
        return updated_by_tf
    
    async def _fetch_all_orderbooks_parallel(self, symbols: list) -> Dict[str, Dict]:
        """
        ОПТИМИЗАЦИЯ: Параллельная загрузка orderbook для всех символов с агрессивным timeout
        
        Args:
            symbols: Список символов для загрузки orderbook
            
        Returns:
            Dict[symbol, orderbook_metrics]: Словарь с данными orderbook по символам
        """
        start_time = datetime.now()
        
        # Semaphore для контроля параллелизма (max 100 одновременно)
        # Orderbook - лёгкий запрос (weight=2), можем больше параллелизма
        semaphore = asyncio.Semaphore(100)
        
        async def fetch_one_orderbook(symbol: str):
            """Загрузить orderbook для одного символа с aggressive timeout"""
            async with semaphore:
                try:
                    # Timeout 5 секунд - плохие токены падают быстро
                    metrics = await OrderbookAnalyzer.fetch_and_calculate_depth(
                        client=self.client,
                        symbol=symbol,
                        limit=20,
                        use_weighted=True,
                        timeout=5.0  # Агрессивный timeout
                    )
                    return (symbol, metrics)
                except Exception as e:
                    logger.debug(f"Orderbook fetch failed for {symbol}: {e}")
                    return (symbol, {
                        'depth_imbalance': 0.0,
                        'bid_volume': 0.0,
                        'ask_volume': 0.0,
                        'spread_pct': 0.0,
                        'data_valid': False
                    })
        
        # Создать задачи для всех символов
        tasks = [fetch_one_orderbook(symbol) for symbol in symbols]
        
        # Запустить все параллельно (Semaphore ограничивает до 100 одновременно)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Собрать результаты в словарь
        orderbook_cache = {}
        valid_count = 0
        for result in results:
            if isinstance(result, tuple) and len(result) == 2:
                symbol, metrics = result
                orderbook_cache[symbol] = metrics
                if metrics.get('data_valid', False):
                    valid_count += 1
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        logger.info(
            f"⚡ Parallel Orderbook Fetch: {valid_count}/{len(symbols)} valid "
            f"in {elapsed:.2f}s ({len(symbols)/elapsed:.1f} req/s) | "
            f"Timeout: 5s per symbol"
        )
        
        return orderbook_cache
    
    async def _check_signals_wrapper(self):
        """Обёртка для _check_signals с логированием времени выполнения
        
        Note: Использует флаг вместо lock чтобы не блокировать следующие циклы
        во время медленных операций (загрузка candles, rate limiter sleep).
        """
        # Проверить флаг с lock (атомарная операция)
        async with self._check_signals_lock:
            if self._is_checking_signals:
                logger.debug("Signal check already in progress (concurrent protection)")
                return
            self._is_checking_signals = True
        
        start_time = datetime.now()
        try:
            # Выполнить проверку БЕЗ lock (не блокируем следующие циклы)
            await self._check_signals()
        except Exception as e:
            logger.error(f"Error in _check_signals: {e}", exc_info=True)
        finally:
            # Сбросить флаг с lock (атомарная операция)
            async with self._check_signals_lock:
                self._is_checking_signals = False
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            # Логировать cycle duration для мониторинга
            if elapsed > 90:
                logger.warning(f"⚠️ Signal check took {elapsed:.1f}s (>90s tolerance)")
            elif elapsed > 60:
                logger.info(f"⏱️  Signal check took {elapsed:.1f}s (>60s, monitor for drift)")
            else:
                logger.debug(f"✅ Signal check completed in {elapsed:.1f}s")
    
    async def _check_signals(self):
        """Проверить сигналы для всех готовых символов"""
        if not self.data_loader:
            return
        
        # Определить какие таймфреймы обновились (свечи закрылись)
        now = datetime.now(pytz.UTC)
        updated_timeframes = []
        
        if TimeframeSync.should_update_timeframe('15m', current_time=now, consumer_id='strategies'):
            updated_timeframes.append('15m')
        if TimeframeSync.should_update_timeframe('1h', current_time=now, consumer_id='strategies'):
            updated_timeframes.append('1h')
        if TimeframeSync.should_update_timeframe('4h', current_time=now, consumer_id='strategies'):
            updated_timeframes.append('4h')
        if TimeframeSync.should_update_timeframe('1d', current_time=now, consumer_id='strategies'):
            updated_timeframes.append('1d')
        
        # Если ни одна свеча не закрылась - пропускаем проверку стратегий
        if not updated_timeframes:
            logger.info(f"⏭️  No candles closed - skipping strategy check")
            return
        
        logger.info(f"🕯️  Candles closed: {', '.join(updated_timeframes)} - checking strategies")
        
        symbols_to_check = self.ready_symbols.copy()
        if not symbols_to_check:
            logger.debug("No symbols ready for analysis yet...")
            return
        
        # Все символы проверяются - блокировка теперь на уровне каждой стратегии отдельно
        symbols_to_update = symbols_to_check
        
        logger.debug(f"Checking signals for {len(symbols_to_update)} symbols on {', '.join(updated_timeframes)} timeframes...")
        
        # 1. ПАРАЛЛЕЛЬНО обновить BTC данные
        if '1h' in updated_timeframes:
            try:
                await self.data_loader.update_missing_candles('BTCUSDT', '1h')
                logger.info(f"✅ Updated BTCUSDT 1h data (candle closed at {now.strftime('%H:%M UTC')})")
            except Exception as e:
                logger.debug(f"Could not update BTCUSDT: {e}")
        
        # 2. ПАРАЛЛЕЛЬНО обновить все символы (Runtime Fast Catchup)
        updated_by_tf = {}
        if symbols_to_update:
            updated_by_tf = await self._parallel_update_candles(symbols_to_update, updated_timeframes)
        
        # 2.5. ЗАПУСК ACTION PRICE после сохранения 15m свечей
        if self.action_price_enabled and ('15m' in updated_timeframes or '1h' in updated_timeframes):
            # Определить символы с успешно обновленными 15m свечами
            symbols_for_ap = []
            if '15m' in updated_by_tf:
                symbols_for_ap.extend(updated_by_tf['15m'])
            if '1h' in updated_by_tf and '15m' not in updated_by_tf:
                # Если 1h закрылась но 15m не обновлялась, использовать 1h символы
                symbols_for_ap.extend(updated_by_tf['1h'])
            
            # Убрать дубликаты
            symbols_for_ap = list(set(symbols_for_ap))
            
            if symbols_for_ap:
                tf_4h_close = TimeframeSync.should_update_timeframe('4h', consumer_id='action_price')
                force_zone_recalc = (now.hour == 0 and now.minute == 0) or tf_4h_close
                await self._check_action_price_signals(now, symbols_for_ap, force_zone_recalc)
        
        btc_data = self.data_loader.get_candles('BTCUSDT', '1h', limit=100)
        
        # 3. Проверить стратегии для каждого символа (ПАРАЛЛЕЛЬНО)
        # Каждая стратегия проверяет блокировку независимо
        if symbols_to_check:
            batch_size = 20  # Обрабатывать по 20 символов параллельно
            total_batches = (len(symbols_to_check) + batch_size - 1) // batch_size
            
            logger.info(f"🔄 Starting parallel strategy checks: {len(symbols_to_check)} symbols in {total_batches} batches (batch_size={batch_size})")
            
            for batch_idx in range(0, len(symbols_to_check), batch_size):
                batch = symbols_to_check[batch_idx:batch_idx + batch_size]
                batch_num = (batch_idx // batch_size) + 1
                
                # Параллельная проверка батча
                tasks = [
                    self._check_symbol_signals_safe(symbol, btc_data, updated_timeframes)
                    for symbol in batch
                ]
                
                await asyncio.gather(*tasks)
                
                logger.debug(f"  ✅ Batch {batch_num}/{total_batches} completed ({len(batch)} symbols)")
            
            logger.info(f"✅ All strategy checks completed for {len(symbols_to_check)} symbols")
    
    async def _check_symbol_signals_safe(self, symbol: str, btc_data, updated_timeframes: list):
        """Обёртка для безопасной параллельной проверки сигналов (с обработкой ошибок)
        
        Args:
            symbol: Символ для проверки
            btc_data: BTC данные для фильтра
            updated_timeframes: Список обновившихся таймфреймов
        """
        try:
            await self._check_symbol_signals(symbol, btc_data, updated_timeframes)
        except Exception as e:
            logger.error(f"Error checking {symbol}: {e}")
    
    async def _check_symbol_signals(self, symbol: str, btc_data, updated_timeframes: list):
        """Проверить сигналы для одного символа
        
        Args:
            symbol: Символ для проверки
            btc_data: BTC данные для фильтра
            updated_timeframes: Список обновившихся таймфреймов (свечи которых закрылись)
        
        Note: Свечи уже обновлены параллельно в _check_signals через Runtime Fast Catchup
        """
        if not self.data_loader:
            return
        
        # Загрузить данные ТОЛЬКО для обновившихся таймфреймов
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
        for tf in updated_timeframes:  # ОПТИМИЗАЦИЯ: загружаем только обновившиеся таймфреймы
            limit = tf_limits.get(tf, 200)
            df = self.data_loader.get_candles(symbol, tf, limit=limit)
            if df is not None and len(df) > 0:
                timeframe_data[tf] = df
        
        # ВСЕГДА загружаем 4h для определения режима рынка (даже если свеча не закрылась)
        if '4h' not in timeframe_data:
            df_4h = self.data_loader.get_candles(symbol, '4h', limit=tf_limits['4h'])
            if df_4h is not None and len(df_4h) > 0:
                timeframe_data['4h'] = df_4h
        
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
            # Nested timeframe data with both DataFrames and indicators (for CVD Divergence)
            # This allows both old style (indicators['1h'] = DataFrame) and new style (indicators['15m_data']['df'])
            '15m_data': {
                'df': timeframe_data.get('15m'),
                **cached_indicators.get('15m', {})
            },
            '1h_data': {
                'df': timeframe_data.get('1h'),
                **cached_indicators.get('1h', {})
            },
            '4h_data': {
                'df': timeframe_data.get('4h'),
                **cached_indicators.get('4h', {})
            },
            # Keep backward compatibility for Break&Retest (expects direct DataFrames)
            '1h': timeframe_data.get('1h'),  # DataFrame 1H для HTF проверки
            '4h': timeframe_data.get('4h'),  # DataFrame 4H для HTF проверки
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
            blocked_symbols_by_strategy=self.symbols_blocked_main,  # Передать блокировки по стратегиям
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
                strategy_logger.info(f"\n✅ ПРОШЕЛ ПОРОГ (≥{self.signal_scorer.enter_threshold}) - ВАЛИДНЫЙ СИГНАЛ!")
                
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
                    f"TP1: {signal.take_profit_1:.4f} | TP2: {signal.take_profit_2:.4f}"
                )
                
                # MARKET entry - вход по текущей цене
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
                
                # Сохранить сигнал в БД - ТОЛЬКО если успешно, блокируем символ
                save_success = self._save_signal_to_db(
                    signal=signal,
                    final_score=final_score,
                    regime=regime,
                    telegram_msg_id=telegram_msg_id
                )
                
                # Заблокировать символ ТОЛЬКО после успешного сохранения (для ОСНОВНЫХ стратегий)
                if save_success:
                    self._block_symbol_main(signal.symbol, signal.strategy_name)
                else:
                    logger.warning(f"⚠️ {signal.symbol} NOT blocked - DB save failed")
            else:
                logger.debug(
                    f"❌ {signal.strategy_name} | {symbol} {signal.direction} | "
                    f"Score: {final_score:.1f} < threshold {self.signal_scorer.enter_threshold} | "
                    f"Base: {signal.base_score:.1f}, Vol: {signal.volume_ratio:.1f}x, "
                    f"CVD: {signal.cvd_direction}, Late: {signal.late_trend}, BTC: {signal.btc_against}"
                )
                strategy_logger.warning(f"❌ НЕ ПРОШЕЛ ПОРОГ: Score {final_score:.1f} < {self.signal_scorer.enter_threshold}")
                continue  # Пропустить сигналы с score < threshold
    
    async def _check_action_price_signals(self, current_time: datetime, symbols_with_updated_candles: list = None, force_zone_recalc: bool = False):
        """Проверить Action Price сигналы для символов с обновленными 15m свечами
        
        Args:
            current_time: Текущее время
            symbols_with_updated_candles: Список символов с успешно загруженными 15m/1h свечами
            force_zone_recalc: Принудительный пересчет зон
        """
        if not self.action_price_engine or not self.data_loader:
            return
        
        # Если не указаны символы - использовать все готовые
        if symbols_with_updated_candles is None:
            symbols_to_check = self.ready_symbols.copy()
        else:
            symbols_to_check = symbols_with_updated_candles
        
        if not symbols_to_check:
            return
        
        # Определить текущий таймфрейм
        tf_1h_close = TimeframeSync.should_update_timeframe('1h', consumer_id='action_price_check')
        current_tf = '1h' if tf_1h_close else '15m'
        
        ap_logger.info(
            f"🎯 Checking Action Price signals on {current_tf} close (force_recalc={force_zone_recalc})\n"
            f"  📊 Symbols with updated candles: {len(symbols_to_check)}"
        )
        
        signals_found = 0
        symbols_analyzed = 0
        symbols_blocked = 0
        
        for symbol in symbols_to_check:
            # Пропускаем символы с активными сигналами ACTION PRICE
            if symbol in self.symbols_blocked_action_price:
                symbols_blocked += 1
                ap_logger.debug(f"{symbol} - Blocked (active AP signal)")
                continue
            
            symbols_analyzed += 1
            
            try:
                # Загрузить данные для всех необходимых таймфреймов
                timeframe_data = {}
                for tf in ['15m', '1h', '4h', '1d']:
                    limits = {'15m': 500, '1h': 500, '4h': 500, '1d': 200}
                    df = self.data_loader.get_candles(symbol, tf, limit=limits.get(tf, 200))
                    if df is not None and len(df) > 0:
                        # DataLoader уже фильтрует незакрытые свечи (close_time > now)
                        # Поэтому все свечи в df - ЗАКРЫТЫЕ, дополнительная фильтрация НЕ нужна
                        timeframe_data[tf] = df
                
                # Требуем минимум 15m и 1h данные (4h и 1d опциональны)
                if '15m' not in timeframe_data or '1h' not in timeframe_data:
                    missing = []
                    if '15m' not in timeframe_data:
                        missing.append('15m')
                    if '1h' not in timeframe_data:
                        missing.append('1h')
                    ap_logger.debug(f"{symbol} - Missing required timeframes: {', '.join(missing)}")
                    continue
                
                # Анализ паттернов - новый EMA200 Body Cross engine
                # Использует 15m данные (или 1h если timeframe='1h')
                tf_data = timeframe_data.get(self.action_price_engine.timeframe, timeframe_data.get('15m'))
                ap_signal = await self.action_price_engine.analyze(
                    symbol=symbol,
                    df=tf_data,
                    df_1h=timeframe_data.get('1h')
                )
                
                # Обработать сигнал (новый engine возвращает один Dict или None)
                if ap_signal:
                    # Сохранить в БД - ТОЛЬКО если успешно, блокируем символ
                    save_success = self._save_action_price_signal(ap_signal)
                    
                    if save_success:
                        signals_found += 1
                        
                        # Заблокировать символ ТОЛЬКО после успешного сохранения (для ACTION PRICE)
                        self._block_symbol_action_price(symbol)
                        
                        # Отправить в Telegram
                        await self._send_action_price_telegram(ap_signal)
                        
                        ap_logger.info(
                            f"🎯 AP Signal: {ap_signal['symbol']} {ap_signal['direction']} "
                            f"{ap_signal['pattern_type']} @ {ap_signal.get('entry_price', 0):.4f} "
                            f"(Score: {ap_signal.get('confidence_score', 0):.1f})"
                        )
                    else:
                        ap_logger.warning(f"⚠️ Skipping {symbol} - failed to save signal to DB")
            
            except Exception as e:
                ap_logger.error(f"Error checking AP for {symbol}: {e}", exc_info=True)
            
            await asyncio.sleep(0.05)
        
        # Всегда логировать итоги анализа
        ap_logger.info(
            f"🎯 Action Price analysis complete:\n"
            f"  📊 Total symbols: {len(symbols_to_check)}\n"
            f"  🔍 Analyzed: {symbols_analyzed}\n"
            f"  🚫 Blocked: {symbols_blocked}\n"
            f"  ✅ Signals found: {signals_found}"
        )
    
    async def _fast_catchup_phase(self):
        """FAST CATCHUP: Быстрая параллельная догрузка gaps для existing symbols"""
        if not self.fast_catchup or not self.coordinator:
            return
        
        # Проверка включен ли fast catchup
        if not config.get('fast_catchup.enabled', True):
            logger.info("⚡ Fast catchup disabled in config - using normal loader")
            return
        
        current_time = datetime.now(pytz.UTC)
        
        # Анализ состояния БД
        existing_gaps, new_symbols = self.fast_catchup.analyze_restart_state(
            self.symbols, current_time
        )
        
        if not existing_gaps:
            logger.info("⚡ No gaps detected - all symbols are new or up-to-date")
            return
        
        # Показать статистику
        stats = self.fast_catchup.get_catchup_stats(existing_gaps)
        logger.info(
            f"⚡ BURST CATCHUP starting:\n"
            f"  📦 Symbols with gaps: {stats['total_symbols']}\n"
            f"  📊 Total gaps: {stats['total_gaps']}\n"
            f"  🕐 15m gaps: {stats['by_timeframe']['15m']['gaps']} ({stats['by_timeframe']['15m']['candles']} candles)\n"
            f"  🕑 1h gaps: {stats['by_timeframe']['1h']['gaps']} ({stats['by_timeframe']['1h']['candles']} candles)\n"
            f"  🕓 4h gaps: {stats['by_timeframe']['4h']['gaps']} ({stats['by_timeframe']['4h']['candles']} candles)\n"
            f"  🕔 1d gaps: {stats['by_timeframe']['1d']['gaps']} ({stats['by_timeframe']['1d']['candles']} candles)"
        )
        
        # Запуск burst catchup с настройками из config
        max_parallel = config.get('fast_catchup.max_parallel', None)
        success_count, failed_count = await self.fast_catchup.burst_catchup(
            existing_gaps, max_parallel=max_parallel
        )
        
        # Добавить успешно обработанные символы в ready queue
        # НО! Проверяем возраст символа перед добавлением
        min_age_days = config.get('universe.min_coin_age_days', 90)
        for symbol in existing_gaps.keys():
            if symbol not in self.coordinator._failed_symbols:
                # Проверка возраста для символов из БД (могли быть загружены до внедрения фильтра)
                if min_age_days > 0:
                    age = await self.client.get_symbol_age_days(symbol)
                    if age > 0 and age < min_age_days:
                        logger.debug(f"⏩ Fast Catchup: skipping {symbol} - too young ({age} days < {min_age_days} days)")
                        self.coordinator.mark_symbol_failed(symbol, f"Too young ({age}d < {min_age_days}d)")
                        continue
                
                await self.coordinator.add_ready_symbol(symbol)
                self.catchup_done_symbols.add(symbol)  # Track processed symbols
                logger.info(f"⚡ {symbol} caught up and ready")
        
        logger.info(
            f"⚡ BURST CATCHUP finished: {success_count} success, {failed_count} failed\n"
            f"📊 {len(new_symbols)} new symbols will be loaded by normal loader"
        )
    
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
            
            # Пропускаем символы уже обработанные в fast catchup
            if symbol in self.catchup_done_symbols:
                logger.debug(f"⚡ Skipping {symbol} - already processed in catchup")
                continue
            
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
    
    async def _periodic_gap_refill_task(self):
        """Background task to periodically refill gaps every 15 minutes"""
        if not config.get('periodic_gap_refill.enabled', True):
            logger.info("Periodic gap refill disabled")
            return
        
        # Ждем перед первым запуском (пусть бот загрузится)
        await asyncio.sleep(60)
        
        logger.info("🔄 Periodic gap refill started (interval: 15 minutes)")
        
        while self.running:
            # Ждать 15 минут до следующей проверки
            await asyncio.sleep(15 * 60)  # 15 минут
            
            if not self.running:
                break
            
            try:
                # Запустить периодическую докачку gaps
                await self.periodic_gap_refill.run_periodic_check(self.ready_symbols)
                
            except Exception as e:
                logger.error(f"Error in periodic gap refill: {e}", exc_info=True)
        
        logger.info("Periodic gap refill task stopped")
    
    def _save_signal_to_db(self, signal, final_score: float, regime: str, telegram_msg_id: Optional[int] = None, status: str = 'ACTIVE') -> bool:
        """
        Сохранить сигнал в базу данных
        
        Returns:
            bool: True если успешно сохранено, False если ошибка
        """
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
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save signal to DB: {e}", exc_info=True)
            return False
        finally:
            session.close()
    
    def _save_action_price_signal(self, ap_signal: Dict) -> bool:
        """
        Сохранить Action Price сигнал в БД
        
        Returns:
            bool: True если успешно сохранено, False если ошибка
        """
        session = db.get_session()
        try:
            # Получить meta_data
            meta_data = ap_signal.get('meta_data', {})
            
            # Получить risk_reward из rr1 (первая цель)
            risk_reward = meta_data.get('rr1', 1.5)
            
            # Получить zone_touches из meta_data
            zone_touches = meta_data.get('zone_touches', 0)
            
            # Сформировать confluence list из флагов
            confluence_flags = ap_signal.get('confluence_flags', {})
            confluences = []
            if confluence_flags.get('avwap_primary'):
                confluences.append('AVWAP Primary')
            if confluence_flags.get('avwap_secondary'):
                confluences.append('AVWAP Secondary')
            if confluence_flags.get('daily_vwap'):
                confluences.append('Daily VWAP')
            if confluence_flags.get('zone_sr'):
                confluences.append('S/R Zone')
            
            confluences_str = ', '.join(confluences) if confluences else None
            
            signal = ActionPriceSignal(
                context_hash=ap_signal.get('context_hash', f"{ap_signal['symbol']}_{ap_signal['direction']}_{int(datetime.now(pytz.UTC).timestamp())}"),
                symbol=ap_signal['symbol'],
                timeframe=ap_signal['timeframe'],
                direction=ap_signal['direction'],
                pattern_type=ap_signal['pattern_type'],
                zone_id=ap_signal.get('zone_id', 'unknown'),
                zone_low=float(ap_signal.get('zone_low', 0)),
                zone_high=float(ap_signal.get('zone_high', 0)),
                entry_price=float(ap_signal['entry_price']),
                stop_loss=float(ap_signal['stop_loss']),
                take_profit_1=float(ap_signal['take_profit_1']) if ap_signal.get('take_profit_1') else None,
                take_profit_2=float(ap_signal['take_profit_2']) if ap_signal.get('take_profit_2') else None,
                avwap_primary=ap_signal.get('avwap_primary'),
                avwap_secondary=ap_signal.get('avwap_secondary'),
                daily_vwap=ap_signal.get('daily_vwap'),
                ema_50_4h=ap_signal.get('ema_50_4h'),
                ema_200_4h=ap_signal.get('ema_200_4h'),
                ema_50_1h=ap_signal.get('ema_50_1h'),
                ema_200_1h=ap_signal.get('ema_200_1h'),
                confidence_score=float(ap_signal.get('confidence_score', 0)),
                confluence_flags=ap_signal.get('confluence_flags', {}),
                market_regime=ap_signal.get('regime', ''),
                status='ACTIVE',
                meta_data=ap_signal.get('meta_data', {}),
                created_at=datetime.now(pytz.UTC)
            )
            
            session.add(signal)
            session.commit()
            ap_logger.info(f"💾 Saved AP signal to DB: {ap_signal['symbol']} {ap_signal['direction']}")
            return True
            
        except Exception as e:
            session.rollback()
            ap_logger.error(f"Failed to save AP signal to DB: {e}", exc_info=True)
            return False
        finally:
            session.close()
    
    async def _send_action_price_telegram(self, ap_signal: Dict):
        """Отправить Action Price сигнал в Telegram"""
        try:
            # Формат для EMA200 Body Cross
            pattern_emoji = {
                'body_cross': '🎯',
                'pin_bar': '📌',
                'engulfing': '🔥',
                'inside_bar': '📦',
                'fakey': '🎭',
                'ppr': '🔄'
            }
            
            pattern_type = ap_signal.get('pattern_type', 'body_cross')
            emoji = pattern_emoji.get(pattern_type, '🎯')
            direction_emoji = '🟢' if ap_signal['direction'].lower() == 'long' else '🔴'
            
            # Получить meta_data
            meta_data = ap_signal.get('meta_data', {})
            
            # Получить confluence flags
            confluence_flags = ap_signal.get('confluence_flags', {})
            confluences = []
            if confluence_flags.get('avwap_primary'):
                confluences.append('AVWAP Primary')
            if confluence_flags.get('avwap_secondary'):
                confluences.append('AVWAP Secondary')
            if confluence_flags.get('daily_vwap'):
                confluences.append('Daily VWAP')
            if confluence_flags.get('zone_sr'):
                confluences.append('S/R Zone')
            
            # Получить цены и риск для расчёта R:R
            entry = ap_signal['entry_price']
            sl = ap_signal['stop_loss']
            tp1 = ap_signal.get('take_profit_1')
            tp2 = ap_signal.get('take_profit_2')
            risk = abs(entry - sl)
            
            # Форматировать цены с точностью Binance
            symbol = ap_signal['symbol']
            entry_fmt = self.client.format_price(symbol, entry)
            sl_fmt = self.client.format_price(symbol, sl)
            
            message = (
                f"🎯 <b>ACTION PRICE SIGNAL</b>\n\n"
                f"{direction_emoji} <b>{ap_signal['symbol']} {ap_signal['direction']}</b>\n"
                f"{emoji} Стратегия: <b>EMA200 Body Cross</b>\n"
                f"📊 Таймфрейм: <b>{ap_signal['timeframe']}</b>\n"
                f"⭐ Score: <b>{ap_signal.get('confidence_score', 0):.1f}</b>\n\n"
                f"💰 Вход: <b>{entry_fmt}</b>\n"
                f"🛑 Стоп: <b>{sl_fmt}</b>\n"
            )
            
            # Показать TP уровни с их R:R
            if tp1:
                tp1_fmt = self.client.format_price(symbol, tp1)
                rr1 = abs(tp1 - entry) / risk if risk > 0 else 0.0
                message += f"🎯 TP1 (30%): <b>{tp1_fmt}</b> | R:R <b>1:{rr1:.1f}</b>\n"
            
            if tp2:
                tp2_fmt = self.client.format_price(symbol, tp2)
                rr2 = abs(tp2 - entry) / risk if risk > 0 else 0.0
                message += f"🎯 TP2 (40%): <b>{tp2_fmt}</b> | R:R <b>1:{rr2:.1f}</b>\n"
            
            # Если есть TP3 (для будущего расширения)
            tp3 = ap_signal.get('take_profit_3')
            if tp3:
                tp3_fmt = self.client.format_price(symbol, tp3)
                rr3 = abs(tp3 - entry) / risk if risk > 0 else 0.0
                message += f"🎯 TP3 (30%): <b>{tp3_fmt}</b> | R:R <b>1:{rr3:.1f}</b>\n"
            
            message += "\n"
            
            # Добавить таблицу с деталями свечей
            from datetime import datetime
            import pytz
            
            # Получить timestamp и данные свечей
            init_ts_str = ap_signal.get('initiator_timestamp')
            confirm_ts_str = ap_signal.get('timestamp_open')
            
            init_open = ap_signal.get('initiator_open')
            init_close = ap_signal.get('initiator_close')
            init_ema200 = ap_signal.get('initiator_ema200')
            
            confirm_high = ap_signal.get('confirm_high')
            confirm_low = ap_signal.get('confirm_low')
            confirm_ema200 = ap_signal.get('confirm_ema200')
            
            if all([init_ts_str, confirm_ts_str, init_open, init_close, init_ema200, confirm_high, confirm_low, confirm_ema200]):
                # Конвертировать timestamp в локальное время (EEST)
                eest_tz = pytz.timezone('Europe/Kiev')
                
                init_dt = datetime.fromisoformat(init_ts_str.replace('Z', '+00:00'))
                init_dt_local = init_dt.astimezone(eest_tz)
                init_time_fmt = init_dt_local.strftime('%d %b %H:%M')
                
                confirm_dt = datetime.fromisoformat(confirm_ts_str.replace('Z', '+00:00'))
                confirm_dt_local = confirm_dt.astimezone(eest_tz)
                confirm_time_fmt = confirm_dt_local.strftime('%d %b %H:%M')
                
                # Форматировать цены
                init_open_fmt = self.client.format_price(symbol, init_open)
                init_close_fmt = self.client.format_price(symbol, init_close)
                init_ema200_fmt = self.client.format_price(symbol, init_ema200)
                
                confirm_high_fmt = self.client.format_price(symbol, confirm_high)
                confirm_low_fmt = self.client.format_price(symbol, confirm_low)
                confirm_ema200_fmt = self.client.format_price(symbol, confirm_ema200)
                
                # Добавить таблицу
                message += (
                    f"📊 <b>Анализ свечей:</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔶 Индикатор     | {init_time_fmt}\n"
                    f"   O→C: {init_open_fmt} → {init_close_fmt}\n"
                    f"   EMA200: {init_ema200_fmt}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ Подтверждение | {confirm_time_fmt}\n"
                    f"   H-L: {confirm_high_fmt} - {confirm_low_fmt}\n"
                    f"   EMA200: {confirm_ema200_fmt}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            
            # Конфлюэнсы
            if confluences:
                message += "✅ <b>Конфлюэнсы:</b>\n"
                for conf in confluences:
                    message += f"  • {conf}\n"
            
            # Проверка что Telegram инициализирован
            if not self.telegram_bot or not self.telegram_bot.bot or not self.telegram_bot.chat_id:
                ap_logger.warning("Telegram bot not initialized - skipping AP signal notification")
                return
            
            await self.telegram_bot.bot.send_message(
                chat_id=self.telegram_bot.chat_id,
                text=message,
                parse_mode='HTML'
            )
            ap_logger.info(f"📤 Sent AP signal to Telegram: {ap_signal['symbol']} {ap_signal['direction']}")
            
        except Exception as e:
            ap_logger.error(f"Failed to send AP signal to Telegram: {e}", exc_info=True)
    
    def _load_active_signals_on_startup(self):
        """Загрузить активные сигналы из БД при старте и заблокировать символы"""
        session = db.get_session()
        try:
            # Получить все активные и pending сигналы из основной таблицы
            active_signals = session.query(Signal).filter(
                Signal.status.in_(['ACTIVE', 'PENDING'])
            ).all()
            
            # Получить активные Action Price сигналы
            active_ap_signals = session.query(ActionPriceSignal).filter(
                ActionPriceSignal.status.in_(['ACTIVE', 'PENDING'])
            ).all()
            
            total_active = len(active_signals) + len(active_ap_signals)
            
            if active_signals or active_ap_signals:
                # Добавить символы в РАЗДЕЛЬНЫЕ блокировки (по стратегиям для Main)
                for signal in active_signals:
                    self._block_symbol_main(str(signal.symbol), signal.strategy_name)
                for ap_signal in active_ap_signals:
                    self.symbols_blocked_action_price.add(str(ap_signal.symbol))
                
                # Подсчитать общее количество заблокированных символов для main
                total_main_blocked = sum(len(symbols) for symbols in self.symbols_blocked_main.values())
                
                logger.info(
                    f"🔒 Loaded {total_active} active signals "
                    f"(Main: {len(active_signals)}, AP: {len(active_ap_signals)})"
                )
                logger.info(
                    f"   • Main strategies: {total_main_blocked} symbols blocked across {len(self.symbols_blocked_main)} strategies"
                )
                logger.info(
                    f"   • Action Price: {len(self.symbols_blocked_action_price)} symbols blocked"
                )
                if self.symbols_blocked_main:
                    for strategy_name, blocked_symbols in self.symbols_blocked_main.items():
                        logger.debug(f"{strategy_name} blocked: {', '.join(sorted(blocked_symbols))}")
                if self.symbols_blocked_action_price:
                    logger.debug(f"AP blocked: {', '.join(sorted(self.symbols_blocked_action_price))}")
            else:
                logger.info("✅ No active signals in DB - all symbols available for analysis")
                
        except Exception as e:
            logger.error(f"Error loading active signals on startup: {e}", exc_info=True)
        finally:
            session.close()
    
    def _block_symbol_main(self, symbol: str, strategy_name: str):
        """Заблокировать символ для конкретной стратегии (есть активный сигнал)"""
        if strategy_name not in self.symbols_blocked_main:
            self.symbols_blocked_main[strategy_name] = set()
        self.symbols_blocked_main[strategy_name].add(symbol)
        logger.info(f"🔒 {strategy_name}: {symbol} blocked (active signal)")
    
    def _block_symbol_action_price(self, symbol: str):
        """Заблокировать символ для Action Price (есть активный сигнал)"""
        self.symbols_blocked_action_price.add(symbol)
        logger.info(f"🔒 AP: {symbol} blocked (active signal)")
    
    def _unblock_symbol_main(self, symbol: str, strategy_name: str):
        """Разблокировать символ для конкретной стратегии (сигнал закрыт)"""
        try:
            if strategy_name in self.symbols_blocked_main:
                self.symbols_blocked_main[strategy_name].discard(symbol)
                logger.info(f"🔓 {strategy_name}: {symbol} unblocked (signal closed)")
                # Удалить стратегию из словаря если больше нет заблокированных символов
                if not self.symbols_blocked_main[strategy_name]:
                    del self.symbols_blocked_main[strategy_name]
        except Exception as e:
            logger.error(f"Error unblocking symbol {symbol} for {strategy_name}: {e}", exc_info=True)
    
    def _unblock_symbol_action_price(self, symbol: str):
        """Разблокировать символ для Action Price (сигнал закрыт)"""
        try:
            if symbol in self.symbols_blocked_action_price:
                self.symbols_blocked_action_price.discard(symbol)
                logger.info(f"🔓 AP: {symbol} unblocked (signal closed)")
        except Exception as e:
            logger.error(f"Error unblocking symbol {symbol} for AP: {e}", exc_info=True)
    
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
        
        if self.ap_performance_tracker:
            await self.ap_performance_tracker.stop()
        
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
