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
        self.performance_tracker = None
        self.strategy_validator = None
    
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
        self.app.add_handler(CommandHandler("performance", self.cmd_performance))
        self.app.add_handler(CommandHandler("stats", self.cmd_stats))
        self.app.add_handler(CommandHandler("validate", self.cmd_validate))
        
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
            "/performance - Производительность (7 дней)\n"
            "/stats - Статистика по стратегиям\n"
            "/validate - Проверка стратегий\n"
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
            "/performance - Win rate, PnL за 7 дней\n"
            "/stats - Детали по стратегиям\n"
            "/validate - Проверка корректности стратегий\n"
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
                f"📊 *Производительность (7 дней)*\n\n"
                f"📈 Всего сигналов: {perf['total_signals']}\n"
                f"✅ Закрыто: {perf['closed_signals']}\n"
                f"🔄 Активных: {perf['active_signals']}\n\n"
                f"🏆 Побед: {perf['wins']}\n"
                f"❌ Поражений: {perf['losses']}\n"
                f"📊 Win Rate: *{perf['win_rate']}%*\n\n"
                f"💰 Средний PnL: *{perf['avg_pnl']:+.2f}%*\n"
                f"💵 Общий PnL: *{perf['total_pnl']:+.2f}%*\n\n"
                f"🟢 Средняя победа: {perf['avg_win']:+.2f}%\n"
                f"🔴 Среднее поражение: {perf['avg_loss']:+.2f}%\n"
            )
            await update.message.reply_text(text, parse_mode='Markdown')
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
            
            text = "*📊 Статистика по стратегиям (7 дней):*\n\n"
            
            for i, s in enumerate(stats[:10], 1):
                text += (
                    f"{i}. *{s['strategy_name']}*\n"
                    f"   Сигналов: {s['total_signals']} | "
                    f"WR: {s['win_rate']}% | "
                    f"PnL: {s['avg_pnl']:+.2f}%\n\n"
                )
            
            if len(stats) > 10:
                text += f"... и еще {len(stats) - 10} стратегий"
            
            await update.message.reply_text(text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error getting stats: {e}", exc_info=True)
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
                f"✅ *Результаты валидации ({symbol})*\n\n"
                f"📊 Всего стратегий: {total}\n"
                f"✅ Прошли проверку: {passed}\n"
                f"❌ Провалили проверку: {failed}\n\n"
            )
            
            # Показываем проблемные стратегии
            for detail in results['details']:
                if detail['status'] == 'FAIL':
                    text += f"\n❌ *{detail['strategy']}* ({detail['timeframe']})\n"
                    for issue in detail.get('issues', [])[:2]:  # Первые 2 проблемы
                        text += f"   • {issue}\n"
                elif detail.get('warnings'):
                    text += f"\n⚡ *{detail['strategy']}* ({detail['timeframe']})\n"
                    text += f"   • {detail['warnings'][0]}\n"
            
            # Успешные стратегии (только count)
            passed_list = [d['strategy'] for d in results['details'] if d['status'] == 'PASS']
            if passed_list:
                text += f"\n✅ *Успешно:* {len(passed_list)} стратегий"
            
            await update.message.reply_text(text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error validating strategies: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    def set_validator(self, validator):
        """Установить валидатор стратегий для доступа из команд"""
        self.strategy_validator = validator
    
    def set_performance_tracker(self, tracker):
        """Установить трекер производительности для доступа из команд"""
        self.performance_tracker = tracker
    
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
                f"{emoji} *Data Integrity Alert*\n\n"
                f"📊 Symbol: `{symbol}`\n"
                f"🔍 Issue: {issue_type}\n"
                f"📝 Details: {details}\n\n"
                f"⚠️ Trading on this symbol may be affected"
            )
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
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
                parse_mode='Markdown'
            )
            return msg.message_id if msg else None
        except Exception as e:
            logger.error(f"Error sending signal: {e}")
            return None
    
    def _format_signal(self, signal_data: dict) -> str:
        direction_emoji = "🟢" if signal_data['direction'] == 'LONG' else "🔴"
        entry_type = signal_data.get('entry_type', 'MARKET')
        
        # Определить эмодзи для entry_type
        if 'LIMIT' in entry_type:
            entry_emoji = "⏳" if 'pending' in entry_type.lower() else "✅"
        elif 'FILLED' in entry_type:
            entry_emoji = "✅"
        else:
            entry_emoji = "⚡"
        
        message = (
            f"{direction_emoji} *{signal_data['strategy_name']}*\n\n"
            f"📊 Символ: `{signal_data['symbol']}`\n"
            f"📈 Направление: *{signal_data['direction']}*\n"
            f"{entry_emoji} Тип входа: `{entry_type}`\n"
        )
        
        # Для LIMIT pending показать целевую и текущую цену
        if 'pending' in entry_type.lower() and 'current_price' in signal_data:
            message += (
                f"🎯 Целевая цена: `{signal_data['entry_price']:.4f}`\n"
                f"💰 Текущая цена: `{signal_data['current_price']:.4f}`\n"
            )
        else:
            message += f"💰 Вход: `{signal_data['entry_price']:.4f}`\n"
        
        message += (
            f"🛑 Стоп: `{signal_data['stop_loss']:.4f}`\n"
            f"🎯 TP1: `{signal_data.get('tp1', 'N/A')}`\n"
            f"🎯 TP2: `{signal_data.get('tp2', 'N/A')}`\n\n"
            f"⭐️ Скор: `{signal_data['score']:.1f}`\n"
            f"🔄 Режим: `{signal_data['regime']}`\n"
        )
        
        return message
