import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_IDS = set(
    int(x) for x in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if x.strip()
)

_app: Application = None


def _allowed(update: Update) -> bool:
    return update.effective_chat.id in ALLOWED_CHAT_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not _allowed(update):
        await update.message.reply_text(f"Your chat_id: {chat_id}")
        return
    await update.message.reply_text("Plant Monitor is running.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return

    from database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM telemetry_raw ORDER BY timestamp DESC LIMIT 1")
        )
        row = result.mappings().fetchone()

    if not row:
        await update.message.reply_text("No data yet.")
        return

    hum = f"{row['humidity']:.1f}%" if row['humidity'] is not None else "n/a"
    await update.message.reply_text(
        f"plant-01\n"
        f"Temperature: {row['temperature']:.1f}°C\n"
        f"Humidity: {hum}\n"
        f"Soil moisture: {row['soil_moisture']}%"
    )


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return

    from database import AsyncSessionLocal
    from models import AlertState
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AlertState).where(AlertState.is_firing == True)
        )
        alerts = result.scalars().all()

    if not alerts:
        await update.message.reply_text("No active alerts.")
        return

    lines = [f"[!] {a.alert_type} — {a.device_id}" for a in alerts]
    await update.message.reply_text("\n".join(lines))


async def send_notification(message: str):
    if _app is None or not ALLOWED_CHAT_IDS:
        return
    for chat_id in ALLOWED_CHAT_IDS:
        try:
            await _app.bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            logger.error(f"[TELEGRAM] Send failed to {chat_id}: {e}")


async def start_bot():
    global _app
    if not TELEGRAM_TOKEN:
        logger.warning("[TELEGRAM] TELEGRAM_BOT_TOKEN not set, bot disabled.")
        return

    _app = Application.builder().token(TELEGRAM_TOKEN).build()
    _app.add_handler(CommandHandler("start",  cmd_start))
    _app.add_handler(CommandHandler("status", cmd_status))
    _app.add_handler(CommandHandler("alerts", cmd_alerts))

    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling()
    logger.info("[TELEGRAM] Bot started.")


async def stop_bot():
    global _app
    if _app:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        logger.info("[TELEGRAM] Bot stopped.")
