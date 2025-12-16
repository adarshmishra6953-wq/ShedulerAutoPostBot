import os
import sqlite3
import threading  # Threading import kiya
from flask import Flask # Flask import kiya
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

# ==========================================
# 🌐 FAKE WEB SERVER (RENDER KO KHUSH RAKHNE KE LIYE)
# ==========================================
app_server = Flask(__name__)

@app_server.route('/')
def health_check():
    return "Bot is Alive! ✅"

def run_web_server():
    # Render PORT environment variable deta hai, use wo use karein
    port = int(os.environ.get("PORT", 8080))
    app_server.run(host='0.0.0.0', port=port)

# ==========================================
# 🤖 BOT CONFIGURATION
# ==========================================

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
        "Scheduler Auto Post Bot\n\nSelect option:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- ADD CHANNEL ----------
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["state"] = "waiting_for_channel"
    await update.callback_query.message.reply_text(
        "Channel ka @username bhejein\nExample:\n@mychannel"
    )

async def save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = await context.bot.get_chat(update.message.text)
        cur.execute(
            "INSERT OR IGNORE INTO channels VALUES (?,?)",
            (chat.id, chat.title)
        )
        conn.commit()
        await update.message.reply_text(f"✅ Channel added: {chat.title}")
    except Exception as e:
        await update.message.reply_text("❌ Bot admin nahi hai ya channel galat hai.")
        print(e)

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
    context.user_data["state"] = "waiting_for_photo"
    await update.callback_query.message.reply_text("Photo bhejein (caption optional)")

async def save_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "waiting_for_photo":
        return

    photo_id = update.message.photo[-1].file_id
    caption = update.message.caption or ""

    context.user_data["photo_id"] = photo_id
    context.user_data["caption"] = caption
    context.user_data["state"] = "waiting_for_time"
    
    await update.message.reply_text("Time bhejein (HH:MM) Example: 14:30")

async def save_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_text = update.message.text.strip()
        datetime.strptime(time_text, "%H:%M")
        
        cur.execute("""
            INSERT INTO posts (channel_id, photo_id, caption, time, repeat)
            VALUES (?,?,?,?,1)
        """, (
            context.user_data["channel_id"],
            context.user_data["photo_id"],
            context.user_data["caption"],
            time_text
        ))
        conn.commit()

        await update.message.reply_text(f"✅ Daily auto post set for {time_text}")
        context.user_data.clear()
    except ValueError:
        await update.message.reply_text("❌ Galat format. Kripya HH:MM format mein bhejein (e.g., 14:30)")

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state == "waiting_for_channel":
        await save_channel(update, context)
    elif state == "waiting_for_time":
        await save_time(update, context)
    else:
        await update.message.reply_text("Kripya pehle menu se option select karein (/start).")

# ---------- SCHEDULER ----------
async def send_posts(app):
    now = datetime.now().strftime("%H:%M")
    print(f"Checking schedule for: {now}") 
    cur.execute("SELECT channel_id, photo_id, caption FROM posts WHERE time=?", (now,))
    posts = cur.fetchall()
    for cid, pid, cap in posts:
        try:
            await app.bot.send_photo(cid, pid, caption=cap)
            print(f"Post sent to {cid}")
        except Exception as e:
            print(f"Failed to send to {cid}: {e}")

# ---------- MAIN ----------
def main():
    # 1. Pehle Fake Web Server ko alag thread mein start karo
    print("Starting Web Server for Render...")
    server_thread = threading.Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    # 2. Phir Bot start karo
    print("Bot is starting...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_posts, "interval", minutes=1, args=[app])
    scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(add_channel, pattern="add_channel"))
    app.add_handler(CallbackQueryHandler(list_channels, pattern="list_channels"))
    app.add_handler(CallbackQueryHandler(channel_menu, pattern="ch_"))
    app.add_handler(CallbackQueryHandler(add_post, pattern="add_post"))
    app.add_handler(MessageHandler(filters.PHOTO, save_post))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    app.run_polling()

if __name__ == "__main__":
    main()
