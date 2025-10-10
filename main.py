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


class TradingBot:
    def __init__(self):
        self.running = False
        self.client: Optional[BinanceClient] = None
        self.data_loader: Optional[DataLoader] = None
        self.symbols: List[str] = []
        
        # Компоненты бота
        self.strategy_manager = StrategyManager()
        self.signal_scorer = SignalScorer(config._config)  # Передаём внутренний словарь config
        self.btc_filter = BTCFilter(config._config)
        self.regime_detector = MarketRegimeDetector()
        
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
            async with BinanceClient() as client:
                self.client = client
                self.data_loader = DataLoader(client)
                
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
        
        logger.info(f"Loading warm-up data for {len(self.symbols)} symbols...")
        if self.data_loader:
            for symbol in self.symbols[:5]:
                logger.info(f"Loading data for {symbol}...")
                await self.data_loader.load_warm_up_data(symbol)
            await asyncio.sleep(0.5)
        
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
        
        iteration = 0
        check_interval = config.get('scanning.check_interval_seconds', 60)
        
        while self.running:
            iteration += 1
            
            # Каждые check_interval секунд проверяем сигналы
            if iteration % check_interval == 0:
                await self._check_signals()
            
            # Статус каждую минуту
            if iteration % 60 == 0 and self.client:
                rate_status = self.client.get_rate_limit_status()
                total_signals = self.strategy_manager.get_total_signals_count()
                logger.info(
                    f"Status: {len(self.symbols)} symbols | "
                    f"{self.strategy_manager.get_enabled_count()} strategies active | "
                    f"{total_signals} total signals | "
                    f"Rate limit: {rate_status['percent_used']:.1f}%"
                )
            
            await asyncio.sleep(1)
    
    async def _check_signals(self):
        """Проверить сигналы для всех символов"""
        if not self.data_loader:
            return
        
        logger.debug("Checking signals for all symbols...")
        
        # Загрузить BTC данные для фильтра
        btc_data = self.data_loader.get_candles('BTCUSDT', '1h', limit=100)
        
        # Проверяем несколько символов за раз
        for symbol in self.symbols[:10]:  # Лимит для тестирования
            try:
                await self._check_symbol_signals(symbol, btc_data)
            except Exception as e:
                logger.error(f"Error checking {symbol}: {e}")
            
            await asyncio.sleep(0.1)  # Небольшая пауза между символами
    
    async def _check_symbol_signals(self, symbol: str, btc_data):
        """Проверить сигналы для одного символа"""
        if not self.data_loader:
            return
        
        # Загрузить данные для всех таймфреймов
        timeframe_data = {}
        for tf in ['15m', '1h', '4h']:
            df = self.data_loader.get_candles(symbol, tf, limit=200)
            if df is not None and len(df) > 0:
                timeframe_data[tf] = df
        
        if not timeframe_data:
            return
        
        # Определить режим рынка и bias
        h4_data = timeframe_data.get('4h')
        if h4_data is None or len(h4_data) < 50:
            return
        
        regime = self.regime_detector.detect_regime(h4_data)
        bias = self.regime_detector.detect_bias(h4_data)
        
        # Рассчитать H4 swings для confluence проверки
        h4_swing_high = h4_data['high'].tail(20).max() if h4_data is not None and len(h4_data) >= 20 else None
        h4_swing_low = h4_data['low'].tail(20).min() if h4_data is not None and len(h4_data) >= 20 else None
        
        # Indicators для стратегий
        indicators = {
            'cvd': 0.0,
            'doi_pct': 0.0,
            'depth_imbalance': 1.0,
            'late_trend': False,
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
                logger.info(
                    f"✅ VALID SIGNAL: {signal.strategy_name} | "
                    f"{signal.symbol} {signal.direction} @ {signal.entry_price:.4f} | "
                    f"Score: {final_score:.1f} | SL: {signal.stop_loss:.4f} | "
                    f"TP1: {signal.take_profit_1:.4f} | TP2: {signal.take_profit_2:.4f}"
                )
                
                # TODO: Отправить в Telegram / сохранить в БД / выполнить ордер
            else:
                logger.debug(
                    f"❌ Signal rejected (score {final_score:.1f} < {self.signal_scorer.enter_threshold}): "
                    f"{signal.strategy_name} {signal.symbol} {signal.direction}"
                )
    
    async def stop(self):
        logger.info("Stopping bot...")
        self.running = False
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
