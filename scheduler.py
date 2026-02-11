"""Scheduler — checks subscription expiry daily, sends warnings, and removes expired users."""

import datetime
import logging

from database import Subscription, Channel

logger = logging.getLogger(__name__)


async def check_subscriptions(context):
    """Run daily: warn expiring users and kick expired ones."""
    now = datetime.datetime.now()

    # ── 1. Send warnings (3 days before expiry) ──
    warn_threshold = now + datetime.timedelta(days=3)
    expiring = (
        Subscription.select()
        .where(
            (Subscription.is_active == True)
            & (Subscription.warning_sent == False)
            & (Subscription.end_date <= warn_threshold)
            & (Subscription.end_date > now)
        )
    )

    for sub in expiring:
        user = sub.user
        days_left = (sub.end_date - now).days
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"⚠️ <b>Diqqat!</b>\n\n"
                    f"Obunangiz tugashiga <b>{days_left} kun</b> qoldi.\n\n"
                    f"To'lovni uzaytirish uchun /start bosing."
                ),
                parse_mode="HTML",
            )
            sub.warning_sent = True
            sub.save()
            logger.info(f"Warning sent to user {user.telegram_id}, {days_left} days left")
        except Exception as e:
            logger.error(f"Failed to warn user {user.telegram_id}: {e}")

    # ── 2. Remove expired users ──
    expired = (
        Subscription.select()
        .where(
            (Subscription.is_active == True) & (Subscription.end_date <= now)
        )
    )

    channels = Channel.select().where(Channel.is_active == True)

    for sub in expired:
        user = sub.user
        sub.is_active = False
        sub.save()

        # Kick from all active channels
        for ch in channels:
            try:
                await context.bot.ban_chat_member(
                    chat_id=ch.chat_id,
                    user_id=user.telegram_id,
                )
                # Immediately unban so they can rejoin later after payment
                await context.bot.unban_chat_member(
                    chat_id=ch.chat_id,
                    user_id=user.telegram_id,
                )
                logger.info(
                    f"Removed user {user.telegram_id} from channel {ch.chat_id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to remove user {user.telegram_id} from {ch.chat_id}: {e}"
                )

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    "❌ <b>Obunangiz tugadi!</b>\n\n"
                    "Siz guruh/kanallardan chiqarildingiz.\n\n"
                    "Qayta obuna bo'lish uchun /start bosing."
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to notify expired user {user.telegram_id}: {e}")

    logger.info(
        f"Subscription check done: {len(list(expiring))} warned, "
        f"{len(list(expired))} expired"
    )
