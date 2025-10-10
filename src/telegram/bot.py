import asyncio
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from src.utils.config import config
from src.utils.logger import logger


class TelegramBot:
    def __init__(self):
        self.token = config.get_secret('telegram_bot_token')
        self.chat_id = config.get_secret('telegram_chat_id')
        self.app = None
        self.bot = None
        self.startup_message_sent = False
    
    async def start(self):
        if not self.token:
            logger.error("Telegram bot token not configured")
            return
        
        self.app = Application.builder().token(self.token).build()
        self.bot = self.app.bot
        
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("strategies", self.cmd_strategies))
        self.app.add_handler(CommandHandler("latency", self.cmd_latency))
        self.app.add_handler(CommandHandler("report", self.cmd_report))
        
        await self.app.initialize()
        await self.app.start()
        
        # Запуск polling в фоновом режиме для получения команд
        if self.app.updater:
            asyncio.create_task(self.app.updater.start_polling(drop_pending_updates=True))
            logger.info("Telegram bot started with polling")
        else:
            logger.warning("Telegram updater not available - commands will not work")
    
    async def stop(self):
        if self.app:
            try:
                if self.app.updater and self.app.updater.running:
                    await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except Exception as e:
                logger.error(f"Error stopping Telegram bot: {e}")
        logger.info("Telegram bot stopped")
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        welcome_text = (
            "🤖 *Торговый бот запущен*\n\n"
            "Доступные команды:\n"
            "/help - Справка\n"
            "/status - Статус бота\n"
            "/strategies - Список стратегий\n"
            "/latency - Задержки системы\n"
            "/report - Статистика сигналов\n"
        )
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        help_text = (
            "*Справка по командам:*\n\n"
            "/start - Начало работы\n"
            "/status - Состояние бота и рынков\n"
            "/strategies - Активные стратегии\n"
            "/latency - Задержки WebSocket\n"
            "/report - Статистика за период\n"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        status_text = "✅ Бот работает\n\nСтатус: в процессе разработки"
        await update.message.reply_text(status_text)
    
    async def cmd_strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        strategies_text = (
            "*Активные стратегии:*\n\n"
            "1. Donchian Breakout\n"
            "2. Squeeze→Breakout\n"
            "3. ORB/IRB\n"
            "4. MA/VWAP Pullback\n"
            "5. Break & Retest\n"
            "6. ATR Momentum\n"
            "7. VWAP Mean Reversion\n"
            "8. Range Fade\n"
        )
        await update.message.reply_text(strategies_text, parse_mode='Markdown')
    
    async def cmd_latency(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        await update.message.reply_text("⏱ Latency: в процессе разработки")
    
    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        await update.message.reply_text("📊 Report: в процессе разработки")
    
    async def send_startup_message(self, pairs_count: int, strategies_count: int, mode: str = "Signals-Only"):
        if not self.bot or not self.chat_id:
            logger.warning("Telegram bot not configured - skipping startup message")
            return
        
        # Отправляем только один раз
        if self.startup_message_sent:
            logger.debug("Startup message already sent, skipping")
            return
        
        try:
            message = (
                f"🤖 *Бот запущен!*\n\n"
                f"📊 *В работе:* {pairs_count} пар\n"
                f"🎯 *Активных стратегий:* {strategies_count}\n"
                f"⚙️ *Режим:* {mode}\n\n"
                f"Используйте /help для списка команд"
            )
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            self.startup_message_sent = True
            logger.info("Startup message sent to Telegram")
        except Exception as e:
            logger.error(f"Error sending startup message: {e}")
    
    async def send_signal(self, signal_data: dict):
        if not self.bot or not self.chat_id:
            return
        
        try:
            message = self._format_signal(signal_data)
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error sending signal: {e}")
    
    def _format_signal(self, signal_data: dict) -> str:
        direction_emoji = "🟢" if signal_data['direction'] == 'LONG' else "🔴"
        
        message = (
            f"{direction_emoji} *{signal_data['strategy_name']}*\n\n"
            f"📊 Символ: `{signal_data['symbol']}`\n"
            f"📈 Направление: *{signal_data['direction']}*\n"
            f"💰 Вход: `{signal_data['entry_price']:.4f}`\n"
            f"🛑 Стоп: `{signal_data['stop_loss']:.4f}`\n"
            f"🎯 TP1: `{signal_data.get('tp1', 'N/A')}`\n"
            f"🎯 TP2: `{signal_data.get('tp2', 'N/A')}`\n\n"
            f"⭐️ Скор: `{signal_data['score']:.1f}`\n"
            f"🔄 Режим: `{signal_data['regime']}`\n"
        )
        
        return message
