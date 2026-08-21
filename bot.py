"""
👑 ULTIMATE PRIVATE RELAY BOT — DEPLOYED ON RENDER (FIXED VERSION)
"""
import logging
import sqlite3
import os
import time
import json
from datetime import datetime
from flask import Flask, request
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ──────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8806058859:AAFp6hmI5j1Oj6MH9fJCTr1PDYh9PQOyaFw')
ADMIN_IDS = [int(os.environ.get('ADMIN_ID', '6024704351'))]

DB_NAME = 'relay_bot.db'
FILES_DIR = 'received_files'
os.makedirs(FILES_DIR, exist_ok=True)

SPAM_LIMIT = 10
SPAM_WINDOW = 60

# ──────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# DATABASE SETUP
# ──────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  chat_id INTEGER,
                  first_name TEXT,
                  username TEXT,
                  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  is_blocked INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  chat_id INTEGER,
                  message_type TEXT,
                  content TEXT,
                  file_path TEXT,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS auto_replies
                 (keyword TEXT PRIMARY KEY,
                  response TEXT)''')
    
    conn.commit()
    conn.close()

def db_execute(query, params=()):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    result = c.fetchall()
    conn.close()
    return result

def db_get_one(query, params=()):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, params)
    result = c.fetchone()
    conn.close()
    return result

def save_user(user_id, chat_id, first_name, username):
    db_execute('''INSERT OR REPLACE INTO users (user_id, chat_id, first_name, username, last_active)
                  VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
               (user_id, chat_id, first_name, username))

