import asyncio
from datetime import datetime, timedelta
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from src.utils.config import config
from src.utils.logger import logger
from src.database.models import Signal, ActionPriceSignal
from src.database.db import Database
import pytz


class TelegramBot:
    TELEGRAM_MAX_LENGTH = 4000  # Лимит Telegram 4096, оставляем запас
    
    def __init__(self, binance_client=None):
        self.token = config.get_secret('telegram_bot_token')
        self.chat_id = config.get_secret('telegram_chat_id')
        self.app = None
        self.bot = None
        self.startup_message_sent = False
        self.performance_tracker = None
        self.ap_performance_tracker = None  # Action Price tracker
        self.strategy_validator = None
        self.binance_client = binance_client
        self.db = Database()
    
    async def start(self):
        if not self.token:
            logger.error("Telegram bot token not configured")
            return
        
        try:
            # Proxy support (опционально)
            builder = Application.builder().token(self.token)
            
            # Увеличенные таймауты для стабильности (особенно на Windows)
            from telegram.request import HTTPXRequest
            
            proxy_url = config.get_secret('telegram_proxy_url')
            if proxy_url:
                logger.info(f"🌐 Using proxy for Telegram: {proxy_url}")
                from httpx import AsyncClient
                http_client = AsyncClient(proxy=proxy_url, timeout=60.0)
                builder = builder.request(HTTPXRequest(client=http_client))
            else:
                # Увеличенный таймаут для подключения (помогает на медленных сетях)
                builder = builder.connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0)
            
            # Retry логика для временных сбоев
            builder = builder.pool_timeout(30.0)
            
            self.app = builder.build()
            self.bot = self.app.bot
        except Exception as e:
            logger.error(f"❌ Failed to initialize Telegram bot: {e}")
            logger.warning("⚠️  Bot will continue WITHOUT Telegram notifications")
            logger.warning("⚠️  Check your TELEGRAM_BOT_TOKEN and internet connection")
            self.app = None
            self.bot = None
            return
        
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("strategies", self.cmd_strategies))
        self.app.add_handler(CommandHandler("latency", self.cmd_latency))
        self.app.add_handler(CommandHandler("report", self.cmd_report))
        self.app.add_handler(CommandHandler("performance", self.cmd_performance))
        self.app.add_handler(CommandHandler("stats", self.cmd_stats))
        self.app.add_handler(CommandHandler("ap_stats", self.cmd_ap_stats))
        self.app.add_handler(CommandHandler("closed", self.cmd_closed))
        self.app.add_handler(CommandHandler("closed_ap", self.cmd_closed_ap))
        self.app.add_handler(CommandHandler("closed_ap_sl", self.cmd_closed_ap_sl))
        self.app.add_handler(CommandHandler("closed_ap_tp", self.cmd_closed_ap_tp))
        self.app.add_handler(CommandHandler("menu", self.cmd_menu))
        self.app.add_handler(CommandHandler("validate", self.cmd_validate))
        # Новые профессиональные команды
        self.app.add_handler(CommandHandler("regime_stats", self.cmd_regime_stats))
        self.app.add_handler(CommandHandler("confluence_stats", self.cmd_confluence_stats))
        # Обработчик нажатий на кнопки клавиатуры
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_keyboard_buttons))
        
        try:
            await self.app.initialize()
            await self.app.start()
            
            # Запуск polling в фоновом режиме для получения команд
            if self.app.updater:
                asyncio.create_task(self.app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=Update.ALL_TYPES
                ))
                logger.info("✅ Telegram bot started with polling")
            else:
                logger.warning("⚠️  Telegram updater not available - commands will not work")
        except Exception as e:
            logger.error(f"❌ Failed to start Telegram polling: {e}")
            logger.warning("⚠️  Bot will continue WITHOUT Telegram notifications")
            logger.warning("💡 This is usually a temporary network issue. Bot will keep trying...")
            self.app = None
            self.bot = None
    
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
    
    def _is_telegram_available(self) -> bool:
        """Проверить доступность Telegram бота"""
        if self.bot is None or self.app is None:
            logger.debug("⚠️  Telegram not available - skipping notification")
            return False
        return True
    
    def get_main_keyboard(self):
        """Создать главную клавиатуру с кнопками"""
        keyboard = [
            [KeyboardButton("📊 Производительность"), KeyboardButton("🎯 Action Price")],
            [KeyboardButton("📋 Закрытые сигналы"), KeyboardButton("📈 Закрытые AP")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    async def handle_keyboard_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на кнопки клавиатуры"""
        if not update.message or not update.message.text:
            return
        
        text = update.message.text
        
        if text == "📊 Производительность":
            await self.cmd_performance(update, context)
        elif text == "🎯 Action Price":
            await self.cmd_ap_stats(update, context)
        elif text == "📋 Закрытые сигналы":
            await self.cmd_closed(update, context)
        elif text == "📈 Закрытые AP":
            await self.cmd_closed_ap(update, context)
    
    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать/скрыть главную клавиатуру"""
        if not update.message:
            return
        
        # Проверяем аргумент: hide для скрытия, иначе показываем
        if context.args and context.args[0].lower() == 'hide':
            await update.message.reply_text(
                "🔹 Клавиатура скрыта\n\nИспользуй /menu чтобы показать снова",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            await update.message.reply_text(
                "🔹 Клавиатура активирована\n\nИспользуй /menu hide чтобы скрыть",
                reply_markup=self.get_main_keyboard()
            )
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        welcome_text = (
            "🤖 <b>Торговый бот запущен</b>\n\n"
            "📊 <b>Основные команды:</b>\n"
            "/help - Справка\n"
            "/menu - Показать/скрыть клавиатуру\n"
            "/status - Статус бота\n"
            "/strategies - Список стратегий\n"
            "/performance - Производительность (7 дней)\n"
            "/stats - Статистика по стратегиям\n"
            "/ap_stats - Action Price статистика\n"
            "/closed - Закрытые сигналы (24ч)\n"
            "/closed_ap - Закрытые Action Price (24ч)\n\n"
            "📈 <b>Профессиональная аналитика:</b>\n"
            "/regime_stats - Статистика по режимам рынка\n"
            "/confluence_stats - Эффективность confluence\n\n"
            "⚙️ <b>Диагностика:</b>\n"
            "/validate - Проверка стратегий\n"
            "/latency - Задержки системы\n"
            "/report - Статистика сигналов\n\n"
            "Используй кнопки внизу для быстрого доступа! 👇"
        )
        await update.message.reply_text(
            welcome_text, 
            parse_mode='HTML',
            reply_markup=self.get_main_keyboard()
        )
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        help_text = (
            "<b>Справка по командам:</b>\n\n"
            "/start - Начало работы\n"
            "/menu - Показать/скрыть клавиатуру\n"
            "/status - Состояние бота и рынков\n"
            "/strategies - Активные стратегии\n"
            "/performance - Win rate, PnL за 7 дней\n"
            "/stats - Детали по стратегиям\n"
            "/ap_stats - Action Price статистика\n"
            "/closed [часы] - Закрытые сигналы (по умолчанию 24ч)\n"
            "/closed_ap [часы] - Все закрытые Action Price (по умолчанию 24ч)\n"
            "/closed_ap_sl [часы] - Только Stop Loss Action Price\n"
            "/closed_ap_tp [часы] - Только TP/BE Action Price\n"
            "/validate - Проверка корректности стратегий\n"
            "/regime_stats - Статистика по режимам рынка\n"
            "/confluence_stats - Эффективность confluence\n"
            "/latency - Задержки WebSocket\n"
            "/report - Статистика за период\n"
        )
        await update.message.reply_text(help_text, parse_mode='HTML')
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        status_text = "✅ Бот работает\n\nСтатус: в процессе разработки"
        await update.message.reply_text(status_text)
    
    async def cmd_strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        strategies_text = (
            "<b>Активные стратегии:</b>\n\n"
            "1. Donchian Breakout\n"
            "2. Squeeze → Breakout\n"
            "3. ORB/IRB\n"
            "4. MA/VWAP Pullback\n"
            "5. Break &amp; Retest\n"
            "6. ATR Momentum\n"
            "7. VWAP Mean Reversion\n"
            "8. Range Fade\n"
            "9. Volume Profile\n"
            "10. RSI/Stoch MR\n"
            "11. Liquidity Sweep\n"
            "12. Order Flow\n"
            "13. CVD Divergence\n"
            "14. Time of Day\n"
            "15. Cash &amp; Carry\n"
            "16. Market Making\n\n"
            "🎯 <b>Action Price</b> (отдельная статистика)\n"
            "   • Pin-Bar, Engulfing, Inside-Bar\n"
            "   • Fakey, ППР\n"
            "   • Команда: /ap_stats\n"
        )
        await update.message.reply_text(strategies_text, parse_mode='HTML')
    
    async def cmd_latency(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        await update.message.reply_text("⏱ Latency: в процессе разработки")
    
    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        await update.message.reply_text("📊 Report: в процессе разработки")
    
    async def cmd_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать общую производительность за 7 дней"""
        if not update.message:
            return
        
        if not self.performance_tracker:
            await update.message.reply_text("⚠️ Трекер производительности не запущен")
            return
        
        try:
            perf = await self.performance_tracker.get_strategy_performance(days=7)
            
            text = (
                f"📊 <b>Производительность (7 дней)</b>\n\n"
                f"📈 Всего сигналов: {perf['total_signals']}\n"
                f"✅ Закрыто: {perf['closed_signals']}\n"
                f"🔄 Активных: {perf['active_signals']}\n\n"
                f"🏆 Побед: {perf['wins']}\n"
                f"❌ Поражений: {perf['losses']}\n"
                f"📊 Win Rate: <b>{perf['win_rate']}%</b>\n\n"
                f"🎯 TP1 (0.5R): {perf.get('tp1_count', 0)}\n"
                f"🎯 TP2 (1.5R): {perf.get('tp2_count', 0)}\n"
                f"⚖️ Breakeven: {perf.get('breakeven_count', 0)}\n"
                f"⏱️ Time Stop: {perf.get('time_stop_count', 0)} | "
                f"PnL: {perf.get('time_stop_total_pnl', 0):+.2f}%\n\n"
                f"💰 Средний PnL: <b>{perf['avg_pnl']:+.2f}%</b>\n"
                f"💵 Общий PnL: <b>{perf['total_pnl']:+.2f}%</b>\n\n"
                f"🟢 Средняя победа: {perf['avg_win']:+.2f}%\n"
                f"🔴 Среднее поражение: {perf['avg_loss']:+.2f}%\n"
            )
            await update.message.reply_text(text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error getting performance: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать статистику по стратегиям"""
        if not update.message:
            return
        
        if not self.performance_tracker:
            await update.message.reply_text("⚠️ Трекер производительности не запущен")
            return
        
        try:
            stats = await self.performance_tracker.get_all_strategies_performance(days=7)
            
            if not stats:
                await update.message.reply_text("📊 Пока нет данных по стратегиям")
                return
            
            text = "<b>📊 Статистика по стратегиям (7 дней):</b>\n\n"
            
            for i, s in enumerate(stats[:10], 1):
                text += (
                    f"{i}. <b>{s['strategy_name']}</b>\n"
                    f"   Сигналов: {s['total_signals']} | "
                    f"WR: {s['win_rate']}% | "
                    f"PnL: {s['avg_pnl']:+.2f}%\n\n"
                )
            
            if len(stats) > 10:
                text += f"... и еще {len(stats) - 10} стратегий"
            
            await update.message.reply_text(text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error getting stats: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def cmd_ap_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать статистику Action Price (унифицирована с /performance)"""
        if not update.message:
            return
        
        if not self.ap_performance_tracker:
            await update.message.reply_text("⚠️ Action Price не активирован (требуется production режим)")
            return
        
        try:
            perf = await self.ap_performance_tracker.get_performance_stats(days=7)
            
            text = (
                f"📊 <b>Производительность Action Price (7 дней)</b>\n\n"
                f"📈 Всего сигналов: {perf['total_signals']}\n"
                f"✅ Закрыто: {perf['closed_signals']}\n"
                f"🔄 Активных: {perf['active_signals']}\n\n"
                f"🏆 Побед: {perf['wins']}\n"
                f"❌ Поражений: {perf['losses']}\n"
                f"📊 Win Rate: <b>{perf['win_rate']}%</b>\n\n"
                f"🎯 TP1 (0.5R): {perf.get('tp1_count', 0)}\n"
                f"🎯 TP2 (1.5R): {perf.get('tp2_count', 0)}\n"
                f"⚖️ Breakeven: {perf.get('breakeven_count', 0)}\n"
                f"⏱️ Time Stop: {perf.get('time_stop_count', 0)} | "
                f"PnL: {perf.get('time_stop_total_pnl', 0):+.2f}%\n\n"
                f"💰 Средний PnL: <b>{perf['avg_pnl']:+.2f}%</b>\n"
                f"💵 Общий PnL: <b>{perf['total_pnl']:+.2f}%</b>\n\n"
                f"🟢 Средняя победа: {perf['avg_win']:+.2f}%\n"
                f"🔴 Среднее поражение: {perf['avg_loss']:+.2f}%\n"
            )
            await update.message.reply_text(text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error getting AP stats: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def cmd_closed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать закрытые сигналы основных стратегий за 24 часа"""
        if not update.message:
            return
        
        try:
            hours = 24
            if context.args and context.args[0].isdigit():
                hours = int(context.args[0])
            
            start_time = datetime.now(pytz.UTC) - timedelta(hours=hours)
            
            session = self.db.get_session()
            try:
                closed_signals = session.query(Signal).filter(
                    Signal.closed_at >= start_time,
                    Signal.status.in_(['WIN', 'LOSS', 'TIME_STOP', 'BREAKEVEN'])
                ).order_by(Signal.closed_at.desc()).limit(20).all()
                
                if not closed_signals:
                    await update.message.reply_text(f"📊 Нет закрытых сигналов за последние {hours}ч")
                    return
                
                text = f"📊 <b>Закрытые сигналы ({hours}ч)</b>\n\n"
                count = 0
                
                for sig in closed_signals:
                    direction_emoji = "🟢" if sig.direction.lower() == "long" else "🔴"
                    
                    exit_type = getattr(sig, 'exit_type', 'N/A')
                    if sig.status == 'WIN':
                        status_emoji = "✅"
                        exit_label = exit_type if exit_type else "WIN"
                    elif sig.status == 'LOSS':
                        status_emoji = "❌"
                        exit_label = exit_type if exit_type else "LOSS"
                    elif sig.status == 'BREAKEVEN':
                        status_emoji = "⚖️"
                        exit_label = "BE"
                    else:
                        status_emoji = "⏱️"
                        exit_label = "TIME_STOP"
                    
                    pnl = sig.pnl_percent if sig.pnl_percent is not None else 0.0
                    pnl_str = f"{pnl:+.2f}%" if pnl != 0 else "0.00%"
                    
                    strategy_short = sig.strategy_name[:15]
                    
                    signal_text = (
                        f"{direction_emoji} <b>{sig.symbol}</b> {sig.direction.lower()}\n"
                        f"   {status_emoji} {exit_label} | {pnl_str} | {strategy_short}\n\n"
                    )
                    
                    # Проверка лимита Telegram (4096 символов)
                    footer = f"\n📈 Показано: {count} из {len(closed_signals)}"
                    if len(text + signal_text + footer) > self.TELEGRAM_MAX_LENGTH:
                        # Отправить текущее сообщение с footer
                        await update.message.reply_text(text + footer, parse_mode='HTML')
                        text = f"📊 <b>Закрытые сигналы ({hours}ч) - продолжение</b>\n\n"
                    
                    text += signal_text
                    count += 1
                
                # Финальное сообщение
                final_footer = f"\n📈 Всего показано: {len(closed_signals)}"
                if len(text + final_footer) > self.TELEGRAM_MAX_LENGTH:
                    await update.message.reply_text(text, parse_mode='HTML')
                    await update.message.reply_text(final_footer, parse_mode='HTML')
                else:
                    await update.message.reply_text(text + final_footer, parse_mode='HTML')
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error getting closed signals: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def cmd_closed_ap(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать закрытые сигналы Action Price за 24 часа"""
        if not update.message:
            return
        
        try:
            hours = 24
            if context.args and context.args[0].isdigit():
                hours = int(context.args[0])
            
            start_time = datetime.now(pytz.UTC) - timedelta(hours=hours)
            
            session = self.db.get_session()
            try:
                closed_signals = session.query(ActionPriceSignal).filter(
                    ActionPriceSignal.closed_at >= start_time,
                    ActionPriceSignal.status.in_(['WIN', 'LOSS', 'TIME_STOP', 'BREAKEVEN'])
                ).order_by(ActionPriceSignal.closed_at.desc()).all()
                
                if not closed_signals:
                    await update.message.reply_text(f"📊 Нет закрытых Action Price сигналов за последние {hours}ч")
                    return
                
                text = f"📊 <b>Action Price закрытые ({hours}ч)</b>\n\n"
                count = 0
                
                for sig in closed_signals:
                    direction_emoji = "🟢" if sig.direction.lower() == "long" else "🔴"
                    
                    exit_reason = sig.exit_reason if sig.exit_reason else 'N/A'
                    
                    if sig.status == 'WIN':
                        status_emoji = "✅"
                        if 'TAKE_PROFIT_2' in exit_reason:
                            exit_label = "TP2"
                        elif 'TAKE_PROFIT_1' in exit_reason:
                            exit_label = "TP1"
                        elif 'BREAKEVEN' in exit_reason:
                            exit_label = "BE"
                        else:
                            exit_label = "WIN"
                    elif sig.status == 'LOSS':
                        status_emoji = "❌"
                        exit_label = "SL"
                    elif sig.status == 'BREAKEVEN':
                        status_emoji = "⚖️"
                        exit_label = "BE"
                    else:
                        status_emoji = "⏱️"
                        exit_label = "TIME_STOP"
                    
                    pnl = sig.pnl_percent if sig.pnl_percent is not None else 0.0
                    pnl_str = f"{pnl:+.2f}%" if pnl != 0 else "0.00%"
                    
                    pattern = sig.pattern_type[:12]
                    
                    signal_text = (
                        f"{direction_emoji} <b>{sig.symbol}</b> {sig.direction.lower()}\n"
                        f"   {status_emoji} {exit_label} | {pnl_str} | {pattern}\n\n"
                    )
                    
                    # Проверка лимита Telegram (4096 символов)
                    footer = f"\n📈 Показано: {count} из {len(closed_signals)}"
                    if len(text + signal_text + footer) > self.TELEGRAM_MAX_LENGTH:
                        # Отправить текущее сообщение с footer
                        await update.message.reply_text(text + footer, parse_mode='HTML')
                        text = f"📊 <b>Action Price закрытые ({hours}ч) - продолжение</b>\n\n"
                    
                    text += signal_text
                    count += 1
                
                # Финальное сообщение
                final_footer = f"\n📈 Всего показано: {len(closed_signals)}"
                if len(text + final_footer) > self.TELEGRAM_MAX_LENGTH:
                    await update.message.reply_text(text, parse_mode='HTML')
                    await update.message.reply_text(final_footer, parse_mode='HTML')
                else:
                    await update.message.reply_text(text + final_footer, parse_mode='HTML')
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error getting closed AP signals: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def cmd_closed_ap_sl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать закрытые по Stop Loss сигналы Action Price за 24 часа"""
        if not update.message:
            return
        
        try:
            hours = 24
            if context.args and context.args[0].isdigit():
                hours = int(context.args[0])
            
            start_time = datetime.now(pytz.UTC) - timedelta(hours=hours)
            
            session = self.db.get_session()
            try:
                closed_signals = session.query(ActionPriceSignal).filter(
                    ActionPriceSignal.closed_at >= start_time,
                    ActionPriceSignal.status == 'LOSS'
                ).order_by(ActionPriceSignal.closed_at.desc()).all()
                
                if not closed_signals:
                    await update.message.reply_text(f"📊 Нет закрытых по SL Action Price сигналов за последние {hours}ч")
                    return
                
                text = f"🔴 <b>Action Price Stop Loss ({hours}ч)</b>\n\n"
                count = 0
                
                for sig in closed_signals:
                    direction_emoji = "🟢" if sig.direction.lower() == "long" else "🔴"
                    pnl = sig.pnl_percent if sig.pnl_percent is not None else 0.0
                    pnl_str = f"{pnl:+.2f}%" if pnl != 0 else "0.00%"
                    pattern = sig.pattern_type[:12]
                    
                    signal_text = (
                        f"{direction_emoji} <b>{sig.symbol}</b> {sig.direction.lower()}\n"
                        f"   ❌ SL | {pnl_str} | {pattern}\n\n"
                    )
                    
                    footer = f"\n📈 Показано: {count} из {len(closed_signals)}"
                    if len(text + signal_text + footer) > self.TELEGRAM_MAX_LENGTH:
                        await update.message.reply_text(text + footer, parse_mode='HTML')
                        text = f"🔴 <b>Action Price Stop Loss ({hours}ч) - продолжение</b>\n\n"
                    
                    text += signal_text
                    count += 1
                
                final_footer = f"\n📈 Всего показано: {len(closed_signals)}"
                if len(text + final_footer) > self.TELEGRAM_MAX_LENGTH:
                    await update.message.reply_text(text, parse_mode='HTML')
                    await update.message.reply_text(final_footer, parse_mode='HTML')
                else:
                    await update.message.reply_text(text + final_footer, parse_mode='HTML')
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error getting closed AP SL signals: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def cmd_closed_ap_tp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать закрытые по TP/BE сигналы Action Price за 24 часа"""
        if not update.message:
            return
        
        try:
            hours = 24
            if context.args and context.args[0].isdigit():
                hours = int(context.args[0])
            
            start_time = datetime.now(pytz.UTC) - timedelta(hours=hours)
            
            session = self.db.get_session()
            try:
                closed_signals = session.query(ActionPriceSignal).filter(
                    ActionPriceSignal.closed_at >= start_time,
                    ActionPriceSignal.status.in_(['WIN', 'BREAKEVEN'])
                ).order_by(ActionPriceSignal.closed_at.desc()).all()
                
                if not closed_signals:
                    await update.message.reply_text(f"📊 Нет закрытых по TP/BE Action Price сигналов за последние {hours}ч")
                    return
                
                text = f"🟢 <b>Action Price TP/BE ({hours}ч)</b>\n\n"
                count = 0
                
                for sig in closed_signals:
                    direction_emoji = "🟢" if sig.direction.lower() == "long" else "🔴"
                    
                    exit_reason = sig.exit_reason if sig.exit_reason else 'N/A'
                    
                    if sig.status == 'WIN':
                        status_emoji = "✅"
                        if 'TAKE_PROFIT_2' in exit_reason:
                            exit_label = "TP2"
                        elif 'TAKE_PROFIT_1' in exit_reason:
                            exit_label = "TP1"
                        elif 'BREAKEVEN' in exit_reason:
                            exit_label = "BE"
                        else:
                            exit_label = "WIN"
                    else:
                        status_emoji = "✅"
                        exit_label = "BE"
                    
                    pnl = sig.pnl_percent if sig.pnl_percent is not None else 0.0
                    pnl_str = f"{pnl:+.2f}%" if pnl != 0 else "0.00%"
                    pattern = sig.pattern_type[:12]
                    
                    signal_text = (
                        f"{direction_emoji} <b>{sig.symbol}</b> {sig.direction.lower()}\n"
                        f"   {status_emoji} {exit_label} | {pnl_str} | {pattern}\n\n"
                    )
                    
                    footer = f"\n📈 Показано: {count} из {len(closed_signals)}"
                    if len(text + signal_text + footer) > self.TELEGRAM_MAX_LENGTH:
                        await update.message.reply_text(text + footer, parse_mode='HTML')
                        text = f"🟢 <b>Action Price TP/BE ({hours}ч) - продолжение</b>\n\n"
                    
                    text += signal_text
                    count += 1
                
                final_footer = f"\n📈 Всего показано: {len(closed_signals)}"
                if len(text + final_footer) > self.TELEGRAM_MAX_LENGTH:
                    await update.message.reply_text(text, parse_mode='HTML')
                    await update.message.reply_text(final_footer, parse_mode='HTML')
                else:
                    await update.message.reply_text(text + final_footer, parse_mode='HTML')
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error getting closed AP TP signals: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def cmd_validate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверить корректность работы стратегий"""
        if not update.message:
            return
        
        if not self.strategy_validator:
            await update.message.reply_text("⚠️ Валидатор стратегий не запущен")
            return
        
        await update.message.reply_text("🔍 Запускаю валидацию стратегий...\n\nЭто займет 10-20 секунд")
        
        try:
            # Можно передать символ как аргумент: /validate BTCUSDT
            symbol = context.args[0] if context.args else 'BTCUSDT'
            
            results = self.strategy_validator.validate_all_strategies(symbol)
            
            # Форматирование результатов
            passed = results['strategies_passed']
            failed = results['strategies_failed']
            total = results['strategies_tested']
            
            text = (
                f"✅ <b>Результаты валидации ({symbol})</b>\n\n"
                f"📊 Всего стратегий: {total}\n"
                f"✅ Прошли проверку: {passed}\n"
                f"❌ Провалили проверку: {failed}\n\n"
            )
            
            # Показываем проблемные стратегии
            for detail in results['details']:
                if detail['status'] == 'FAIL':
                    text += f"\n❌ <b>{detail['strategy']}</b> ({detail['timeframe']})\n"
                    for issue in detail.get('issues', [])[:2]:  # Первые 2 проблемы
                        text += f"   • {issue}\n"
                elif detail.get('warnings'):
                    text += f"\n⚡ <b>{detail['strategy']}</b> ({detail['timeframe']})\n"
                    text += f"   • {detail['warnings'][0]}\n"
            
            # Успешные стратегии (только count)
            passed_list = [d['strategy'] for d in results['details'] if d['status'] == 'PASS']
            if passed_list:
                text += f"\n✅ <b>Успешно:</b> {len(passed_list)} стратегий"
            
            await update.message.reply_text(text, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Error validating strategies: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    def set_validator(self, validator):
        """Установить валидатор стратегий для доступа из команд"""
        self.strategy_validator = validator
    
    def set_performance_tracker(self, tracker):
        """Установить трекер производительности для доступа из команд"""
        self.performance_tracker = tracker
    
    def set_ap_performance_tracker(self, tracker):
        """Установить Action Price трекер для доступа из команд"""
        self.ap_performance_tracker = tracker
    
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
                f"🤖 <b>Бот запущен!</b>\n\n"
                f"📊 <b>В работе:</b> {pairs_count} пар\n"
                f"🎯 <b>Активных стратегий:</b> {strategies_count}\n"
                f"⚙️ <b>Режим:</b> {mode}\n\n"
                f"Используйте /help для списка команд"
            )
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            self.startup_message_sent = True
            logger.info("Startup message sent to Telegram")
        except Exception as e:
            logger.error(f"Error sending startup message: {e}")
    
    async def send_data_integrity_alert(self, symbol: str, issue_type: str, details: str):
        """Send data integrity alert to Telegram
        
        Args:
            symbol: Symbol with data issues
            issue_type: Type of issue ('incomplete', 'gaps', 'corruption')
            details: Detailed description of the issue
        """
        if not self.bot or not self.chat_id:
            return
        
        try:
            emoji_map = {
                'incomplete': '⚠️',
                'gaps': '🔴',
                'corruption': '💥'
            }
            emoji = emoji_map.get(issue_type, '⚠️')
            
            message = (
                f"{emoji} <b>Data Integrity Alert</b>\n\n"
                f"📊 Symbol: <code>{symbol}</code>\n"
                f"🔍 Issue: {issue_type}\n"
                f"📝 Details: {details}\n\n"
                f"⚠️ Trading on this symbol may be affected"
            )
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"Data integrity alert sent for {symbol}")
        except Exception as e:
            logger.error(f"Error sending data integrity alert: {e}")
    
    async def send_signal(self, signal_data: dict):
        if not self.bot or not self.chat_id:
            return None
        
        try:
            message = self._format_signal(signal_data)
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            return msg.message_id if msg else None
        except Exception as e:
            logger.error(f"Error sending signal: {e}")
            return None
    
    def _format_signal(self, signal_data: dict) -> str:
        direction_emoji = "🟢" if signal_data['direction'] == 'LONG' else "🔴"
        entry_type = signal_data.get('entry_type', 'MARKET')
        symbol = signal_data['symbol']
        
        # Определить эмодзи для entry_type
        if 'LIMIT' in entry_type:
            entry_emoji = "⏳" if 'pending' in entry_type.lower() else "✅"
        elif 'FILLED' in entry_type:
            entry_emoji = "✅"
        else:
            entry_emoji = "⚡"
        
        message = (
            f"{direction_emoji} <b>{signal_data['strategy_name']}</b>\n\n"
            f"📊 Символ: <code>{symbol}</code>\n"
            f"📈 Направление: <b>{signal_data['direction']}</b>\n"
            f"{entry_emoji} Тип входа: <code>{entry_type}</code>\n"
        )
        
        # Форматировать цены с правильной точностью
        def format_price(price):
            if self.binance_client:
                return self.binance_client.format_price(symbol, price)
            return f"{price:.8f}".rstrip('0').rstrip('.')
        
        # Для LIMIT pending показать целевую и текущую цену
        if 'pending' in entry_type.lower() and 'current_price' in signal_data:
            message += (
                f"🎯 Целевая цена: <code>{format_price(signal_data['entry_price'])}</code>\n"
                f"💰 Текущая цена: <code>{format_price(signal_data['current_price'])}</code>\n"
            )
        else:
            message += f"💰 Вход: <code>{format_price(signal_data['entry_price'])}</code>\n"
        
        # Форматировать SL и TP
        stop_loss = format_price(signal_data['stop_loss'])
        tp1 = format_price(signal_data['tp1']) if signal_data.get('tp1') else 'N/A'
        tp2 = format_price(signal_data['tp2']) if signal_data.get('tp2') else 'N/A'
        
        message += (
            f"🛑 Стоп: <code>{stop_loss}</code>\n"
            f"🎯 TP1: <code>{tp1}</code>\n"
            f"🎯 TP2: <code>{tp2}</code>\n\n"
            f"⭐️ Скор: <code>{signal_data['score']:.1f}</code>\n"
            f"🔄 Режим: <code>{signal_data['regime']}</code>\n"
        )
        
        return message
    
    async def cmd_regime_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Статистика по режимам рынка"""
        if not update.message:
            return
        
        if not self.performance_tracker:
            await update.message.reply_text("⚠️ Трекер производительности не запущен")
            return
        
        try:
            from src.database.models import Signal
            from datetime import timedelta
            import pytz
            from datetime import datetime
            
            session = self.performance_tracker.db.get_session()
            start_date = datetime.now(pytz.UTC) - timedelta(days=7)
            
            signals = session.query(Signal).filter(
                Signal.created_at >= start_date,
                Signal.status.in_(['WIN', 'LOSS', 'TIME_STOP'])
            ).all()
            
            if not signals:
                await update.message.reply_text("📊 Пока нет данных по режимам рынка")
                session.close()
                return
            
            regime_data = {}
            for sig in signals:
                regime = sig.market_regime or "UNKNOWN"
                if regime not in regime_data:
                    regime_data[regime] = {'total': 0, 'wins': 0, 'pnl': []}
                
                regime_data[regime]['total'] += 1
                if sig.status == 'WIN':
                    regime_data[regime]['wins'] += 1
                if sig.pnl_percent:
                    regime_data[regime]['pnl'].append(sig.pnl_percent)
            
            session.close()
            
            text = "📊 <b>Market Regime Performance (7d)</b>\n\n"
            
            regime_emojis = {
                'TRENDING': '📈',
                'RANGING': '↔️',
                'VOLATILE': '⚡',
                'CHOPPY': '🌊',
                'UNDECIDED': '❓'
            }
            
            for regime in sorted(regime_data.keys()):
                data = regime_data[regime]
                win_rate = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
                avg_pnl = sum(data['pnl']) / len(data['pnl']) if data['pnl'] else 0
                
                emoji = regime_emojis.get(regime, '📊')
                text += (
                    f"{emoji} <b>{regime}</b>\n"
                    f"├─ Signals: {data['total']}\n"
                    f"├─ Win Rate: {win_rate:.1f}%\n"
                    f"└─ Avg PnL: {avg_pnl:+.2f}%\n\n"
                )
            
            await update.message.reply_text(text, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Error getting regime stats: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def cmd_confluence_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Статистика по confluence сигналов"""
        if not update.message:
            return
        
        if not self.performance_tracker:
            await update.message.reply_text("⚠️ Трекер производительности не запущен")
            return
        
        try:
            from src.database.models import Signal
            from datetime import timedelta
            import pytz
            from datetime import datetime
            
            session = self.performance_tracker.db.get_session()
            start_date = datetime.now(pytz.UTC) - timedelta(days=7)
            
            signals = session.query(Signal).filter(
                Signal.created_at >= start_date,
                Signal.status.in_(['WIN', 'LOSS', 'TIME_STOP'])
            ).all()
            
            if not signals:
                await update.message.reply_text("📊 Пока нет данных по confluence")
                session.close()
                return
            
            conf_data = {}
            for sig in signals:
                count = sig.confluence_count or 1
                if count not in conf_data:
                    conf_data[count] = {'total': 0, 'wins': 0, 'pnl': []}
                
                conf_data[count]['total'] += 1
                if sig.status == 'WIN':
                    conf_data[count]['wins'] += 1
                if sig.pnl_percent:
                    conf_data[count]['pnl'].append(sig.pnl_percent)
            
            session.close()
            
            text = "✨ <b>Signal Confluence Performance (7d)</b>\n\n"
            
            for count in sorted(conf_data.keys()):
                data = conf_data[count]
                win_rate = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
                avg_pnl = sum(data['pnl']) / len(data['pnl']) if data['pnl'] else 0
                
                if count == 1:
                    label = "Single Strategy"
                    emoji = "📌"
                elif count == 2:
                    label = "Double Confluence"
                    emoji = "🔥"
                elif count == 3:
                    label = "Triple Confluence"
                    emoji = "⭐"
                else:
                    label = f"{count}+ Confluence"
                    emoji = "🚀"
                
                text += (
                    f"{emoji} <b>{label}</b>\n"
                    f"├─ Signals: {data['total']}\n"
                    f"├─ Win Rate: {win_rate:.1f}%\n"
                    f"└─ Avg PnL: {avg_pnl:+.2f}%\n\n"
                )
            
            if len(conf_data) > 1:
                single_wr = (conf_data[1]['wins'] / conf_data[1]['total'] * 100) if 1 in conf_data and conf_data[1]['total'] > 0 else 0
                multi_wins = sum(data['wins'] for c, data in conf_data.items() if c > 1)
                multi_total = sum(data['total'] for c, data in conf_data.items() if c > 1)
                multi_wr = (multi_wins / multi_total * 100) if multi_total > 0 else 0
                
                improvement = multi_wr - single_wr
                text += (
                    f"💡 <b>Insights:</b>\n"
                    f"Confluence improves Win Rate by <b>{improvement:+.1f}%</b>\n"
                )
            
            await update.message.reply_text(text, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Error getting confluence stats: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
