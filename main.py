import asyncio
import signal
import sys
from typing import List, Optional, Dict
from src.utils.logger import logger
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
from src.utils.strategy_validator import StrategyValidator
from src.utils.timeframe_sync import TimeframeSync
from src.database.db import db
from src.database.models import Signal
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
        self.coordinator: Optional[SymbolLoadCoordinator] = None
        self.performance_tracker: Optional[SignalPerformanceTracker] = None
        
        # Компоненты бота
        self.strategy_manager = StrategyManager()
        self.signal_scorer = SignalScorer(config._config)  # Передаём внутренний словарь config
        self.btc_filter = BTCFilter(config._config)
        self.regime_detector = MarketRegimeDetector()
        self.telegram_bot = TelegramBot()
        self.signal_lock_manager = SignalLockManager()
        
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
            self.data_loader = DataLoader(self.client)
            
            await self._initialize()
            await self._run_main_loop()
        
        except KeyboardInterrupt:
            logger.info("Shutdown signal received")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            await self.stop()
    
    async def _initialize(self):
        logger.info("Initializing bot...")
        
        if not self.client:
            raise Exception("Client not initialized")
        
        rate_limit_status = self.client.get_rate_limit_status()
        logger.info(f"Rate limit status: {rate_limit_status['current_weight']}/{rate_limit_status['limit']}")
        
        if config.get('universe.fetch_all_pairs', True):
            logger.info("Fetching all USDT-M futures pairs...")
            all_pairs = await self.client.get_futures_pairs()
            
            min_volume = config.get('universe.min_volume_24h', 10000000)
            ticker_data = await self.client.get_24h_ticker()
            
            if isinstance(ticker_data, dict):
                ticker_data = [ticker_data]
            
            volume_map = {t['symbol']: float(t['quoteVolume']) for t in ticker_data}
            
            self.symbols = [s for s in all_pairs if volume_map.get(s, 0) >= min_volume]
            logger.info(f"Filtered to {len(self.symbols)} pairs with volume >= ${min_volume:,.0f}")
        else:
            self.symbols = config.get('universe.initial_symbols', ['BTCUSDT', 'ETHUSDT'])
            logger.info(f"Using configured symbols: {self.symbols}")
        
        logger.info(f"Starting parallel data loading for {len(self.symbols)} symbols...")
        
        self.coordinator = SymbolLoadCoordinator(total_symbols=len(self.symbols), queue_max_size=50)
        
        loader_task = asyncio.create_task(self._symbol_loader_task())
        analyzer_task = asyncio.create_task(self._symbol_analyzer_task())
        
        logger.info("Background tasks started (loader + analyzer running in parallel)")
        logger.info("Bot will start analyzing symbols as soon as their data is loaded")
        
        # Запуск системы трекинга производительности
        check_interval = config.get('performance.tracking_interval_seconds', 60)
        self.performance_tracker = SignalPerformanceTracker(
            binance_client=self.client,
            db=db,
            lock_manager=self.signal_lock_manager,
            check_interval=check_interval
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
        timeframe_data = {}
        for tf in ['15m', '1h', '4h']:
            df = self.data_loader.get_candles(symbol, tf, limit=200)
            if df is not None and len(df) > 0:
                timeframe_data[tf] = df
        
        if not timeframe_data:
            logger.debug(f"❌ {symbol}: No timeframe data available")
            return
        
        # Определить режим рынка и bias
        h4_data = timeframe_data.get('4h')
        if h4_data is None or len(h4_data) < 50:
            logger.debug(f"❌ {symbol}: Insufficient H4 data ({len(h4_data) if h4_data is not None else 0} bars)")
            return
        
        regime_data = self.regime_detector.detect_regime(h4_data)
        regime = regime_data['regime'].value  # Convert ENUM to string
        bias = self.regime_detector.get_h4_bias(h4_data)
        
        logger.debug(f"🔍 Analyzing {symbol} | Regime: {regime} | Bias: {bias}")
        
        # Рассчитать H4 swings для confluence проверки
        h4_swing_high = h4_data['high'].tail(20).max() if h4_data is not None and len(h4_data) >= 20 else None
        h4_swing_low = h4_data['low'].tail(20).min() if h4_data is not None and len(h4_data) >= 20 else None
        
        # Indicators для стратегий
        indicators = {
            'cvd': 0.0,
            'doi_pct': 0.0,
            'depth_imbalance': 1.0,
            'late_trend': regime_data.get('late_trend', False),
            'funding_extreme': False,
            'btc_bias': self.btc_filter.get_btc_bias(btc_data) if btc_data is not None else 'Neutral',
            'h4_swing_high': h4_swing_high,
            'h4_swing_low': h4_swing_low
        }
        
        # Проверка MR блокировки по BTC
        if btc_data is not None:
            block_mr = self.btc_filter.should_block_mean_reversion(btc_data)
            if block_mr:
                logger.debug(f"{symbol}: MR strategies blocked due to BTC volatility")
        
        # Получить сигналы от всех стратегий
        signals = self.strategy_manager.check_all_signals(
            symbol=symbol,
            timeframe_data=timeframe_data,
            regime=regime,
            bias=bias,
            indicators=indicators
        )
        
        if signals:
            logger.debug(f"📊 {symbol}: {len(signals)} signals from strategies: {[s.strategy_name for s in signals]}")
        else:
            logger.debug(f"⚪ {symbol}: No signals from any strategy")
        
        # Применить скоринг к каждому сигналу
        for signal in signals:
            final_score = self.signal_scorer.score_signal(
                signal=signal,
                market_data={'df': timeframe_data.get(signal.timeframe)},
                indicators=indicators,
                btc_data=btc_data
            )
            
            # Проверить порог входа
            if self.signal_scorer.should_enter(final_score):
                logger.debug(f"✅ {signal.strategy_name} | {symbol} {signal.direction} | Score: {final_score:.1f} PASSED threshold")
                
                # Проверить блокировку символа (политика "1 сигнал на символ")
                lock_acquired = self.signal_lock_manager.acquire_lock(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    strategy_name=signal.strategy_name
                )
                
                if not lock_acquired:
                    logger.warning(
                        f"⏭️  Signal skipped (symbol locked): {signal.strategy_name} | "
                        f"{signal.symbol} {signal.direction}"
                    )
                    continue
            else:
                logger.debug(
                    f"❌ {signal.strategy_name} | {symbol} {signal.direction} | "
                    f"Score: {final_score:.1f} < threshold 2.0 | "
                    f"Base: {signal.base_score:.1f}, Vol: {signal.volume_ratio:.1f}x, "
                    f"CVD: {signal.cvd_direction}, Late: {signal.late_trend}, BTC: {signal.btc_against}"
                )
                continue
                
                logger.info(
                    f"✅ VALID SIGNAL: {signal.strategy_name} | "
                    f"{signal.symbol} {signal.direction} @ {signal.entry_price:.4f} | "
                    f"Score: {final_score:.1f} | SL: {signal.stop_loss:.4f} | "
                    f"TP1: {signal.take_profit_1:.4f} | TP2: {signal.take_profit_2:.4f}"
                )
                
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
                    'regime': regime
                })
                
                # Сохранить сигнал в БД
                self._save_signal_to_db(
                    signal=signal,
                    final_score=final_score,
                    regime=regime,
                    telegram_msg_id=telegram_msg_id
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
    
    def _save_signal_to_db(self, signal, final_score: float, regime: str, telegram_msg_id: Optional[int] = None):
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
                status='ACTIVE',
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
