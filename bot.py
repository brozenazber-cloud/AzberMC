import asyncio
import os
import sqlite3
from datetime import datetime
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Railway environment variables
MAIN_BOT_TOKEN = os.getenv("MAIN_BOT_TOKEN", "").strip()
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(value.strip()) for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}
DB_PATH = os.getenv("DB_PATH", "shop.db")
SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "azbermc.tgmc.ir")
DEFAULT_CARD_NUMBER = os.getenv("CARD_NUMBER", "تنظیم نشده")
DEFAULT_CARD_NAME = os.getenv("CARD_NAME", "تنظیم نشده")
DEFAULT_SUPPORT = os.getenv("SUPPORT_USERNAME", "IBrOzen").lstrip("@")

if not MAIN_BOT_TOKEN or not ADMIN_BOT_TOKEN:
    raise RuntimeError("MAIN_BOT_TOKEN and ADMIN_BOT_TOKEN must be set in Railway Variables")
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS must contain at least one numeric Telegram user ID")

main_bot = Bot(MAIN_BOT_TOKEN)
admin_bot = Bot(ADMIN_BOT_TOKEN)
main_dp = Dispatcher()
admin_dp = Dispatcher()


def db():
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    with closing(db()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            price INTEGER NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            product_key TEXT NOT NULL,
            product_name TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            receipt_file_id TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY,
            percent INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_pending (
            user_id INTEGER PRIMARY KEY,
            product_key TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS awaiting_ign (
            user_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        defaults = {
            "card_number": DEFAULT_CARD_NUMBER,
            "card_name": DEFAULT_CARD_NAME,
            "support": DEFAULT_SUPPORT,
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))
        products = [
            ("sponsor_1m", "rank", "💎 Sponsor • یک ماهه", 450000, "حمایت مالی سرور به مدت یک ماه"),
            ("sponsor_2m", "rank", "💎 Sponsor • دو ماهه", 600000, "حمایت مالی سرور به مدت دو ماه"),
            ("sponsor_3m", "rank", "💎 Sponsor • سه ماهه", 950000, "حمایت مالی سرور به مدت سه ماه"),
            ("legend_1m", "rank", "👑 Legend • یک ماهه", 350000, "رنک Legend به مدت یک ماه"),
            ("legend_2m", "rank", "👑 Legend • دو ماهه", 370000, "رنک Legend به مدت دو ماه"),
            ("legend_3m", "rank", "👑 Legend • سه ماهه", 400000, "رنک Legend به مدت سه ماه"),
            ("vip_1m", "rank", "✨ VIP • یک ماهه", 200000, "رنک VIP به مدت یک ماه"),
            ("vip_2m", "rank", "✨ VIP • دو ماهه", 270000, "رنک VIP به مدت دو ماه"),
            ("vip_3m", "rank", "✨ VIP • سه ماهه", 307000, "رنک VIP به مدت سه ماه"),
            ("mvp_1m", "rank", "🌟 MVP • یک ماهه", 248000, "رنک MVP به مدت یک ماه"),
            ("mvp_2m", "rank", "🌟 MVP • دو ماهه", 268000, "رنک MVP به مدت دو ماه"),
            ("mvp_3m", "rank", "🌟 MVP • سه ماهه", 300000, "رنک MVP به مدت سه ماه"),
        ]
        # Disable all old rank products. Only the explicitly configured timed ranks below
        # should remain enabled; legacy rank keys/titles are deactivated automatically.
        timed_rank_keys = tuple(item[0] for item in products if item[1] == "rank")
        placeholders = ",".join("?" for _ in timed_rank_keys)
        conn.execute(
            f"UPDATE products SET enabled=0 WHERE category='rank' AND product_key NOT IN ({placeholders})",
            timed_rank_keys,
        )

        for key, category, title, price, description in products:
            conn.execute("""INSERT INTO products
                (product_key,category,title,price,description,enabled,created_at)
                VALUES(?,?,?,?,?,1,?)
                ON CONFLICT(product_key) DO UPDATE SET
                    category=excluded.category,
                    title=excluded.title,
                    price=excluded.price,
                    description=excluded.description""",
                (key, category, title, price, description, now()))
        conn.commit()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def money(value):
    return f"{int(value):,}".replace(",", "٬") + " تومان"


def get_setting(key, fallback=""):
    with closing(db()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else fallback


def set_setting(key, value):
    with closing(db()) as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.commit()


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎・فروشگاه رنک‌ها", callback_data="cat:rank")],
        [InlineKeyboardButton(text="⚡・قابلیت‌های OP", callback_data="cat:op"),
         InlineKeyboardButton(text="🛒・آیتم‌های شاپ", callback_data="cat:item")],
        [InlineKeyboardButton(text="👤・پروفایل من", callback_data="profile"),
         InlineKeyboardButton(text="💬・پشتیبانی", callback_data="support")],
        [InlineKeyboardButton(text="🌐・آدرس سرور", callback_data="server")],
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥・سفارش‌های در انتظار", callback_data="adm:orders"),
         InlineKeyboardButton(text="📊・آمار فروشگاه", callback_data="adm:stats")],
        [InlineKeyboardButton(text="🛍・مدیریت محصولات", callback_data="adm:products"),
         InlineKeyboardButton(text="➕・افزودن محصول", callback_data="adm:add")],
        [InlineKeyboardButton(text="💳・تنظیمات پرداخت", callback_data="adm:payment"),
         InlineKeyboardButton(text="🛟・تنظیم پشتیبانی", callback_data="adm:support")],
    ])