def update_last_active(user_id):
    db_execute('UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))

def save_message(user_id, chat_id, message_type, content, file_path=None):
    db_execute('''INSERT INTO messages (user_id, chat_id, message_type, content, file_path)
                  VALUES (?, ?, ?, ?, ?)''',
               (user_id, chat_id, message_type, content, file_path))

def get_user_messages(user_id, limit=50):
    return db_execute('''SELECT message_type, content, file_path, timestamp 
                         FROM messages WHERE user_id = ? 
                         ORDER BY timestamp DESC LIMIT ?''', (user_id, limit))

def get_all_users():
    return db_execute('SELECT user_id, chat_id, first_name, username, is_blocked FROM users')

def set_block_status(user_id, blocked):
    db_execute('UPDATE users SET is_blocked = ? WHERE user_id = ?', (1 if blocked else 0, user_id))

def is_blocked(user_id):
    row = db_get_one('SELECT is_blocked FROM users WHERE user_id = ?', (user_id,))
    return row and row[0] == 1

# ──────────────────────────────────────────
# ANTI-SPAM
# ──────────────────────────────────────────
user_message_times = {}

def check_spam(user_id):
    now = time.time()
    if user_id not in user_message_times:
        user_message_times[user_id] = []
    
    user_message_times[user_id] = [t for t in user_message_times[user_id] if now - t < SPAM_WINDOW]
    
    if len(user_message_times[user_id]) >= SPAM_LIMIT:
        return False
    
    user_message_times[user_id].append(now)
    return True

# ──────────────────────────────────────────
# AUTO-REPLY
# ──────────────────────────────────────────
def get_auto_reply(message_text):
    templates = db_execute('SELECT keyword, response FROM auto_replies')
    for keyword, response in templates:
        if keyword.lower() in message_text.lower():
            return response
    return None

def add_auto_reply(keyword, response):
    db_execute('INSERT OR REPLACE INTO auto_replies (keyword, response) VALUES (?, ?)', (keyword, response))

# ──────────────────────────────────────────
# START COMMAND
# ──────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    save_user(user.id, chat_id, user.first_name, user.username)
    update_last_active(user.id)
    
    if is_blocked(user.id):
        await update.message.reply_text("⛔ You are blocked from using this bot.")
        return
    
    if user.id in ADMIN_IDS:
        keyboard = [
            [InlineKeyboardButton("📊 Stats", callback_data='stats')],
            [InlineKeyboardButton("👥 Users", callback_data='users')],
            [InlineKeyboardButton("📢 Broadcast", callback_data='broadcast')],
            [InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
            [InlineKeyboardButton("📁 Files", callback_data='files')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"👑 Welcome back, Admin {user.first_name}!\n\n"
            f"Bot is running. All messages from users will be forwarded to you.",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "👋 Hello! Welcome to the Private Relay Bot.\n\n"
            "You can send me any type of message — text, photos, videos, files, audio, voice, location, contacts, etc.\n"
            "All your messages are completely private and only visible to the admin.\n\n"
            "You will receive replies directly from the admin.\n"
            "Thank you!"
        )

# ──────────────────────────────────────────
# HANDLE ALL MESSAGES
# ──────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message
    
    save_user(user.id, chat_id, user.first_name, user.username)
    update_last_active(user.id)
    
    if is_blocked(user.id):
        await update.message.reply_text("⛔ You are blocked from using this bot.")
        return
    
    if user.id in ADMIN_IDS:
        await handle_admin_message(update, context)
        return
    
    if not check_spam(user.id):
        await update.message.reply_text("⛔ Too many messages! Please wait a minute.")
        return
    
    if message.text:
        auto_reply = get_auto_reply(message.text)
        if auto_reply:
            await update.message.reply_text(auto_reply)
            await forward_to_admin(update, context)
            return
    
    await forward_to_admin(update, context)

# ──────────────────────────────────────────
# FORWARD TO ADMIN
# ──────────────────────────────────────────
async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message
    
    message_type = "text"
    content = message.text or ""
    file_path = None
    
    if message.photo:
        message_type = "photo"
        content = "Photo received"
        file_id = message.photo[-1].file_id
        file = await context.bot.get_file(file_id)
        file_path = f"{FILES_DIR}/{user.id}_{int(time.time())}.jpg"
        await file.download_to_drive(file_path)
    elif message.video:
        message_type = "video"
        content = "Video received"
        file_id = message.video.file_id
        file = await context.bot.get_file(file_id)
        file_path = f"{FILES_DIR}/{user.id}_{int(time.time())}.mp4"
        await file.download_to_drive(file_path)
    elif message.document:
        message_type = "document"
        content = f"Document: {message.document.file_name}"
        file_id = message.document.file_id
        file = await context.bot.get_file(file_id)
        file_path = f"{FILES_DIR}/{user.id}_{int(time.time())}_{message.document.file_name}"
        await file.download_to_drive(file_path)
    elif message.audio:
        message_type = "audio"
        content = "Audio received"
        file_id = message.audio.file_id
        file = await context.bot.get_file(file_id)
        file_path = f"{FILES_DIR}/{user.id}_{int(time.time())}.mp3"
        await file.download_to_drive(file_path)
    elif message.voice:
        message_type = "voice"
        content = "Voice message received"
        file_id = message.voice.file_id
        file = await context.bot.get_file(file_id)
        file_path = f"{FILES_DIR}/{user.id}_{int(time.time())}.ogg"
        await file.download_to_drive(file_path)
    elif message.sticker:
        message_type = "sticker"
        content = "Sticker received"
    elif message.location:
        message_type = "location"
        content = f"Location: {message.location.latitude}, {message.location.longitude}"
    elif message.contact:
        message_type = "contact"
        content = f"Contact: {message.contact.first_name} {message.contact.last_name} - {message.contact.phone_number}"
    elif message.animation:
        message_type = "animation"
        content = "GIF/Animation received"
        file_id = message.animation.file_id
        file = await context.bot.get_file(file_id)
        file_path = f"{FILES_DIR}/{user.id}_{int(time.time())}.gif"
        await file.download_to_drive(file_path)
    elif message.poll:
        message_type = "poll"
        content = f"Poll: {message.poll.question}"
    else:
        message_type = "unknown"
        content = "Unknown message type"
    
    save_message(user.id, chat_id, message_type, content, file_path)
    
    admin_text = (
        f"📨 New Message from {user.first_name} (@{user.username})\n"
        f"🆔 ID: {user.id}\n"
        f"📱 Chat ID: {chat_id}\n"
        f"📝 Type: {message_type}\n"
        f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{content}"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_text)
            await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=chat_id,
                message_id=message.message_id
            )
        except Exception as e:
            logger.error(f"Failed to send to admin {admin_id}: {e}")
    
    await update.message.reply_text("✅ Message delivered to admin. You will get a reply soon.")

# ──────────────────────────────────────────
# HANDLE ADMIN MESSAGES
# ──────────────────────────────────────────
async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    
    if message.reply_to_message:
        forwarded_msg = message.reply_to_message
        
        target_user_id = None
        if forwarded_msg.forward_from:
            target_user_id = forwarded_msg.forward_from.id
        elif forwarded_msg.forward_from_chat:
            target_user_id = forwarded_msg.forward_from_chat.id
        
        if target_user_id is None:
            rows = db_execute('SELECT user_id FROM users ORDER BY last_active DESC LIMIT 1')
            if rows:
                target_user_id = rows[0][0]
        
        if target_user_id is None:
            await message.reply_text("❌ Could not identify the user.")
            return
        
        target_chat_id = db_get_one('SELECT chat_id FROM users WHERE user_id = ?', (target_user_id,))
        if not target_chat_id:
            await message.reply_text("❌ User not found in database.")
            return
        
        target_chat_id = target_chat_id[0]
        
        try:
            await context.bot.forward_message(
                chat_id=target_chat_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            await message.reply_text("✅ Reply sent to user.")
        except Exception as e:
            await message.reply_text(f"❌ Failed to send reply: {e}")
        return
    
    if message.text and message.text.startswith('/'):
        await handle_admin_command(update, context)
        return
    
    await message.reply_text("To reply to a user, reply to their forwarded message.")

# ──────────────────────────────────────────
# ADMIN COMMANDS
# ──────────────────────────────────────────
async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    text = message.text
    command = text.split()[0].lower()
    
    if command == '/stats':
        total_users = db_get_one('SELECT COUNT(*) FROM users')[0]
        total_messages = db_get_one('SELECT COUNT(*) FROM messages')[0]
        blocked_users = db_get_one('SELECT COUNT(*) FROM users WHERE is_blocked = 1')[0]
        await message.reply_text(
            f"📊 **Bot Statistics**\n\n"
            f"👥 Total Users: {total_users}\n"
            f"💬 Total Messages: {total_messages}\n"
            f"🚫 Blocked Users: {blocked_users}",
            parse_mode='Markdown'
        )
    
    elif command == '/users':
        users = get_all_users()
        if not users:
            await message.reply_text("No users yet.")
            return
        user_list = "📋 **Registered Users:**\n\n"
        for uid, chat_id, first_name, username, is_blocked in users:
            status = "🚫" if is_blocked else "✅"
            user_list += f"{status} **{first_name}** (@{username}) — ID: {uid}\n"
        await message.reply_text(user_list, parse_mode='Markdown')
    
    elif command == '/broadcast':
        if len(context.args) < 1:
            await message.reply_text("Usage: /broadcast <message>")
            return
        broadcast_text = ' '.join(context.args)
        users = get_all_users()
        sent_count = 0
        for uid, chat_id, first_name, username, is_blocked in users:
            if is_blocked:
                continue
            try:
                await context.bot.send_message(chat_id=chat_id, text=f"📢 **Broadcast from Admin:**\n\n{broadcast_text}", parse_mode='Markdown')
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send to {uid}: {e}")
        await message.reply_text(f"✅ Broadcast sent to {sent_count} users.")
    
    elif command == '/block':
        if len(context.args) < 1:
            await message.reply_text("Usage: /block <user_id>")
            return
        target_id = int(context.args[0])
        set_block_status(target_id, True)
        await message.reply_text(f"✅ User {target_id} has been blocked.")
    
    elif command == '/unblock':
        if len(context.args) < 1:
            await message.reply_text("Usage: /unblock <user_id>")
            return
        target_id = int(context.args[0])
        set_block_status(target_id, False)
        await message.reply_text(f"✅ User {target_id} has been unblocked.")
    
    elif command == '/delete':
        if len(context.args) < 1:
            await message.reply_text("Usage: /delete <user_id>")
            return
        target_id = int(context.args[0])
        db_execute('DELETE FROM users WHERE user_id = ?', (target_id,))
        await message.reply_text(f"✅ User {target_id} has been deleted.")
    
    elif command == '/messages':
        if len(context.args) < 1:
            await message.reply_text("Usage: /messages <user_id>")
            return
        target_id = int(context.args[0])
        messages = get_user_messages(target_id, limit=20)
        if not messages:
            await message.reply_text("No messages found for this user.")
            return
        msg_list = f"📜 **Recent Messages from User {target_id}:**\n\n"
        for msg_type, content, file_path, timestamp in messages:
            msg_list += f"**{msg_type}** ({timestamp}): {content}\n"
            if file_path:
                msg_list += f"   📁 File: {file_path}\n"
        await message.reply_text(msg_list, parse_mode='Markdown')
    
    elif command == '/addreply':
        if len(context.args) < 2:
            await message.reply_text("Usage: /addreply <keyword> <response>")
            return
        keyword = context.args[0]
        response = ' '.join(context.args[1:])
        add_auto_reply(keyword, response)
        await message.reply_text(f"✅ Auto-reply added: '{keyword}' -> '{response}'")
    
    elif command == '/export':
        users = get_all_users()
        messages = db_execute('SELECT * FROM messages')
        export_data = {
            'users': users,
            'messages': messages,
            'exported_at': datetime.now().isoformat()
        }
        with open('export.json', 'w') as f:
            json.dump(export_data, f, indent=4, default=str)
        await message.reply_text("✅ Data exported to `export.json`", parse_mode='Markdown')
    
    elif command == '/help':
        help_text = (
            "🛠️ **Admin Commands:**\n\n"
            "/stats — Show bot statistics\n"
            "/users — List all users\n"
            "/broadcast <msg> — Send message to all users\n"
            "/block <user_id> — Block a user\n"
            "/unblock <user_id> — Unblock a user\n"
            "/delete <user_id> — Delete a user from database\n"
            "/messages <user_id> — View user's message history\n"
            "/addreply <keyword> <response> — Add auto-reply template\n"
            "/export — Export all data to JSON file\n"
            "/help — Show this help menu"
        )
        await message.reply_text(help_text, parse_mode='Markdown')
    
    else:
        await message.reply_text("Unknown command. Use /help for the list of commands.")

# ──────────────────────────────────────────
# CALLBACK BUTTONS
# ──────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'stats':
        total_users = db_get_one('SELECT COUNT(*) FROM users')[0]
        total_messages = db_get_one('SELECT COUNT(*) FROM messages')[0]
        await query.edit_message_text(f"📊 Total Users: {total_users}\n💬 Total Messages: {total_messages}")
    
    elif query.data == 'users':
        users = get_all_users()
        if not users:
            await query.edit_message_text("No users yet.")
            return
        user_list = "📋 Users:\n"
        for uid, chat_id, first_name, username, is_blocked in users[:10]:
            status = "🚫" if is_blocked else "✅"
            user_list += f"{status} {first_name} (@{username}) — {uid}\n"
        await query.edit_message_text(user_list)
    
    elif query.data == 'broadcast':
        await query.edit_message_text("Use /broadcast <message> to send a message to all users.")
    
    elif query.data == 'settings':
        await query.edit_message_text("Settings: Use /block, /unblock, /delete, /addreply commands.")
    
    elif query.data == 'files':
        files = os.listdir(FILES_DIR)
        if not files:
            await query.edit_message_text("No files received yet.")
            return
        file_list = "\n".join(files[:20])
        await query.edit_message_text(f"📁 Received Files:\n{file_list}")

# ──────────────────────────────────────────
# FLASK WEB SERVER (FOR RENDER)
# ──────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is running! 24/7 on Render. ✅"

def start_polling():
    global telegram_app
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler('start', start))
    telegram_app.add_handler(MessageHandler(filters.ALL, handle_message))
    telegram_app.add_handler(CallbackQueryHandler(button_handler))
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)

# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    
    # Start bot polling in background thread
    polling_thread = Thread(target=start_polling)
    polling_thread.daemon = True
    polling_thread.start()
    
    # Start Flask web server
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
