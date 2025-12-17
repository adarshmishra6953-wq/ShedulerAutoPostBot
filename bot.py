import os
import sqlite3
import threading
import asyncio
from flask import Flask
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ---------- CONFIG ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
IST = pytz.timezone('Asia/Kolkata')

# ---------- SERVER FOR RENDER ----------
app_server = Flask(__name__)
@app_server.route('/')
def health_check(): return "Bot is Alive! ✅"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app_server.run(host='0.0.0.0', port=port)

# ---------- DATABASE ----------
conn = sqlite3.connect("posts.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS channels (channel_id INTEGER PRIMARY KEY, channel_name TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, photo_id TEXT, caption TEXT, time TEXT)")
conn.commit()

# ---------- CORE FUNCTIONS ----------
def get_main_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")], [InlineKeyboardButton("📋 My Channels", callback_data="list_channels")]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Bot Active! IST Timezone & Bold Support Ready.", reply_markup=get_main_keyboard())

# Scheduler Task
async def send_posts(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(IST).strftime("%H:%M")
    cur.execute("SELECT channel_id, photo_id, caption FROM posts WHERE time=?", (now,))
    for cid, pid, cap in cur.fetchall():
        try:
            await context.bot.send_photo(cid, pid, caption=f"*{cap}*", parse_mode=ParseMode.MARKDOWN)
        except Exception as e: print(f"Post Error: {e}")

# ---------- HANDLERS ----------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "main_menu":
        await query.message.edit_text("Main Menu:", reply_markup=get_main_keyboard())
    elif data == "add_channel":
        context.user_data["state"] = "waiting_for_channel"
        await query.message.edit_text("Channel @username bhejein:")
    elif data == "list_channels":
        cur.execute("SELECT channel_id, channel_name FROM channels")
        rows = cur.fetchall()
        if not rows: await query.message.edit_text("No channels.", reply_markup=get_main_keyboard())
        else:
            keyboard = [[InlineKeyboardButton(name, callback_data=f"ch_{cid}")] for cid, name in rows]
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
            await query.message.edit_text("Select Channel:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("ch_"):
        cid = int(data.split("_")[1])
        context.user_data["channel_id"] = cid
        await query.message.edit_text(f"Channel {cid} selected.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🖼 Add Post", callback_data="add_post")]]))
    elif data == "add_post":
        context.user_data["state"] = "waiting_for_photo"
        await query.message.edit_text("Photo bhejein (with caption):")

async def handle_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state == "waiting_for_channel":
        try:
            chat = await context.bot.get_chat(update.message.text)
            cur.execute("INSERT OR IGNORE INTO channels VALUES (?,?)", (chat.id, chat.title))
            conn.commit()
            await update.message.reply_text(f"✅ Added: {chat.title}", reply_markup=get_main_keyboard())
        except: await update.message.reply_text("❌ Error adding channel.")
    elif state == "waiting_for_time":
        try:
            time_val = update.message.text.strip()
            datetime.strptime(time_val, "%H:%M")
            cur.execute("INSERT INTO posts (channel_id, photo_id, caption, time) VALUES (?,?,?,?)",
                       (context.user_data["channel_id"], context.user_data["photo_id"], context.user_data["caption"], time_val))
            conn.commit()
            await update.message.reply_text(f"✅ Scheduled for {time_val} IST!")
        except: await update.message.reply_text("❌ Use HH:MM format.")
    context.user_data.clear()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") == "waiting_for_photo":
        context.user_data["photo_id"] = update.message.photo[-1].file_id
        context.user_data["caption"] = update.message.caption or ""
        context.user_data["state"] = "waiting_for_time"
        await update.message.reply_text("Time bhejein (HH:MM IST):")

# ---------- BOT STARTUP SETUP ----------
async def post_init(application):
    # Yeh scheduler ko bot ke loop ke andar hi start karega
    scheduler = AsyncIOScheduler(timezone=IST)
    scheduler.add_job(send_posts, "interval", minutes=1, args=[application])
    scheduler.start()

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN missing!")
        return

    # post_init ka use karke loop error khatam kiya gaya hai
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inputs))
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