def is_admin(user_id):
    return user_id in ADMIN_IDS


class AdminStates(StatesGroup):
    card_number = State()
    card_name = State()
    support = State()
    product_key = State()
    product_category = State()
    product_title = State()
    product_price = State()
    product_description = State()
    minecraft_username = State()


@main_dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        f"╭━━━ ✦ 🏰 AZBER SMP 🏰 ✦ ━━━╮\n"
        f"│ 💎 فروشگاه رسمی سرور\n"
        f"│ 🌐 آدرس: {SERVER_ADDRESS}\n"
        f"│ 🧾 پرداخت با کارت و بررسی رسید توسط مدیریت\n"
        f"│ 🎮 بعد از تأیید، آیدی ماینکرفت دریافت می‌شود\n"
        f"╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"✨ خوش اومدی! از منوی شیشه‌ای زیر انتخاب کن:",
        reply_markup=main_menu(),
    )


@main_dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer("برای خرید از دکمه‌های منو استفاده کن. بعد از پرداخت، عکس رسید را همین‌جا ارسال کن.", reply_markup=main_menu())


@main_dp.callback_query(F.data.startswith("cat:"))
async def category(callback: CallbackQuery):
    category_name = callback.data.split(":", 1)[1]
    with closing(db()) as conn:
        rows = conn.execute("SELECT product_key,title,price,description FROM products WHERE category=? AND enabled=1 ORDER BY id", (category_name,)).fetchall()
    if not rows:
        await callback.answer("فعلاً محصول فعالی در این دسته نیست.", show_alert=True)
        return
    buttons = [[InlineKeyboardButton(text=f"🛍 {title} — {money(price)}", callback_data=f"buy:{key}")] for key, title, price, desc in rows]
    buttons.append([InlineKeyboardButton(text="⬅️ بازگشت به منوی اصلی", callback_data="home")])
    labels = {"rank": "💎・رنک‌های ویژه AZBER SMP", "op": "⚡・قابلیت‌های OP", "item": "🛒・آیتم‌های فروشگاه AZBER"}
    await callback.message.edit_text(f"{labels.get(category_name, 'فروشگاه')}\n\nمحصول موردنظرت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@main_dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):
    await callback.message.edit_text("منوی اصلی فروشگاه Azber SMP", reply_markup=main_menu())
    await callback.answer()


@main_dp.callback_query(F.data == "server")
async def server_info(callback: CallbackQuery):
    await callback.message.answer(
        f"🌐 **AZBER SMP**\\n━━━━━━━━━━━━━━\\n"
        f"🎮 آدرس سرور: `{SERVER_ADDRESS}`\\n"
        f"💎 رنک‌های ویژه و فروشگاه اختصاصی\\n"
        f"🛟 پشتیبانی: @{get_setting('support', DEFAULT_SUPPORT).lstrip('@')}",
        parse_mode="Markdown",
    )
    await callback.answer()


@main_dp.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    with closing(db()) as conn:
        product = conn.execute("SELECT product_key,title,price,description FROM products WHERE product_key=? AND enabled=1", (key,)).fetchone()
    if not product:
        await callback.answer("این محصول دیگر فعال نیست.", show_alert=True)
        return
    product_key, title, price, description = product
    with closing(db()) as conn:
        conn.execute("INSERT OR REPLACE INTO user_pending(user_id,product_key) VALUES(?,?)", (callback.from_user.id, product_key))
        conn.commit()
    card_number = get_setting("card_number", DEFAULT_CARD_NUMBER)
    card_name = get_setting("card_name", DEFAULT_CARD_NAME)
    text = (f"**{title}**\n{description}\n\nقیمت: {money(price)}\n\n"
            f"شماره کارت: `{card_number}`\nبه نام: {card_name}\n\n"
            "پس از پرداخت، عکس رسید را در همین ربات ارسال کن. سفارش پس از بررسی مدیر تأیید می‌شود.")
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer("اطلاعات پرداخت ارسال شد")


@main_dp.message(F.photo)
async def receipt(message: Message):
    with closing(db()) as conn:
        pending = conn.execute("SELECT product_key FROM user_pending WHERE user_id=?", (message.from_user.id,)).fetchone()
        if not pending:
            await message.answer("اول محصولت رو از منوی فروشگاه انتخاب کن، بعد رسید رو بفرست.", reply_markup=main_menu())
            return
        product = conn.execute("SELECT title,price FROM products WHERE product_key=?", (pending[0],)).fetchone()
        if not product:
            await message.answer("محصول پیدا نشد؛ دوباره از منو انتخابش کن.")
            return
        cursor = conn.execute("""INSERT INTO orders(user_id,username,product_key,product_name,amount,status,receipt_file_id,created_at)
            VALUES(?,?,?,?,?,'pending',?,?)""", (message.from_user.id, message.from_user.username or "", pending[0], product[0], product[1], message.photo[-1].file_id, now()))
        order_id = cursor.lastrowid
        conn.execute("DELETE FROM user_pending WHERE user_id=?", (message.from_user.id,))
        conn.commit()
    await message.answer(f"✅ رسیدت ثبت شد.\nشماره سفارش: #{order_id}\nرسید مستقیم برای پنل ادمین ارسال شد؛ نتیجه همین‌جا بهت اعلام می‌شه.", reply_markup=main_menu())
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="تأیید سفارش", callback_data=f"review:approve:{order_id}"),
        InlineKeyboardButton(text="رد سفارش", callback_data=f"review:reject:{order_id}"),
    ]])
    caption = f"📥 سفارش جدید #{order_id}\n━━━━━━━━━━━━━━\n🛍 محصول: {product[0]}\n💰 مبلغ: {money(product[1])}\n👤 کاربر: {message.from_user.full_name} (@{message.from_user.username or 'ندارد'})\n🆔 شناسه تلگرام: {message.from_user.id}\n🌐 سرور: {SERVER_ADDRESS}\n🕒 زمان: {now()}\n⏳ وضعیت: در انتظار بررسی"
    for admin_id in ADMIN_IDS:
        try:
            await admin_bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=kb)
        except Exception as exc:
            print(f"Could not notify admin {admin_id}: {exc}")


