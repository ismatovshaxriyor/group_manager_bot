"""Admin panel — /admin command with statistics, card/channel management, and payments."""

import datetime
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import ADMIN_ID, MONTHLY_PRICE
from database import User, Payment, Subscription, Card, Channel

logger = logging.getLogger(__name__)

# Conversation states for admin flows
(
    WAIT_CARD_NUMBER,
    WAIT_CARD_HOLDER,
    WAIT_CHANNEL_ID,
) = range(100, 103)


# ─── Main admin menu ─────────────────────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel with inline buttons."""
    if update.effective_user.id != ADMIN_ID:
        return

    await _show_admin_menu(update.message.reply_text)


async def _show_admin_menu(reply_func, **kwargs):
    """Render the admin menu keyboard."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
            [InlineKeyboardButton("💳 Kartalar", callback_data="admin_cards")],
            [InlineKeyboardButton("📺 Kanallar / Guruhlar", callback_data="admin_channels")],
            [InlineKeyboardButton("💰 So'nggi to'lovlar", callback_data="admin_payments")],
        ]
    )
    await reply_func(
        "⚙️ <b>Admin panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=keyboard,
        **kwargs,
    )


# ─── Callback handler ────────────────────────────────────────────

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel inline button presses."""
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        return

    await query.answer()

    data = query.data

    # ── Statistics ──
    if data == "admin_stats":
        total_users = User.select().count()
        active_subs = Subscription.select().where(Subscription.is_active == True).count()
        total_payments = Payment.select().count()
        approved = Payment.select().where(Payment.status == "approved").count()
        pending = Payment.select().where(Payment.status == "pending").count()
        rejected = Payment.select().where(Payment.status == "rejected").count()
        price_fmt = f"{MONTHLY_PRICE:,}".replace(",", " ")

        text = (
            f"📊 <b>Statistika</b>\n\n"
            f"👥 Jami foydalanuvchilar: <b>{total_users}</b>\n"
            f"✅ Aktiv obunalar: <b>{active_subs}</b>\n\n"
            f"💰 <b>To'lovlar:</b>\n"
            f"  📋 Jami: {total_payments}\n"
            f"  ✅ Tasdiqlangan: {approved}\n"
            f"  ⏳ Kutilmoqda: {pending}\n"
            f"  ❌ Rad etilgan: {rejected}\n\n"
            f"💵 Oylik narx: {price_fmt} so'm"
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Cards list ──
    elif data == "admin_cards":
        await _show_cards(query)

    # ── Channels list ──
    elif data == "admin_channels":
        await _show_channels(query)

    # ── Recent payments ──
    elif data == "admin_payments" or data.startswith("admin_payments_page_"):
        if data == "admin_payments":
            page = 0
        else:
            page = int(data.split("_")[-1])

        # If returning from photo detail, delete photo and send new text
        is_photo = query.message.photo if query.message else False
        await _show_payments_page(query, page, from_photo=bool(is_photo))

    # ── Payment detail ──
    elif data.startswith("admin_pay_detail_"):
        parts = data.split("_")
        payment_id = int(parts[3])
        from_page = int(parts[4]) if len(parts) > 4 else 0
        await _show_payment_detail(query, context, payment_id, from_page)

    # ── Back to menu ──
    elif data == "admin_back":
        try:
            await _show_admin_menu(query.edit_message_text)
        except BadRequest:
            pass

    # ── Add card ──
    elif data == "admin_add_card":
        await query.edit_message_text(
            "💳 Yangi karta raqamini kiriting (masalan: 8600 1234 5678 9012):"
        )
        context.user_data["admin_flow"] = "add_card"
        return WAIT_CARD_NUMBER

    # ── Delete card ──
    elif data.startswith("admin_del_card_"):
        card_id = int(data.split("_")[-1])
        try:
            card = Card.get_by_id(card_id)
            card.delete_instance()
            await query.answer("🗑 Karta o'chirildi!", show_alert=True)
        except Card.DoesNotExist:
            await query.answer("Karta topilmadi.", show_alert=True)
        await _show_cards(query)

    # ── Add channel ──
    elif data == "admin_add_channel":
        await query.edit_message_text(
            "📺 Kanal/guruh ID sini kiriting (masalan: -1001234567890):\n\n"
            "💡 Bot o'sha kanal/guruhda admin bo'lishi kerak."
        )
        context.user_data["admin_flow"] = "add_channel"
        return WAIT_CHANNEL_ID

    # ── Delete channel ──
    elif data.startswith("admin_del_ch_"):
        ch_id = int(data.split("_")[-1])
        try:
            ch = Channel.get_by_id(ch_id)
            ch.delete_instance()
            await query.answer("🗑 Kanal o'chirildi!", show_alert=True)
        except Channel.DoesNotExist:
            await query.answer("Kanal topilmadi.", show_alert=True)
        await _show_channels(query)


# ─── Card management helpers ─────────────────────────────────────

async def _show_cards(query):
    """Show the list of active cards with delete buttons."""
    cards = Card.select().where(Card.is_active == True)
    text = "💳 <b>Kartalar</b>\n\n"

    buttons = []
    if cards:
        for c in cards:
            text += f"• <code>{c.card_number}</code> — {c.card_holder}\n"
            buttons.append(
                [InlineKeyboardButton(f"🗑 {c.card_number}", callback_data=f"admin_del_card_{c.id}")]
            )
    else:
        text += "<i>Hali karta qo'shilmagan</i>\n"

    buttons.append([InlineKeyboardButton("➕ Karta qo'shish", callback_data="admin_add_card")])
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


async def _show_channels(query):
    """Show the list of active channels with delete buttons."""
    channels = Channel.select().where(Channel.is_active == True)
    text = "📺 <b>Kanallar / Guruhlar</b>\n\n"

    buttons = []
    if channels:
        for ch in channels:
            text += f"• {ch.title} (<code>{ch.chat_id}</code>)\n"
            buttons.append(
                [InlineKeyboardButton(f"🗑 {ch.title}", callback_data=f"admin_del_ch_{ch.id}")]
            )
    else:
        text += "<i>Hali kanal/guruh qo'shilmagan</i>\n"

    buttons.append([InlineKeyboardButton("➕ Kanal qo'shish", callback_data="admin_add_channel")])
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


# ─── Payments pagination ─────────────────────────────────────────

PAGE_SIZE = 20


async def _show_payments_page(query, page: int, from_photo: bool = False):
    """Show a paginated list of payments as inline buttons."""
    total = Payment.select().count()

    if total == 0:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
        )
        if from_photo:
            try:
                await query.message.delete()
            except Exception:
                pass
            await query.from_user.get_bot().send_message(
                chat_id=query.from_user.id, text="💰 Hali to'lovlar yo'q.", reply_markup=keyboard
            )
        else:
            await query.edit_message_text("💰 Hali to'lovlar yo'q.", reply_markup=keyboard)
        return

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    payments = (
        Payment.select(Payment, User)
        .join(User)
        .order_by(Payment.created_at.desc())
        .offset(page * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )

    text = f"💰 <b>To'lovlar</b> (sahifa {page + 1}/{total_pages}, jami: {total})\n\n"
    text += "To'lovni ko'rish uchun ustiga bosing:"

    emoji_map = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    buttons = []

    for p in payments:
        e = emoji_map.get(p.status, "❓")
        price = f"{p.amount:,}".replace(",", " ")
        label = f"{e} #{p.id} | {p.user.first_name} {p.user.last_name} | {price} | {p.created_at:%d.%m}"
        buttons.append(
            [InlineKeyboardButton(label, callback_data=f"admin_pay_detail_{p.id}_{page}")]
        )

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton("◀️ Oldingi", callback_data=f"admin_payments_page_{page - 1}")
        )
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton("Keyingi ▶️", callback_data=f"admin_payments_page_{page + 1}")
        )

    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])

    markup = InlineKeyboardMarkup(buttons)

    if from_photo:
        try:
            await query.message.delete()
        except Exception:
            pass
        from telegram.ext import ContextTypes
        await query.get_bot().send_message(
            chat_id=query.from_user.id, text=text, parse_mode="HTML", reply_markup=markup
        )
    else:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)


