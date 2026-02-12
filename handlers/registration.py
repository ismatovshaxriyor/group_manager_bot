"""Registration handler — welcome menu, subscription flow, status, and support."""

import os
import datetime
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
from database import User, Payment, Card, Subscription

logger = logging.getLogger(__name__)

# Conversation states (no more MENU — menu is handled outside ConversationHandler)
ASK_FULLNAME, ASK_PHONE, ASK_RECEIPT = range(3)

# Button labels
BTN_JOIN = "🎓 Kursga qo'shilish"
BTN_STATUS = "🗂 Obuna holati"
BTN_HELP = "📞 Yordam"

# Path to welcome image
WELCOME_IMAGE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "welcome.jpg")


# ─── Main menu keyboard ─────────────────────────────────────────

def _main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_JOIN)],
            [KeyboardButton(BTN_STATUS)],
            [KeyboardButton(BTN_HELP)],
        ],
        resize_keyboard=True,
    )


# ─── /start — sends welcome image, does NOT enter conversation ──

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point — /start command. Send welcome image with keyboard menu."""
    keyboard = _main_menu_keyboard()
    caption = (
        "Assalomu alaykum! 🎓  Kursga obuna bo'ling va yopiq guruhga qo'shiling.\n\n"
        "Kerakli bo'limni pastdagi menyudan tanlang 👇"
    )

    try:
        with open(WELCOME_IMAGE, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=caption,
                reply_markup=keyboard,
            )
    except FileNotFoundError:
        await update.message.reply_text(caption, reply_markup=keyboard)

    return ConversationHandler.END


# ─── Menu button handlers (standalone, NOT inside ConversationHandler) ──

async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's subscription status."""
    telegram_id = update.effective_user.id

    try:
        user = User.get(User.telegram_id == telegram_id)
    except User.DoesNotExist:
        await update.message.reply_text(
            "🗂 <b>Obuna holati</b>\n\n"
            "❌ Siz hali ro'yxatdan o'tmagansiz.\n\n"
            "\"Kursga qo'shilish\" tugmasini bosing.",
            parse_mode="HTML",
        )
        return

    sub = (
        Subscription.select()
        .where((Subscription.user == user) & (Subscription.is_active == True))
        .first()
    )

    if sub:
        days_left = (sub.end_date - datetime.datetime.now()).days
        text = (
            f"🗂 <b>Obuna holati</b>\n\n"
            f"👤 {user.first_name} {user.last_name}\n"
            f"📱 {user.phone}\n\n"
            f"✅ <b>Obuna faol</b>\n"
            f"📅 Tugash sanasi: {sub.end_date:%d.%m.%Y}\n"
            f"⏳ Qolgan kunlar: <b>{max(days_left, 0)} kun</b>"
        )
    else:
        text = (
            f"🗂 <b>Obuna holati</b>\n\n"
            f"👤 {user.first_name} {user.last_name}\n"
            f"📱 {user.phone}\n\n"
            f"❌ <b>Aktiv obuna yo'q</b>\n\n"
            f"Obunani yangilash uchun \"Kursga qo'shilish\" tugmasini bosing."
        )

    await update.message.reply_text(text, parse_mode="HTML")


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show support contact info."""
    support_contact = os.getenv("SUPPORT_CONTACT", "Admin")
    support_phone = os.getenv("SUPPORT_PHONE", "")

    text = (
        f"📞 <b>Yordam</b>\n\n"
        f"Savollar yoki muammolar bo'lsa, quyidagi kontakt orqali bog'laning:\n\n"
        f"👤 {support_contact}"
    )
    if support_phone:
        text += f"\n📱 {support_phone}"

    await update.message.reply_text(text, parse_mode="HTML")


# ─── Kursga qo'shilish (registration flow — ConversationHandler) ─

async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the course registration flow."""
    await update.message.reply_text(
        "🎓 <b>Kursga qo'shilish</b>\n\n"
        "📝 Ism-familiyangizni yuboring (masalan: Akmal Akbarov).",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
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

    cards = Card.select().where(Card.is_active == True)
    if not cards:
        await update.message.reply_text(
            "⚠️ Hozircha to'lov kartasi qo'shilmagan. Iltimos, keyinroq urinib ko'ring.",
            reply_markup=_main_menu_keyboard(),
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

    photo = update.message.photo[-1]
    file_id = photo.file_id
    telegram_id = update.effective_user.id
    username = update.effective_user.username
    first_name = context.user_data["first_name"]
    last_name = context.user_data["last_name"]
    phone = context.user_data["phone"]

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

    payment = Payment.create(
        user=user,
        amount=MONTHLY_PRICE,
        receipt_file_id=file_id,
        status="pending",
    )

    price_formatted = f"{MONTHLY_PRICE:,}".replace(",", " ")
    admin_text = (
        f"🆕 <b>Yangi to'lov!</b>\n\n"
        f"👤 Ism: {first_name} {last_name}\n"
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
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=admin_text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Failed to send receipt to admin {admin_id}: {e}")

    await update.message.reply_text(
        "✅ Chek qabul qilindi!\n\n"
        "⏳ Admin tekshirmoqda. Iltimos, kuting...",
        reply_markup=_main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─── Cancel ──────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text(
        "❌ Bekor qilindi.",
        reply_markup=_main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─── Build handlers ─────────────────────────────────────────────

def get_registration_handler():
    """Build and return registration ConversationHandler + standalone menu handlers."""
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(f"^{BTN_JOIN}$"), start_registration),
        ],
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
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        allow_reentry=True,
    )

    # Standalone handlers for menu buttons (NOT inside ConversationHandler)
    status_handler = MessageHandler(filters.Regex(f"^{BTN_STATUS}$"), handle_status)
    help_handler = MessageHandler(filters.Regex(f"^{BTN_HELP}$"), handle_help)

    return conv, status_handler, help_handler