@main_dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    with closing(db()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (callback.from_user.id,)).fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='pending'", (callback.from_user.id,)).fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='approved'", (callback.from_user.id,)).fetchone()[0]
    await callback.message.answer(f"پروفایل شما\nشناسه تلگرام: {callback.from_user.id}\nتعداد سفارش‌ها: {total}\nدر انتظار بررسی: {pending}\nتأییدشده: {approved}")
    await callback.answer()


@main_dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    username = get_setting("support", DEFAULT_SUPPORT).lstrip("@")
    await callback.message.answer(f"برای پشتیبانی به این آیدی پیام بده: @{username}")
    await callback.answer()


@admin_dp.message(CommandStart())
async def admin_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("شما اجازه دسترسی به پنل مدیریت را ندارید.")
        return
    await message.answer("پنل مدیریت Azber SMP", reply_markup=admin_menu())


@admin_dp.message(Command("admin"))
async def admin_command(message: Message):
    await admin_start(message)


@admin_dp.callback_query(F.data.startswith("adm:"))
async def admin_actions(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی غیرمجاز", show_alert=True)
        return
    action = callback.data.split(":", 1)[1]
    if action == "orders":
        with closing(db()) as conn:
            rows = conn.execute("SELECT id,product_name,amount,user_id,created_at FROM orders WHERE status='pending' ORDER BY id DESC LIMIT 20").fetchall()
        if not rows:
            await callback.message.answer("سفارش در انتظار بررسی وجود ندارد.")
        for order_id, name, amount, user_id, created_at in rows:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="تأیید", callback_data=f"review:approve:{order_id}"),
                InlineKeyboardButton(text="رد", callback_data=f"review:reject:{order_id}"),
            ]])
            await callback.message.answer(f"سفارش #{order_id}\n{name}\n{money(amount)}\nکاربر: {user_id}\n{created_at}", reply_markup=kb)
    elif action == "products":
        with closing(db()) as conn:
            rows = conn.execute("SELECT product_key,title,price,enabled FROM products ORDER BY id").fetchall()
        for key, title, price, enabled in rows:
            label = "خاموش کردن" if enabled else "فعال کردن"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=f"toggle:{key}")]])
            await callback.message.answer(f"{title} ({key}) — {money(price)} — {'فعال' if enabled else 'غیرفعال'}", reply_markup=kb)
    elif action == "stats":
        with closing(db()) as conn:
            total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
            approved = conn.execute("SELECT COUNT(*) FROM orders WHERE status='approved'").fetchone()[0]
            rejected = conn.execute("SELECT COUNT(*) FROM orders WHERE status='rejected'").fetchone()[0]
            revenue = conn.execute("SELECT COALESCE(SUM(amount),0) FROM orders WHERE status='approved'").fetchone()[0]
            products = conn.execute("SELECT COUNT(*) FROM products WHERE enabled=1").fetchone()[0]
        await callback.message.answer(f"📊 آمار فروشگاه Azber SMP\n━━━━━━━━━━━━━━\n🧾 کل سفارش‌ها: {total}\n⏳ در انتظار: {pending}\n✅ تأییدشده: {approved}\n❌ ردشده: {rejected}\n💰 فروش تأییدشده: {money(revenue)}\n🛍 محصولات فعال: {products}", reply_markup=admin_menu())
    elif action == "payment":
        await callback.message.answer("شماره کارت جدید را ارسال کن:")
        await state.set_state(AdminStates.card_number)
    elif action == "support":
        await callback.message.answer("آیدی پشتیبانی جدید را بدون @ یا با @ ارسال کن:")
        await state.set_state(AdminStates.support)
    elif action == "add":
        await callback.message.answer("یک شناسه انگلیسی یکتا برای محصول بفرست؛ مثال: vip_plus")
        await state.set_state(AdminStates.product_key)
    await callback.answer()


