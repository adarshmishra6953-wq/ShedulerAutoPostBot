import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ---------- DB ----------
conn = sqlite3.connect("posts.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS channels (
    channel_id INTEGER PRIMARY KEY,
    channel_name TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER,
    photo_id TEXT,
    caption TEXT,
    time TEXT,
    repeat INTEGER
)
""")
conn.commit()

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")],
        [InlineKeyboardButton("📋 My Channels", callback_data="list_channels")]
    ]
    await update.message.reply_text(
        "Sheduler Auto Post Bot\n\nSelect option:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- ADD CHANNEL ----------
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["add_channel"] = True
    await update.callback_query.message.reply_text(
        "Channel का @username भेजें\nExample:\n@mychannel"
    )

async def save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("add_channel"):
        return

    try:
        chat = await context.bot.get_chat(update.message.text)
        cur.execute(
            "INSERT OR IGNORE INTO channels VALUES (?,?)",
            (chat.id, chat.title)
        )
        conn.commit()
        await update.message.reply_text("✅ Channel added")
    except:
        await update.message.reply_text("❌ Bot admin नहीं है या channel गलत है")

    context.user_data.clear()

# ---------- LIST CHANNELS ----------
async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cur.execute("SELECT channel_id, channel_name FROM channels")
    rows = cur.fetchall()

    if not rows:
        await update.callback_query.message.reply_text("No channels found")
        return

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"ch_{cid}")]
        for cid, name in rows
    ]

    await update.callback_query.message.reply_text(
        "Select channel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- ADD POST ----------
async def channel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["channel_id"] = int(update.callback_query.data.split("_")[1])

    keyboard = [
        [InlineKeyboardButton("🖼 Add Post", callback_data="add_post")]
    ]
    await update.callback_query.message.reply_text(
        "Channel menu:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def add_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["add_post"] = True
    await update.callback_query.message.reply_text("Photo भेजें (caption optional)")

async def save_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("add_post"):
        return

    photo_id = update.message.photo[-1].file_id
    caption = update.message.caption or ""

    context.user_data["photo_id"] = photo_id
    context.user_data["caption"] = caption
    context.user_data["add_post"] = False
    context.user_data["ask_time"] = True

    await update.message.reply_text("Time भेजें (HH:MM)")

async def save_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("ask_time"):
        return

    cur.execute("""
        INSERT INTO posts (channel_id, photo_id, caption, time, repeat)
        VALUES (?,?,?,?,1)
    """, (
        context.user_data["channel_id"],
        context.user_data["photo_id"],
        context.user_data["caption"],
        update.message.text.strip()
    ))
    conn.commit()

    await update.message.reply_text("✅ Daily auto post set")
    context.user_data.clear()

# ---------- SCHEDULER ----------
async def send_posts(app):
    now = datetime.now().strftime("%H:%M")
    cur.execute("SELECT channel_id, photo_id, caption FROM posts WHERE time=?", (now,))
    for cid, pid, cap in cur.fetchall():
        try:
            await app.bot.send_photo(cid, pid, caption=cap)
        except:
            pass

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_posts, "interval", minutes=1, args=[app])
    scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(add_channel, pattern="add_channel"))
    app.add_handler(CallbackQueryHandler(list_channels, pattern="list_channels"))
    app.add_handler(CallbackQueryHandler(channel_menu, pattern="ch_"))
    app.add_handler(CallbackQueryHandler(add_post, pattern="add_post"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_channel))
    app.add_handler(MessageHandler(filters.PHOTO, save_post))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_time))

    app.run_polling()

if __name__ == "__main__":
    main()
