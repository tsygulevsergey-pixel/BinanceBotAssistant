import asyncio
import signal
import sys
from src.utils.logger import logger
from src.utils.config import config
from src.binance.client import BinanceClient
from src.binance.data_loader import DataLoader


class TradingBot:
    def __init__(self):
        self.running = False
        self.client = None
        self.data_loader = None
        self.symbols = []
    
    async def start(self):
        logger.info("=" * 60)
        logger.info("Trading Bot Starting...")
        logger.info("=" * 60)
        
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
        for symbol in self.symbols[:5]:
            logger.info(f"Loading data for {symbol}...")
            await self.data_loader.load_warm_up_data(symbol)
            await asyncio.sleep(0.5)
        
        logger.info("Initialization complete")
    
    async def _run_main_loop(self):
        logger.info("Starting main loop...")
        
        iteration = 0
        while self.running:
            iteration += 1
            
            if iteration % 60 == 0:
                rate_status = self.client.get_rate_limit_status()
                logger.info(
                    f"Status: {len(self.symbols)} symbols tracked | "
                    f"Rate limit: {rate_status['percent_used']:.1f}%"
                )
            
            await asyncio.sleep(1)
    
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
