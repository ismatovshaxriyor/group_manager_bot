"""Handle channel/group join requests — auto-approve users with active subscriptions."""

import logging

from telegram import Update
from telegram.ext import ChatJoinRequestHandler, ContextTypes

from database import User, Subscription

logger = logging.getLogger(__name__)


async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve or decline join requests based on subscription status."""
    join_request = update.chat_join_request
    telegram_id = join_request.from_user.id

    try:
        user = User.get(User.telegram_id == telegram_id)
        active_sub = (
            Subscription.select()
            .where(
                (Subscription.user == user) & (Subscription.is_active == True)
            )
            .first()
        )

        if active_sub:
            await join_request.approve()
            logger.info(f"Approved join request for user {telegram_id}")
        else:
            await join_request.decline()
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        "❌ Obunangiz faol emas.\n\n"
                        "To'lov qilish uchun /start bosing."
                    ),
                )
            except Exception:
                pass
            logger.info(f"Declined join request for user {telegram_id} — no active subscription")

    except User.DoesNotExist:
        await join_request.decline()
        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=(
                    "❌ Siz ro'yxatdan o'tmagansiz.\n\n"
                    "Ro'yxatdan o'tish uchun /start bosing."
                ),
            )
        except Exception:
            pass
        logger.info(f"Declined join request for unregistered user {telegram_id}")


def get_membership_handler():
    """Return the join request handler."""
    return ChatJoinRequestHandler(handle_join_request)
