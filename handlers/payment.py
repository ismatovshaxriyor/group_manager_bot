"""Payment approval / rejection handler for admin inline buttons."""

import datetime
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import ADMIN_IDS
from database import Payment, Subscription, User, Channel

logger = logging.getLogger(__name__)


async def handle_payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process admin's approve/reject button press."""
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        await query.answer("⛔ Sizda ruxsat yo'q!", show_alert=True)
        return

    data = query.data  # approve_<id> or reject_<id>
    action, payment_id = data.split("_", 1)
    payment_id = int(payment_id)

    try:
        payment = Payment.get_by_id(payment_id)
    except Payment.DoesNotExist:
        await query.edit_message_caption(
            caption="❌ To'lov topilmadi.", parse_mode="HTML"
        )
        return

    if payment.status != "pending":
        await query.answer(
            f"Bu to'lov allaqachon {payment.status} qilingan.", show_alert=True
        )
        return

    user = payment.user

    if action == "approve":
        # Update payment
        payment.status = "approved"
        payment.approved_by = query.from_user.id
        payment.approved_at = datetime.datetime.now()
        payment.save()

        # Create subscription (1 month)
        now = datetime.datetime.now()
        end = now + datetime.timedelta(days=30)
        Subscription.create(
            user=user,
            payment=payment,
            start_date=now,
            end_date=end,
            is_active=True,
            warning_sent=False,
        )

        # Update admin message
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n✅ <b>TASDIQLANDI</b>",
            parse_mode="HTML",
        )

        # Build inline buttons for all active channels/groups
        channels = Channel.select().where(Channel.is_active == True)

        if not channels:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    "🎉 <b>To'lovingiz tasdiqlandi!</b>\n\n"
                    "✅ Obunangiz 30 kunga faollashtirildi.\n\n"
                    "⚠️ Hozircha guruh/kanal qo'shilmagan. Admin tez orada qo'shadi."
                ),
                parse_mode="HTML",
            )
            return

        try:
            buttons = []
            for ch in channels:
                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=ch.chat_id,
                    creates_join_request=True,
                    name=f"user_{user.telegram_id}",
                )
                title = ch.title or f"Guruh #{ch.id}"
                buttons.append(
                    [InlineKeyboardButton(f"📢 {title}", url=invite_link.invite_link)]
                )

            keyboard = InlineKeyboardMarkup(buttons)

            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    "🎉 <b>To'lovingiz tasdiqlandi!</b>\n\n"
                    "✅ Obunangiz 30 kunga faollashtirildi.\n\n"
                    "Quyidagi tugmalarni bosib guruh/kanallarga qo'shiling:"
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Failed to send invite to user {user.telegram_id}: {e}")
            for admin_id in ADMIN_IDS:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ Userga ({user.telegram_id}) havola yuborishda xato: {e}",
                )

    elif action == "reject":
        payment.status = "rejected"
        payment.approved_at = datetime.datetime.now()
        payment.save()

        # Update admin message
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n❌ <b>RAD ETILDI</b>",
            parse_mode="HTML",
        )

        # Inform user
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    "❌ <b>To'lovingiz rad etildi.</b>\n\n"
                    "Iltimos, to'lov chekini qayta yuboring yoki admin bilan bog'laning.\n"
                    "Qaytadan boshlash uchun /start bosing."
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user.telegram_id}: {e}")


def get_payment_handler():
    """Return the callback query handler for payment decisions."""
    return CallbackQueryHandler(
        handle_payment_decision, pattern=r"^(approve|reject)_\d+$"
    )
