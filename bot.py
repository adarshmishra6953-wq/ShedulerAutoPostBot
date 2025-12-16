import os
import sqlite3
import threading
from flask import Flask
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

# ---------- BOT TOKEN CONFIG ----------
# Render ke environment variables mein BOT_TOKEN naam se token zarur daalein
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ---------- FAKE SERVER (For Render) ----------
app_server = Flask(__name__)
@app_server.route('/')
def health_check(): return "Bot is Alive! ✅"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app_server.run(host='0.0.0.0', port=port)

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

# ---------- MENU KEYBOARDS ----------
def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")],
        [InlineKeyboardButton("📋 My Channels", callback_data="list_channels")]
    ])

# ---------- START COMMAND ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to Sheduler Auto Post Bot!\n\nNiche diye gaye buttons se bot ko control karein:", reply_markup=get_main_keyboard())

# ---------- MAIN BUTTON HANDLER ----------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "main_menu":
        await query.message.edit_text("Main Menu:", reply_markup=get_main_keyboard())

    elif data == "add_channel":
        context.user_data["state"] = "waiting_for_channel"
        await query.message.edit_text("Us Channel ka @username bhejein jisme bot admin hai:", 
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]))

    elif data == "list_channels":
        cur.execute("SELECT channel_id, channel_name FROM channels")
        rows = cur.fetchall()
        if not rows:
            await query.message.edit_text("Koi channel nahi mila. Pehle channel add karein.", reply_markup=get_main_keyboard())
            return
        keyboard = [[InlineKeyboardButton(name, callback_data=f"ch_{cid}")] for cid, name in rows]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
        await query.message.edit_text("Apna Channel select karein:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("ch_"):
        cid = int(data.split("_")[1])
        context.user_data["channel_id"] = cid
        keyboard = [
            [InlineKeyboardButton("🖼 Add New Post", callback_data="add_post")],
            [InlineKeyboardButton("📅 Manage Posts", callback_data=f"manage_{cid}")],
            [InlineKeyboardButton("🔙 Back", callback_data="list_channels")]
        ]
        await query.message.edit_text(f"Settings for Channel ID: {cid}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "add_post":
        context.user_data["state"] = "waiting_for_photo"
        await query.message.edit_text("Photo bhejein (aap caption bhi saath mein bhej sakte hain):", 
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"ch_{context.user_data['channel_id']}")]]))

    elif data.startswith("manage_"):
        cid = int(data.split("_")[1])
        cur.execute("SELECT id, time FROM posts WHERE channel_id=?", (cid,))
        posts = cur.fetchall()
        if not posts:
            await query.message.edit_text("Is channel mein koi post scheduled nahi hai.", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"ch_{cid}")]]))
            return
        keyboard = [[InlineKeyboardButton(f"⏰ Time: {p[1]}", callback_data=f"view_{p[0]}")] for p in posts]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"ch_{cid}")])
        await query.message.edit_text("Aapki Scheduled Posts niche hain (click to edit/delete):", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("view_"):
        pid = int(data.split("_")[1])
        cur.execute("SELECT photo_id, caption, time, channel_id FROM posts WHERE id=?", (pid,))
        p = cur.fetchone()
        if p:
            keyboard = [
                [InlineKeyboardButton("🕒 Change Time", callback_data=f"edittime_{pid}")],
                [InlineKeyboardButton("🗑 Delete Post", callback_data=f"del_{pid}")],
                [InlineKeyboardButton("🔙 Back", callback_data=f"manage_{p[3]}")]
            ]
            await query.message.delete()
            await context.bot.send_photo(chat_id=query.message.chat_id, photo=p[0], 
                                       caption=f"📋 Post Details:\n\n⏰ Time: {p[2]}\n📝 Caption: {p[1]}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("del_"):
        pid = int(data.split("_")[1])
        cur.execute("SELECT channel_id FROM posts WHERE id=?", (pid,))
        row = cur.fetchone()
        if row:
            cid = row[0]
            cur.execute("DELETE FROM posts WHERE id=?", (pid,))
            conn.commit()
            await query.message.delete()
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Post successfully deleted!", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"manage_{cid}")]]))

    elif data.startswith("edittime_"):
        pid = int(data.split("_")[1])
        context.user_data["edit_post_id"] = pid
        context.user_data["state"] = "waiting_for_new_time"
        await query.message.delete()
        await context.bot.send_message(chat_id=query.message.chat_id, text="Naya time bhejein (HH:MM format mein):\nExample: 14:30")

# ---------- INPUT HANDLERS (TEXT/PHOTO) ----------
async def handle_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    
    if state == "waiting_for_channel":
        try:
            chat = await context.bot.get_chat(update.message.text)
            cur.execute("INSERT OR IGNORE INTO channels VALUES (?,?)", (chat.id, chat.title))
            conn.commit()
            await update.message.reply_text(f"✅ Channel Added: {chat.title}", reply_markup=get_main_keyboard())
        except:
            await update.message.reply_text("❌ Error! Bot channel mein admin hona chahiye ya username galat hai.")
        context.user_data.clear()

    elif state == "waiting_for_new_time":
        try:
            new_time = update.message.text.strip()
            datetime.strptime(new_time, "%H:%M")
            cur.execute("UPDATE posts SET time=? WHERE id=?", (new_time, context.user_data["edit_post_id"]))
            conn.commit()
            await update.message.reply_text(f"✅ Time successfully updated to {new_time}!", reply_markup=get_main_keyboard())
        except:
            await update.message.reply_text("❌ Format galat hai. Kripya HH:MM format use karein (e.g. 21:15).")
        context.user_data.clear()

    elif state == "waiting_for_time":
        try:
            time_val = update.message.text.strip()
            datetime.strptime(time_val, "%H:%M")
            cur.execute("INSERT INTO posts (channel_id, photo_id, caption, time) VALUES (?,?,?,?)",
                       (context.user_data["channel_id"], context.user_data["photo_id"], context.user_data["caption"], time_val))
            conn.commit()
            await update.message.reply_text(f"✅ Post scheduled for {time_val} daily!", reply_markup=get_main_keyboard())
        except:
            await update.message.reply_text("❌ Format galat hai. Kripya HH:MM use karein.")
        context.user_data.clear()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") == "waiting_for_photo":
        context.user_data["photo_id"] = update.message.photo[-1].file_id
        context.user_data["caption"] = update.message.caption or ""
        context.user_data["state"] = "waiting_for_time"
        await update.message.reply_text("Photo mil gayi! Ab is post ke liye Time bhejein (HH:MM format):\nExample: 10:00")

# ---------- AUTOMATED SCHEDULER ----------
async def send_posts(app):
    now = datetime.now().strftime("%H:%M")
    cur.execute("SELECT channel_id, photo_id, caption FROM posts WHERE time=?", (now,))
    posts_to_send = cur.fetchall()
    for cid, pid, cap in posts_to_send:
        try: 
            await app.bot.send_photo(cid, pid, caption=cap)
            print(f"Successfully posted to {cid} at {now}")
        except Exception as e: 
            print(f"Failed to post to {cid}: {e}")

# ---------- MAIN FUNCTION ----------
def main():
    # Render compatibility: Start Web Server
    threading.Thread(target=run_web_server, daemon=True).start()
    
    if not BOT_TOKEN:
        print("CRITICAL ERROR: BOT_TOKEN is not set!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Schedule posts checking every 1 minute
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_posts, "interval", minutes=1, args=[app])
    scheduler.start()

    # Handlers Registration
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inputs))
    
    print("Bot is starting polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