@admin_dp.callback_query(F.data.startswith("toggle:"))
async def toggle_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی غیرمجاز", show_alert=True)
        return
    key = callback.data.split(":", 1)[1]
    with closing(db()) as conn:
        row = conn.execute("SELECT enabled FROM products WHERE product_key=?", (key,)).fetchone()
        if row is None:
            await callback.answer("محصول پیدا نشد", show_alert=True)
            return
        new_value = 0 if row[0] else 1
        conn.execute("UPDATE products SET enabled=? WHERE product_key=?", (new_value, key))
        conn.commit()
    await callback.message.edit_text(f"محصول {key} اکنون {'فعال' if new_value else 'غیرفعال'} است.")
    await callback.answer()


@admin_dp.callback_query(F.data.startswith("review:"))
async def review_order(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی غیرمجاز", show_alert=True)
        return
    _, decision, order_id_text = callback.data.split(":", 2)
    order_id = int(order_id_text)
    status = "approved" if decision == "approve" else "rejected"
    with closing(db()) as conn:
        row = conn.execute("SELECT user_id,product_name,amount,status FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row:
            await callback.answer("سفارش پیدا نشد", show_alert=True)
            return
        user_id, product_name, amount, old_status = row
        if old_status != "pending":
            await callback.answer(f"این سفارش قبلاً بررسی شده است: {old_status}", show_alert=True)
            return
        conn.execute("UPDATE orders SET status=?,reviewed_at=? WHERE id=? AND status='pending'", (status, now(), order_id))
        conn.commit()
    if status == "approved":
        with closing(db()) as conn:
            conn.execute("INSERT INTO awaiting_ign(user_id,order_id,created_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET order_id=excluded.order_id, created_at=excluded.created_at", (user_id, order_id, now()))
            conn.commit()
        user_text = (f"✅ پرداخت سفارش #{order_id} تأیید شد!\n\n🛍 محصول: {product_name}\n\nبرای تحویل محصول، لطفاً **آیدی دقیق داخل بازی Minecraft (IGN)** خودت رو همین‌جا بفرست.\nمثال: Azber_Player\n\n⚠️ نام داخل بازی رو دقیق وارد کن؛ لازم نیست به پشتیبانی پیام بدی.")
        admin_text = f"✅ سفارش #{order_id} تأیید شد؛ از کاربر نام داخل بازی گرفته می‌شود و برای ادمین ارسال خواهد شد."
    else:
        user_text = f"سفارش #{order_id} برای {product_name} رد شد. اگر فکر می‌کنی اشتباهی شده، با پشتیبانی تماس بگیر: @{get_setting('support', DEFAULT_SUPPORT).lstrip('@')}"
        admin_text = f"سفارش #{order_id} رد شد."
    try:
        await main_bot.send_message(user_id, user_text)
    except Exception as exc:
        print(f"Could not notify customer {user_id}: {exc}")
    await callback.message.edit_caption(caption=f"{callback.message.caption or ''}\n\n{admin_text}", reply_markup=None) if callback.message.photo else callback.message.edit_text(f"{callback.message.text or ''}\n\n{admin_text}", reply_markup=None)
    await callback.answer("انجام شد")


@main_dp.message(F.text)
async def receive_minecraft_username(message: Message):
    if not message.from_user:
        return
    with closing(db()) as conn:
        pending_ign = conn.execute("SELECT order_id FROM awaiting_ign WHERE user_id=?", (message.from_user.id,)).fetchone()
    if not pending_ign:
        return
    ign = message.text.strip()
    if not (3 <= len(ign) <= 16) or not ign.replace("_", "").isalnum():
        await message.answer("❗ نام ماینکرفت باید ۳ تا ۱۶ کاراکتر و شامل حروف انگلیسی، عدد یا _ باشد. دوباره بفرست:")
        return
    order_id = pending_ign[0]
    with closing(db()) as conn:
        conn.execute("DELETE FROM awaiting_ign WHERE user_id=?", (message.from_user.id,))
        conn.commit()
    await message.answer(f"🎮 نام بازی ثبت شد: `{ign}`\n\nسفارش #{order_id} برای تحویل به تیم Azber SMP ارسال شد. ممنون از خریدت!\n🌐 سرور: {SERVER_ADDRESS}", parse_mode="Markdown", reply_markup=main_menu())
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 تحویل انجام شد", callback_data=f"delivered:{order_id}")]])
    for admin_id in ADMIN_IDS:
        try:
            await admin_bot.send_message(admin_id, f"🎮 اطلاعات تحویل سفارش #{order_id}\n━━━━━━━━━━━━━━\n🛍 محصول: {get_order_product(order_id)}\n👤 نام کاربر: {message.from_user.full_name}\n🆔 Telegram ID: {message.from_user.id}\n🎮 Minecraft IGN: {ign}\n🌐 سرور: {SERVER_ADDRESS}", reply_markup=kb)
        except Exception as exc:
            print(f"Could not notify admin {admin_id}: {exc}")


def get_order_product(order_id):
    with closing(db()) as conn:
        row = conn.execute("SELECT product_name FROM orders WHERE id=?", (order_id,)).fetchone()
    return row[0] if row else "نامشخص"


@admin_dp.callback_query(F.data.startswith("delivered:"))
async def mark_delivered(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی غیرمجاز", show_alert=True)
        return
    order_id = callback.data.split(":", 1)[1]
    await callback.message.edit_text(f"✅ سفارش #{order_id} به‌عنوان تحویل‌شده علامت خورد.")
    await callback.answer("ثبت شد")


@admin_dp.message(AdminStates.card_number)
async def set_card_number(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    value = message.text.strip()
    if len(value) < 8:
        await message.answer("شماره کارت معتبر به نظر نمی‌رسد؛ دوباره بفرست.")
        return
    set_setting("card_number", value)
    await message.answer("شماره کارت ذخیره شد. حالا نام صاحب کارت را بفرست:")
    await state.set_state(AdminStates.card_name)


@admin_dp.message(AdminStates.card_name)
async def set_card_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    set_setting("card_name", message.text.strip())
    await state.clear()
    await message.answer("اطلاعات کارت ذخیره شد.", reply_markup=admin_menu())


@admin_dp.message(AdminStates.support)
async def set_support(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    username = message.text.strip().lstrip("@").replace(" ", "")
    if not username:
        await message.answer("آیدی خالی است؛ دوباره بفرست.")
        return
    set_setting("support", username)
    await state.clear()
    await message.answer(f"پشتیبانی روی @{username} تنظیم شد.", reply_markup=admin_menu())


@admin_dp.message(AdminStates.product_key)
async def add_product_key(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    key = message.text.strip().lower().replace(" ", "_")
    if not key or not key.replace("_", "").isalnum():
        await message.answer("شناسه فقط باید شامل حروف انگلیسی، عدد و زیرخط باشد.")
        return
    with closing(db()) as conn:
        exists = conn.execute("SELECT 1 FROM products WHERE product_key=?", (key,)).fetchone()
    if exists:
        await message.answer("این شناسه از قبل وجود دارد؛ یک شناسه دیگر بفرست.")
        return
    await state.update_data(product_key=key)
    await message.answer("دسته محصول را بفرست: rank (رنک)، op (قابلیت) یا item (شاپ آیتم)")
    await state.set_state(AdminStates.product_category)


@admin_dp.message(AdminStates.product_category)
async def add_product_category(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    category = message.text.strip().lower()
    if category not in ("rank", "op", "item"):
        await message.answer("فقط rank یا op یا item را بفرست.")
        return
    await state.update_data(category=category)
    await message.answer("نام محصول را بفرست:")
    await state.set_state(AdminStates.product_title)


@admin_dp.message(AdminStates.product_title)
async def add_product_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(title=message.text.strip())
    await message.answer("قیمت را فقط به تومان و به شکل عدد بفرست:")
    await state.set_state(AdminStates.product_price)


@admin_dp.message(AdminStates.product_price)
async def add_product_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) < 0:
        await message.answer("قیمت باید عدد صفر یا بیشتر باشد.")
        return
    await state.update_data(price=int(raw))
    await message.answer("توضیحات محصول را بفرست:")
    await state.set_state(AdminStates.product_description)


@admin_dp.message(AdminStates.product_description)
async def add_product_description(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    with closing(db()) as conn:
        conn.execute("""INSERT INTO products(product_key,category,title,price,description,enabled,created_at)
            VALUES(?,?,?,?,?,1,?)""", (data["product_key"], data["category"], data["title"], data["price"], message.text.strip(), now()))
        conn.commit()
    await state.clear()
    await message.answer(f"محصول «{data['title']}» با قیمت {money(data['price'])} اضافه شد.", reply_markup=admin_menu())


async def main():
    init_db()
    print(f"AZBER SMP shop bots starting... Server: {SERVER_ADDRESS}")
    await asyncio.gather(
        main_dp.start_polling(main_bot, handle_signals=False, close_bot_session=False),
        admin_dp.start_polling(admin_bot, handle_signals=False, close_bot_session=False),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        try:
            asyncio.run(main_bot.session.close())
        except Exception:
            pass
        try:
            asyncio.run(admin_bot.session.close())
        except Exception:
            pass
