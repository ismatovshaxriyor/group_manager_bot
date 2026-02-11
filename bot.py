"""Telegram Subscription Bot — main entry point."""

import logging
import datetime
import traceback
import html

from telegram import Update
from telegram.ext import Application, ContextTypes

from config import BOT_TOKEN
from database import create_tables
from handlers.registration import get_registration_handler
from handlers.payment import get_payment_handler
from handlers.admin import get_admin_handlers
from handlers.membership import get_membership_handler
from scheduler import check_subscriptions

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    """Start the bot."""
    # Create database tables
    create_tables()
    logger.info("Database tables created.")

    # Build application
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Register handlers ──
    # Registration conversation (must be first so /start works)
    app.add_handler(get_registration_handler(), group=0)

    # Admin handlers (conversation for add_card/add_channel + callbacks)
    for handler in get_admin_handlers():
        app.add_handler(handler, group=1)

    # Payment approval / rejection callbacks
    app.add_handler(get_payment_handler(), group=2)

    # Join request handler
    app.add_handler(get_membership_handler(), group=3)

    # ── Schedule daily subscription check ──
    job_queue = app.job_queue
    # Run every day at 09:00 (UTC+5)
    job_queue.run_daily(
        check_subscriptions,
        time=datetime.time(hour=4, minute=0, second=0),  # 09:00 UTC+5 = 04:00 UTC
        name="subscription_check",
    )
    # Also run once on startup (after 10 seconds)
    job_queue.run_once(check_subscriptions, when=10, name="startup_check")

    # ── Error handler ──
    app.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    app.run_polling(drop_pending_updates=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and notify admin."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"⚠️ <b>Xatolik yuz berdi!</b>\n\n"
        f"<pre>{html.escape(tb_string[-3000:])}</pre>"
    )

    try:
        from config import ADMIN_ID
        await context.bot.send_message(
            chat_id=ADMIN_ID, text=message, parse_mode="HTML"
        )
    except Exception:
        logger.error("Failed to send error message to admin.")


if __name__ == "__main__":
    main()
