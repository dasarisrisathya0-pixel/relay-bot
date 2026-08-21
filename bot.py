"""
👑 ULTIMATE PRIVATE RELAY BOT - RENDER EDITION (FINAL WORKING VERSION 9)
"""
import logging
import sqlite3
import os
import time
import json
import asyncio
import re
from datetime import datetime
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# CONFIGURATION
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8806058859:AAFp6hmI5j1Oj6MH9fJCTr1PDYh9PQOyaFw')
ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_ID', '6024704351').split(',')]

DB_NAME = 'relay_bot.db'
FILES_DIR = 'received_files'
os.makedirs(FILES_DIR, exist_ok=True)

SPAM_LIMIT = 10
SPAM_WINDOW = 60

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# DATABASE SETUP
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

def save_message(user_id, chat_id, message_type, content, file_path=None):
    db_execute('''INSERT INTO messages (user_id, chat_id, message_type, content, file_path)
                  VALUES (?, ?, ?, ?, ?)''',
               (user_id, chat_id, message_type, content, file_path))

def get_all_users():
    return db_execute('SELECT user_id, chat_id, first_name, username, is_blocked FROM users')

def is_blocked(user_id):
    row = db_get_one('SELECT is_blocked FROM users WHERE user_id = ?', (user_id,))
    return row and row[0] == 1

