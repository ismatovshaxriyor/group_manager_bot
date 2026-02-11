"""Registration conversation handler — collects name, surname, phone, and payment receipt."""

import logging

from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import ADMIN_IDS, MONTHLY_PRICE
from database import User, Payment, Card

logger = logging.getLogger(__name__)

# Conversation states
ASK_FULLNAME, ASK_PHONE, ASK_RECEIPT = range(3)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point — /start command."""
    await update.message.reply_text(
        "👋 Assalomu alaykum! Ro'yxatdan o'tish uchun ma'lumotlaringizni kiriting.\n\n"
        "📝 Ism va familiyangizni kiriting:"
    )
    return ASK_FULLNAME


async def ask_fullname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save full name, ask for phone number."""
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)
    context.user_data["first_name"] = parts[0]
    context.user_data["last_name"] = parts[1] if len(parts) > 1 else ""

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "📱 Telefon raqamingizni yuboring (tugmani bosing):", reply_markup=keyboard
    )
    return ASK_PHONE


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save phone number, show payment details."""
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()

    context.user_data["phone"] = phone

    price_formatted = f"{MONTHLY_PRICE:,}".replace(",", " ")

    # Get active cards from DB
    cards = Card.select().where(Card.is_active == True)
    if not cards:
        await update.message.reply_text(
            "⚠️ Hozircha to'lov kartasi qo'shilmagan. Iltimos, keyinroq urinib ko'ring.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    card_text = ""
    for card in cards:
        card_text += f"💳 <code>{card.card_number}</code>\n👤 {card.card_holder}\n\n"

    await update.message.reply_text(
        f"✅ Ma'lumotlaringiz qabul qilindi!\n\n"
        f"💰 1 oylik obuna narxi: <b>{price_formatted} so'm</b>\n\n"
        f"{card_text}"
        f"📸 To'lov qilganingizdan so'ng chek rasmini yuboring:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_RECEIPT


async def ask_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save receipt, forward to admin for approval."""
    if not update.message.photo:
        await update.message.reply_text(
            "❌ Iltimos, chek <b>rasmini</b> yuboring (faqat rasm).", parse_mode="HTML"
        )
        return ASK_RECEIPT

    photo = update.message.photo[-1]  # highest resolution
    file_id = photo.file_id
    telegram_id = update.effective_user.id
    username = update.effective_user.username
    first_name = context.user_data["first_name"]
    last_name = context.user_data["last_name"]
    phone = context.user_data["phone"]

    # Save or update user in DB
    user, created = User.get_or_create(
        telegram_id=telegram_id,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "username": username or "",
        },
    )
    if not created:
        user.first_name = first_name
        user.last_name = last_name
        user.phone = phone
        user.username = username or ""
        user.save()

    # Create payment record
    payment = Payment.create(
        user=user,
        amount=MONTHLY_PRICE,
        receipt_file_id=file_id,
        status="pending",
    )

    # Notify admin
    price_formatted = f"{MONTHLY_PRICE:,}".replace(",", " ")
    admin_text = (
        f"🆕 <b>Yangi to'lov!</b>\n\n"
        f"👤 Ism: {first_name}\n"
        f"👤 Familiya: {last_name}\n"
        f"📱 Telefon: {phone}\n"
        f"🆔 Username: @{username or 'yo`q'}\n"
        f"🆔 Telegram ID: <code>{telegram_id}</code>\n"
        f"💰 Summa: {price_formatted} so'm\n"
        f"🕐 To'lov ID: #{payment.id}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Tasdiqlash", callback_data=f"approve_{payment.id}"
                ),
                InlineKeyboardButton(
                    "❌ Rad etish", callback_data=f"reject_{payment.id}"
                ),
            ]
        ]
    )

    for admin_id in ADMIN_IDS:
        await context.bot.send_photo(
            chat_id=admin_id,
            photo=file_id,
            caption=admin_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    await update.message.reply_text(
        "✅ Chek qabul qilindi!\n\n"
        "⏳ Admin tekshirmoqda. Iltimos, kuting...",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text(
        "❌ Bekor qilindi. Qaytadan boshlash uchun /start bosing.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


def get_registration_handler() -> ConversationHandler:
    """Build and return the registration ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_FULLNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_fullname)
            ],
            ASK_PHONE: [
                MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), ask_phone)
            ],
            ASK_RECEIPT: [
                MessageHandler(filters.PHOTO, ask_receipt),
                MessageHandler(
                    ~filters.PHOTO & ~filters.COMMAND,
                    lambda u, c: u.message.reply_text(
                        "❌ Iltimos, chek <b>rasmini</b> yuboring.", parse_mode="HTML"
                    ),
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
