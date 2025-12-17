import os
import sqlite3
import threading
from datetime import datetime
import pytz
from flask import Flask
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

# ---------- CONFIG ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
IST = pytz.timezone('Asia/Kolkata')

# ---------- DATABASE SETUP ----------
conn = sqlite3.connect("posts.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS channels (channel_id INTEGER PRIMARY KEY, channel_name TEXT)")
cur.execute("""
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER,
    photo_id TEXT,
    caption TEXT,
    time TEXT
)
""")
conn.commit()

# ---------- WEB SERVER (For Render) ----------
app_server = Flask(__name__)
@app_server.route('/')
def health(): return "Bot is Running! ✅"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_server.run(host='0.0.0.0', port=port)

# ---------- KEYBOARDS ----------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_ch")],
        [InlineKeyboardButton("📋 My Channels", callback_data="list_ch")]
    ])

# ---------- AUTO POSTING LOGIC ----------
async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(IST).strftime("%H:%M")
    cur.execute("SELECT id, channel_id, photo_id, caption FROM posts WHERE time=?", (now,))
    for pid, cid, photo, cap in cur.fetchall():
        try:
            await context.bot.send_photo(chat_id=cid, photo=photo, caption=f"*{cap}*", parse_mode=ParseMode.MARKDOWN)
            print(f"✅ Posted at {now}")
        except Exception as e: print(f"❌ Error: {e}")

# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💎 *Advanced Auto-Post Bot Active*", reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "main":
        await query.message.edit_text("Main Menu:", reply_markup=main_menu())

    elif data == "add_ch":
        context.user_data['step'] = 'wait_ch'
        await query.message.edit_text("📩 Channel ka @username bhejein:")

    elif data == "list_ch":
        cur.execute("SELECT channel_id, channel_name FROM channels")
        rows = cur.fetchall()
        if not rows:
            await query.message.edit_text("❌ Koi channel nahi hai.", reply_markup=main_menu())
            return
        btns = [[InlineKeyboardButton(r[1], callback_data=f"manage_{r[0]}")] for r in rows]
        btns.append([InlineKeyboardButton("🔙 Back", callback_data="main")])
        await query.message.edit_text("Select Channel to Manage:", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("manage_"):
        cid = int(data.split("_")[1])
        context.user_data['cid'] = cid
        btns = [
            [InlineKeyboardButton("➕ Add New Post", callback_data="new_post")],
            [InlineKeyboardButton("📅 View/Delete Posts", callback_data=f"view_{cid}")],
            [InlineKeyboardButton("🔙 Back", callback_data="list_ch")]
        ]
        await query.message.edit_text(f"Channel ID: {cid}\nAction select karein:", reply_markup=InlineKeyboardMarkup(btns))

    elif data == "new_post":
        context.user_data['step'] = 'wait_photo'
        await query.message.edit_text("📸 Photo bhejein (Caption ke saath):")

    elif data.startswith("view_"):
        cid = int(data.split("_")[1])
        cur.execute("SELECT id, time FROM posts WHERE channel_id=?", (cid,))
        posts = cur.fetchall()
        if not posts:
            await query.message.edit_text("Is channel mein koi scheduled post nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"manage_{cid}")]]))
            return
        btns = [[InlineKeyboardButton(f"⏰ {p[1]}", callback_data=f"details_{p[0]}")] for p in posts]
        btns.append([InlineKeyboardButton("🔙 Back", callback_data=f"manage_{cid}")])
        await query.message.edit_text("Select a post to manage:", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("details_"):
        pid = int(data.split("_")[1])
        cur.execute("SELECT id, photo_id, caption, time, channel_id FROM posts WHERE id=?", (pid,))
        p = cur.fetchone()
        if p:
            btns = [
                [InlineKeyboardButton("📝 Edit Caption", callback_data=f"edit_{p[0]}")],
                [InlineKeyboardButton("🗑 Delete Post", callback_data=f"del_{p[0]}")],
                [InlineKeyboardButton("🔙 Back", callback_data=f"view_{p[4]}")]
            ]
            await query.message.delete()
            await context.bot.send_photo(query.message.chat_id, p[1], caption=f"⏰ *Time:* {p[3]}\n\n📝 *Caption:* {p[2]}", reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("edit_"):
        context.user_data['edit_id'] = data.split("_")[1]
        context.user_data['step'] = 'wait_edit'
        await context.bot.send_message(query.message.chat_id, "Naya caption likh kar bhejein:")

    elif data.startswith("del_"):
        pid = int(data.split("_")[1])
        cur.execute("DELETE FROM posts WHERE id=?", (pid,))
        conn.commit()
        await context.bot.send_message(query.message.chat_id, "✅ Post Deleted successfully!")
        await start(update, context)

# ---------- MESSAGE HANDLER ----------
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text

    if step == 'wait_ch':
        try:
            chat = await context.bot.get_chat(text)
            cur.execute("INSERT OR IGNORE INTO channels VALUES (?,?)", (chat.id, chat.title))
            conn.commit()
            await update.message.reply_text(f"✅ Channel Added: {chat.title}", reply_markup=main_menu())
        except: await update.message.reply_text("❌ Invalid @username. Bot ko Admin banayein.")
        
    elif step == 'wait_time':
        try:
            datetime.strptime(text, "%H:%M")
            cur.execute("INSERT INTO posts (channel_id, photo_id, caption, time) VALUES (?,?,?,?)",
                       (context.user_data['cid'], context.user_data['photo'], context.user_data['caption'], text))
            conn.commit()
            await update.message.reply_text(f"✅ Post scheduled for {text} IST!", reply_markup=main_menu())
        except: await update.message.reply_text("❌ Format: HH:MM use karein (e.g., 14:30)")

    elif step == 'wait_edit':
        pid = context.user_data['edit_id']
        cur.execute("UPDATE posts SET caption=? WHERE id=?", (text, pid))
        conn.commit()
        await update.message.reply_text("✅ Caption updated successfully!", reply_markup=main_menu())

    context.user_data['step'] = None

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('step') == 'wait_photo':
        context.user_data['photo'] = update.message.photo[-1].file_id
        context.user_data['caption'] = update.message.caption or ""
        context.user_data['step'] = 'wait_time'
        await update.message.reply_text("⏰ Time bhejein (HH:MM IST):")

# ---------- MAIN ----------
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Auto-post check every minute
    app.job_queue.run_repeating(auto_post_job, interval=60, first=10)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
