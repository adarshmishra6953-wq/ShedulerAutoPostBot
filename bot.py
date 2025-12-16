import os
import sqlite3
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ---------- DATABASE ----------
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
        "🔹 Sheduler Auto Post Bot\n\nSelect option:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- ADD CHANNEL ----------
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "👉 Channel का @username भेजें\n\nExample:\n@mychannel"
    )
    context.user_data["waiting_channel"] = True

async def save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_channel"):
        return

    channel = update.message.text.strip()
    try:
        chat = await context.bot.get_chat(channel)
        cur.execute(
            "INSERT OR IGNORE INTO channels VALUES (?,?)",
            (chat.id, chat.title)
        )
        conn.commit()
        await update.message.reply_text("✅ Channel added successfully")
    except:
        await update.message.reply_text("❌ Channel नहीं मिला या bot admin नहीं है")

    context.user_data["waiting_channel"] = False

# ---------- LIST CHANNELS ----------
async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cur.execute("SELECT channel_id, channel_name FROM channels")
    rows = cur.fetchall()

    if not rows:
        await update.callback_query.message.reply_text("❌ No channels added")
        return

    keyboard = []
    for cid, name in rows:
        keyboard.append([
            InlineKeyboardButton(name, callback_data=f"channel_{cid}")
        ])

    await update.callback_query.message.reply_text(
        "📢 Select Channel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- CHANNEL MENU ----------
async def channel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = update.callback_query.data.split("_")[1]
    context.user_data["channel_id"] = cid

    keyboard = [
        [InlineKeyboardButton("🖼 Add Post", callback_data="add_post")],
        [InlineKeyboardButton("📋 View Posts", callback_data="view_posts")],
        [InlineKeyboardButton("⬅ Back", callback_data="back")]
    ]
    await update.callback_query.message.reply_text(
        "📌 Channel Menu:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- ADD POST ----------
async def add_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🖼 Photo भेजें (caption optional)"
    )
    context.user_data["waiting_photo"] = True

async def save_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_photo"):
        return

    photo_id = update.message.photo[-1].file_id
    caption = update.message.caption or ""
    context.user_data["photo_id"] = photo_id
    context.user_data["caption"] = caption

    await update.message.reply_text(
        "⏰ Time भेजें (24h format)\nExample: 08:00"
    )
    context.user_data["waiting_photo"] = False
    context.user_data["waiting_time"] = True

async def save_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_time"):
        return

    time = update.message.text.strip()
    channel_id = context.user_data["channel_id"]

    cur.execute("""
        INSERT INTO posts (channel_id, photo_id, caption, time, repeat)
        VALUES (?,?,?,?,1)
    """, (
        channel_id,
        context.user_data["photo_id"],
        context.user_data["caption"],
        time
    ))
    conn.commit()

    await update.message.reply_text("✅ Post daily repeat के साथ set हो गया")
    context.user_data.clear()

# ---------- VIEW POSTS ----------
async def view_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = context.user_data["channel_id"]

    cur.execute(
        "SELECT time, caption FROM posts WHERE channel_id=?",
        (cid,)
    )
    rows = cur.fetchall()

    if not rows:
        await update.callback_query.message.reply_text("❌ No posts found")
        return

    msg = "📋 Scheduled Posts:\n\n"
    for t, c in rows:
        msg += f"⏰ {t} → {c[:30]}\n"

    await update.callback_query.message.reply_text(msg)

# ---------- BACK ----------
async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ---------- SCHEDULER ----------
async def send_scheduled_posts(app):
    now = datetime.now().strftime("%H:%M")
    cur.execute(
        "SELECT channel_id, photo_id, caption FROM posts WHERE time=? AND repeat=1",
        (now,)
    )
    rows = cur.fetchall()

    for cid, pid, cap in rows:
        try:
            await app.bot.send_photo(cid, pid, caption=cap)
        except:
            pass

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_scheduled_posts,
        "interval",
        minutes=1,
        args=[app]
    )
    scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(add_channel, pattern="add_channel"))
    app.add_handler(CallbackQueryHandler(list_channels, pattern="list_channels"))
    app.add_handler(CallbackQueryHandler(channel_menu, pattern="channel_"))
    app.add_handler(CallbackQueryHandler(add_post, pattern="add_post"))
    app.add_handler(CallbackQueryHandler(view_posts, pattern="view_posts"))
    app.add_handler(CallbackQueryHandler(back, pattern="back"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_channel))
    app.add_handler(MessageHandler(filters.PHOTO, save_photo))
    app.add_handler(MessageHandler(filters.TEXT, save_time))

    app.run_polling()

if __name__ == "__main__":
    main()
