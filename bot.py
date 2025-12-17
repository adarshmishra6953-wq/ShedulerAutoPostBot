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

# ---------- SERVER ----------
app_server = Flask(__name__)
@app_server.route('/')
def health_check(): return "Bot is Alive! ✅"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app_server.run(host='0.0.0.0', port=port)

# ---------- DATABASE ----------
conn = sqlite3.connect("posts.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS channels (channel_id INTEGER PRIMARY KEY, channel_name TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, photo_id TEXT, caption TEXT, time TEXT)")
conn.commit()

# ---------- HANDLERS (START/BUTTONS/INPUTS) ----------
def get_main_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")], [InlineKeyboardButton("📋 My Channels", callback_data="list_channels")]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Bot is Ready! IST Timezone Active.", reply_markup=get_main_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    try:
        if data == "main_menu":
            await query.message.edit_text("Main Menu:", reply_markup=get_main_keyboard())
        elif data == "add_channel":
            context.user_data["state"] = "waiting_for_channel"
            await query.message.edit_text("Channel @username bhejein:")
        elif data == "list_channels":
            cur.execute("SELECT channel_id, channel_name FROM channels")
            rows = cur.fetchall()
            if not rows: await query.message.edit_text("Koi channel nahi hai.", reply_markup=get_main_keyboard())
            else:
                keyboard = [[InlineKeyboardButton(name, callback_data=f"ch_{cid}")] for cid, name in rows]
                keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
                await query.message.edit_text("Select Channel:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data.startswith("ch_"):
            cid = int(data.split("_")[1])
            context.user_data["channel_id"] = cid
            keyboard = [[InlineKeyboardButton("🖼 Add Post", callback_data="add_post")], [InlineKeyboardButton("🔙 Back", callback_data="list_channels")]]
            await query.message.edit_text(f"Manage Channel: {cid}", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data == "add_post":
            context.user_data["state"] = "waiting_for_photo"
            await query.message.edit_text("Photo bhejein (with caption):")
    except Exception as e: print(f"Error: {e}")

async def handle_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state == "waiting_for_channel":
        try:
            chat = await context.bot.get_chat(update.message.text)
            cur.execute("INSERT OR IGNORE INTO channels VALUES (?,?)", (chat.id, chat.title))
            conn.commit()
            await update.message.reply_text(f"✅ Added: {chat.title}", reply_markup=get_main_keyboard())
        except: await update.message.reply_text("❌ Username galat hai ya bot admin nahi hai.")
        context.user_data.clear()
    elif state == "waiting_for_time":
        try:
            time_val = update.message.text.strip()
            datetime.strptime(time_val, "%H:%M")
            cur.execute("INSERT INTO posts (channel_id, photo_id, caption, time) VALUES (?,?,?,?)",
                       (context.user_data["channel_id"], context.user_data["photo_id"], context.user_data["caption"], time_val))
            conn.commit()
            await update.message.reply_text(f"✅ Scheduled for {time_val} IST!")
        except: await update.message.reply_text("❌ Format HH:MM use karein.")
        context.user_data.clear()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") == "waiting_for_photo":
        context.user_data["photo_id"] = update.message.photo[-1].file_id
        context.user_data["caption"] = update.message.caption or ""
        context.user_data["state"] = "waiting_for_time"
        await update.message.reply_text("Time bhejein (HH:MM IST):")

# ---------- AUTO POSTER ----------
async def send_posts(app):
    now = datetime.now(IST).strftime("%H:%M")
    cur.execute("SELECT channel_id, photo_id, caption FROM posts WHERE time=?", (now,))
    for cid, pid, cap in cur.fetchall():
        try: await app.bot.send_photo(cid, pid, caption=f"*{cap}*", parse_mode=ParseMode.MARKDOWN)
        except Exception as e: print(f"Post Error: {e}")

# ---------- MAIN FUNCTION ----------
def main():
    # Start Web Server
    threading.Thread(target=run_web_server, daemon=True).start()
    
    if not BOT_TOKEN: return

    # App setup
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Scheduler Setup (Corrected Way)
    scheduler = AsyncIOScheduler(timezone=IST)
    scheduler.add_job(send_posts, "interval", minutes=1, args=[app])
    scheduler.start() # No loop error now

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inputs))
    
    print("Bot is Starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