# START COMMAND
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user(user.id, chat_id, user.first_name, user.username)
    
    if user.id in ADMIN_IDS:
        keyboard = [
            [InlineKeyboardButton("📊 Stats", callback_data='stats')],
            [InlineKeyboardButton("👥 Users", callback_data='users')],
            [InlineKeyboardButton("📢 Broadcast", callback_data='broadcast')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"👑 Welcome back, Admin {user.first_name}!\n\nBot is running.",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "👋 Hello! Welcome to the Private Relay Bot.\n\n"
            "You can send me any type of message. All messages are private."
        )

# HANDLE ALL MESSAGES
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message
    
    save_user(user.id, chat_id, user.first_name, user.username)
    
    if is_blocked(user.id):
        await update.message.reply_text("⛔ You are blocked from using this bot.")
        return
    
    if user.id in ADMIN_IDS:
        await handle_admin_message(update, context)
        return
    
    await forward_to_admin(update, context)

# FORWARD TO ADMIN
async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message
    message_type = "text"
    content = message.text or ""
    
    if message.photo:
        message_type = "photo"
        content = "Photo"
    elif message.video:
        message_type = "video"
        content = "Video"
    elif message.document:
        message_type = "document"
        content = f"Document: {message.document.file_name}"
    elif message.voice:
        message_type = "voice"
        content = "Voice message"
    elif message.sticker:
        message_type = "sticker"
        content = "Sticker"
    
    save_message(user.id, chat_id, message_type, content)
    
    admin_text = (
        f"📨 New Message from {user.first_name} (@{user.username})\n"
        f"🆔 ID: {user.id}\n"
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
    
    await update.message.reply_text("✅ Message delivered to admin.")

# HANDLE ADMIN MESSAGES (FIXED)
async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    
    # If admin uses /reply command
    if message.text and message.text.startswith('/reply'):
        parts = message.text.split()
        if len(parts) < 3:
            await message.reply_text("Usage: /reply <user_id> <message>")
            return
        
        target_id = int(parts[1])
        reply_text = ' '.join(parts[2:])
        
        target_chat_id = db_get_one('SELECT chat_id FROM users WHERE user_id = ?', (target_id,))
        if not target_chat_id:
            await message.reply_text("❌ User not found in database.")
            return
        
        try:
            await context.bot.send_message(chat_id=target_chat_id[0], text=reply_text)
            await message.reply_text("✅ Reply sent to user.")
        except Exception as e:
            await message.reply_text(f"❌ Failed: {e}")
        return
    
    # If admin replies to a forwarded message (using reply button)
    if message.reply_to_message:
        forwarded_msg = message.reply_to_message
        target_user_id = None
        
        # Check if the replied message is a forwarded message
        if hasattr(forwarded_msg, 'forward_from') and forwarded_msg.forward_from:
            target_user_id = forwarded_msg.forward_from.id
        elif hasattr(forwarded_msg, 'forward_from_chat') and forwarded_msg.forward_from_chat:
            target_user_id = forwarded_msg.forward_from_chat.id
        
        # If still not found, look for "ID: xxxx" in the text
        if target_user_id is None and forwarded_msg.text:
            match = re.search(r'ID: (\d+)', forwarded_msg.text)
            if match:
                target_user_id = int(match.group(1))
        
        if target_user_id is None:
            await message.reply_text("❌ Could not find user ID. Use /reply <user_id> <message>")
            return
        
        target_chat_id = db_get_one('SELECT chat_id FROM users WHERE user_id = ?', (target_user_id,))
        if not target_chat_id:
            await message.reply_text("❌ User not found in database.")
            return
        
        target_chat_id = target_chat_id[0]
        
        try:
            # Send admin's reply to the user
            await context.bot.send_message(chat_id=target_chat_id, text=message.text or "Reply from admin")
            await message.reply_text("✅ Reply sent to user.")
        except Exception as e:
            await message.reply_text(f"❌ Failed: {e}")
        return
    
    # If admin types a regular command
    if message.text and message.text.startswith('/'):
        await handle_admin_command(update, context)
        return
    
    # If admin sends a message without replying
    await message.reply_text("To reply to a user, reply to their forwarded message.")

# ADMIN COMMANDS
async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    text = message.text
    command = text.split()[0].lower()
    
    if command == '/help':
        await message.reply_text("Commands:\n/stats - Show stats\n/users - List users\n/broadcast <msg> - Send to all\n/reply <user_id> <msg> - Reply to user\n/block <id> - Block user\n/unblock <id> - Unblock user")
    
    elif command == '/stats':
        total_users = db_get_one('SELECT COUNT(*) FROM users')[0]
        total_messages = db_get_one('SELECT COUNT(*) FROM messages')[0]
        await message.reply_text(f"📊 Total Users: {total_users}\n💬 Total Messages: {total_messages}")
    
    elif command == '/users':
        users = get_all_users()
        if not users:
            await message.reply_text("No users yet.")
            return
        user_list = "📋 Users:\n"
        for uid, chat_id, first_name, username, is_blocked in users:
            status = "🚫" if is_blocked else "✅"
            user_list += f"{status} {first_name} (@{username}) - {uid}\n"
        await message.reply_text(user_list)
    
    elif command == '/reply':
        if len(context.args) < 2:
            await message.reply_text("Usage: /reply <user_id> <message>")
            return
        target_id = int(context.args[0])
        reply_text = ' '.join(context.args[1:])
        target_chat_id = db_get_one('SELECT chat_id FROM users WHERE user_id = ?', (target_id,))
        if not target_chat_id:
            await message.reply_text("❌ User not found.")
            return
        try:
            await context.bot.send_message(chat_id=target_chat_id[0], text=reply_text)
            await message.reply_text("✅ Reply sent.")
        except Exception as e:
            await message.reply_text(f"❌ Failed: {e}")
    
    elif command == '/broadcast':
        if len(context.args) < 1:
            await message.reply_text("Usage: /broadcast <message>")
            return
        broadcast_text = ' '.join(context.args)
        users = get_all_users()
        sent = 0
        for uid, chat_id, first_name, username, is_blocked in users:
            if not is_blocked:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=f"📢 {broadcast_text}")
                    sent += 1
                except:
                    pass
        await message.reply_text(f"✅ Sent to {sent} users.")
    
    else:
        await message.reply_text("Unknown command. Use /help.")

# CALLBACK BUTTONS
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
            user_list += f"✅ {first_name} (@{username}) - {uid}\n"
        await query.edit_message_text(user_list)
    
    elif query.data == 'broadcast':
        await query.edit_message_text("Use /broadcast <message> to send to all users.")

# FLASK WEB SERVER
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is running!"

def start_polling():
    async def run_bot():
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler('start', start))
        telegram_app.add_handler(MessageHandler(filters.ALL, handle_message))
        telegram_app.add_handler(CallbackQueryHandler(button_handler))
        
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        await asyncio.Event().wait()
    
    asyncio.run(run_bot())

# INIT DATABASE AT MODULE LOAD
init_db()

# START POLLING AT MODULE LOAD
polling_thread = Thread(target=start_polling)
polling_thread.daemon = True
polling_thread.start()

# RUN FLASK
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