async def _show_payment_detail(query, context, payment_id: int, from_page: int):
    """Show full payment details with receipt photo."""
    try:
        payment = Payment.select(Payment, User).join(User).where(Payment.id == payment_id).get()
    except Payment.DoesNotExist:
        await query.answer("To'lov topilmadi.", show_alert=True)
        return

    user = payment.user
    status_map = {"pending": "⏳ Kutilmoqda", "approved": "✅ Tasdiqlangan", "rejected": "❌ Rad etilgan"}
    price = f"{payment.amount:,}".replace(",", " ")

    text = (
        f"💰 <b>To'lov #{payment.id}</b>\n\n"
        f"👤 Ism: {user.first_name} {user.last_name}\n"
        f"📱 Telefon: {user.phone}\n"
        f"🆔 Username: @{user.username or 'yo`q'}\n"
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n\n"
        f"💵 Summa: {price} so'm\n"
        f"📊 Status: {status_map.get(payment.status, payment.status)}\n"
        f"📅 Sana: {payment.created_at:%d.%m.%Y %H:%M}\n"
    )

    if payment.approved_at:
        text += f"✅ Tasdiqlangan: {payment.approved_at:%d.%m.%Y %H:%M}\n"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Orqaga", callback_data=f"admin_payments_page_{from_page}")]]
    )

    # Delete old message and send photo with details
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_photo(
        chat_id=query.from_user.id,
        photo=payment.receipt_file_id,
        caption=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


# ─── Conversation states for adding card / channel ─────────────

async def receive_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin entered card number, now ask for holder name."""
    context.user_data["new_card_number"] = update.message.text.strip()
    await update.message.reply_text("👤 Karta egasining ismini kiriting:")
    return WAIT_CARD_HOLDER


async def receive_card_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin entered card holder, save card to DB."""
    card_number = context.user_data.pop("new_card_number")
    card_holder = update.message.text.strip()

    Card.create(card_number=card_number, card_holder=card_holder, is_active=True)

    await update.message.reply_text(
        f"✅ Karta qo'shildi!\n\n"
        f"💳 <code>{card_number}</code>\n"
        f"👤 {card_holder}\n\n"
        f"Admin panelga qaytish uchun /admin bosing.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def receive_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin entered channel/group ID — verify bot membership and permissions."""
    text = update.message.text.strip()
    try:
        chat_id = int(text)
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID. Raqam kiriting (masalan: -1001234567890):")
        return WAIT_CHANNEL_ID

    # ── 1. Check bot is a member of the chat ──
    try:
        chat = await context.bot.get_chat(chat_id)
    except Exception:
        await update.message.reply_text(
            "❌ Bot bu kanal/guruhni topa olmadi.\n\n"
            "Avval botni kanal/guruhga <b>admin</b> sifatida qo'shing, "
            "keyin qayta urinib ko'ring.\n\n"
            "Kanal/guruh ID sini kiriting:",
            parse_mode="HTML",
        )
        return WAIT_CHANNEL_ID

    # ── 2. Check bot's permissions ──
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
    except Exception:
        await update.message.reply_text(
            "❌ Bot a'zolik ma'lumotlarini ololmadi.\n\n"
            "Botni kanal/guruhga <b>admin</b> sifatida qo'shing.\n\n"
            "Kanal/guruh ID sini kiriting:",
            parse_mode="HTML",
        )
        return WAIT_CHANNEL_ID

    if bot_member.status not in ("administrator", "creator"):
        await update.message.reply_text(
            f"❌ Bot <b>{chat.title}</b> da admin emas!\n\n"
            "Botni <b>admin</b> sifatida qo'shing va quyidagi huquqlarni bering:\n"
            "• Foydalanuvchilarni taklif qilish\n"
            "• Foydalanuvchilarni cheklash\n\n"
            "Keyin qayta urinib ko'ring.\n"
            "Kanal/guruh ID sini kiriting:",
            parse_mode="HTML",
        )
        return WAIT_CHANNEL_ID

    # ── 3. Check specific required permissions ──
    missing = []
    if not getattr(bot_member, "can_invite_users", False):
        missing.append("• Foydalanuvchilarni taklif qilish (Invite Users)")
    if not getattr(bot_member, "can_restrict_members", False):
        missing.append("• Foydalanuvchilarni cheklash (Ban Users)")

    if missing:
        missing_text = "\n".join(missing)
        await update.message.reply_text(
            f"❌ Bot <b>{chat.title}</b> da quyidagi huquqlarga ega emas:\n\n"
            f"{missing_text}\n\n"
            "Bu huquqlarni bering va qayta urinib ko'ring.\n"
            "Kanal/guruh ID sini kiriting:",
            parse_mode="HTML",
        )
        return WAIT_CHANNEL_ID

    # ── All checks passed — save directly ──
    title = chat.title or f"Kanal #{chat_id}"
    Channel.create(chat_id=chat_id, title=title, is_active=True)

    await update.message.reply_text(
        f"✅ Kanal qo'shildi!\n\n"
        f"📺 {title} (<code>{chat_id}</code>)\n\n"
        f"Admin panelga qaytish uchun /admin bosing.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel admin conversation flow."""
    await update.message.reply_text("❌ Bekor qilindi. /admin bosing.")
    return ConversationHandler.END



# ─── Build handlers ──────────────────────────────────────────────

def get_admin_handlers():
    """Return all admin-related handlers."""
    # ConversationHandler for add_card / add_channel flows
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_callback, pattern=r"^admin_(add_card|add_channel)$"),
        ],
        states={
            WAIT_CARD_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_card_number)
            ],
            WAIT_CARD_HOLDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_card_holder)
            ],
            WAIT_CHANNEL_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_channel_id)
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        per_message=False,
    )

    return [
        CommandHandler("admin", admin_command),
        admin_conv,
        CallbackQueryHandler(admin_callback, pattern=r"^admin_"),
    ]
