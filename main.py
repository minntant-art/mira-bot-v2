# -*- coding: utf-8 -*-
import os
import gspread
import json
import random
import logging
import pytz
import asyncio
from datetime import datetime, time, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler
)
from flask import Flask
from threading import Thread

# --- Flask Web Server Setup (for Render Free Tier) ---
app = Flask('')

@app.route('/')
def home():
    return "MiraNotification Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def start_web_server():
    t = Thread(target=run_flask)
    t.start()

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "MiraNotificationDB")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")

# --- Conversation States ---
RELAPSE_REASON, LOG_MOOD, LOG_REASON, SETTINGS_MORNING, SETTINGS_NIGHT = range(5)

# --- Logging setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- GOOGLE SHEETS SETUP ---
users_sheet = None
log_sheet = None
mood_sheet = None
try:
    if not GOOGLE_CREDENTIALS_JSON:
        logger.error("GOOGLE_CREDENTIALS secret is not set!")
    else:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        gc = gspread.service_account_from_dict(creds_dict)
        spreadsheet = gc.open(GOOGLE_SHEET_NAME)

        # "Users" sheet: Chat_ID, Username, Last_Sober_Date, Morning_Time, Night_Time, Checked_In_Today
        try:
            users_sheet = spreadsheet.worksheet("Users")
        except gspread.exceptions.WorksheetNotFound:
            users_sheet = spreadsheet.add_worksheet(title="Users", rows="100", cols="6")
            users_sheet.append_row(["Chat_ID", "Username", "Last_Sober_Date", "Morning_Time", "Night_Time", "Checked_In_Today"])
        
        # "Log" sheet for relapses
        try:
            log_sheet = spreadsheet.worksheet("Log")
        except gspread.exceptions.WorksheetNotFound:
            log_sheet = spreadsheet.add_worksheet(title="Log", rows="1000", cols="4")
            log_sheet.append_row(["Timestamp", "Chat_ID", "Username", "Relapse_Reason"])

        # "MoodLog" sheet for mood tracking
        try:
            mood_sheet = spreadsheet.worksheet("MoodLog")
        except gspread.exceptions.WorksheetNotFound:
            mood_sheet = spreadsheet.add_worksheet(title="MoodLog", rows="1000", cols="4")
            mood_sheet.append_row(["Timestamp", "Chat_ID", "Mood", "Craving_Reason"])

        logger.info("Successfully connected to Google Sheets.")
except Exception as e:
    logger.error(f"An error occurred during Google Sheets setup: {e}")

# --- MESSAGE POOLS ---
motivateMessages = [
    "You've come so far—one more alcohol-free day makes your mind stronger. 💪",
    "Remember why you started. That reason is more powerful than any craving. ✨",
    "Every day you choose not to drink, you are healing. Be proud of that. 🌱",
    "This moment will pass. Stay strong, and you'll wake up grateful tomorrow. 🌅"
]
focusMessages = [
    "Breathe in for 4 seconds, hold for 4, and breathe out for 6. Repeat 5 times. You are in control. 🌬️",
    "Find a quiet spot. Close your eyes and name 3 things you can hear. It brings you back to the present moment. 🧘",
    "Splash some cold water on your face. It's a simple pattern interrupt that can reset your mind. 💧"
]
rewardMessages = [
    "Treat yourself to your favorite meal tonight. You've earned it! 🍕",
    "Watch that movie you've been wanting to see. Relax and enjoy. 🎬",
    "Go for a walk and listen to a podcast or your favorite music. 🎧",
    "Buy that book you've had your eye on. A reward for your mind. 📚"
]
cravingSupportMessages = [
    "It's okay to feel this way. The feeling is temporary. Can you try a focus exercise with /focus? ✨",
    "I hear you. Remember the last time you felt great waking up without a hangover? Let's aim for that again. 🌅",
    "This is tough, but you are tougher. Let's get through this moment together. 💪"
]
celebrationMessages = [
    "That's amazing to hear! 🎉 Celebrating this positive feeling with you.",
    "So happy for you! Keep embracing these good moments. ✨",
    "Wonderful! Every good day is a huge win. 🥳"
]
noJudgmentMessages = [
    "It's okay. This is a journey with ups and downs. What matters is that you're back. Let's start again, together. 🌱",
    "No judgment here. Recovery isn't a straight line. Be kind to yourself today. We'll take it one day at a time. ❤️"
]

# --- HELPER FUNCTIONS (FINAL FIX)---
def get_user(chat_id):
    if not users_sheet: return None
    try:
        cell = users_sheet.find(str(chat_id))
        if cell:
            return users_sheet.row_values(cell.row)
        return None
    except (gspread.exceptions.CellNotFound, AttributeError):
        return None

def create_or_update_user(chat_id, username):
    if not users_sheet: return None
    try:
        cell = users_sheet.find(str(chat_id))
        if cell:
            users_sheet.update_cell(cell.row, 2, username or "")
            return cell.row
        else: # New user
            raise gspread.exceptions.CellNotFound
    except gspread.exceptions.CellNotFound:
        today_str = datetime.now(pytz.timezone('Asia/Yangon')).strftime("%Y-%m-%d")
        new_row = [str(chat_id), username or "", today_str, "08:00", "21:00", "FALSE"]
        users_sheet.append_row(new_row)
        logger.info(f"New user created: {chat_id} ({username})")
        return len(users_sheet.get_all_values())

def get_streak_days(chat_id):
    user_data = get_user(chat_id)
    if not user_data or len(user_data) < 3: return 0
    try:
        last_sober_date = datetime.strptime(user_data[2], "%Y-%m-%d").date()
        today = datetime.now(pytz.timezone('Asia/Yangon')).date()
        return (today - last_sober_date).days
    except (ValueError, TypeError):
        return 0

def schedule_user_jobs(context: CallbackContext, chat_id: int):
    user_data = get_user(chat_id)
    if not user_data: return

    morning_time_str = user_data[3]
    night_time_str = user_data[4]
    
    try:
        morning_time = datetime.strptime(morning_time_str, "%H:%M").time()
        night_time = datetime.strptime(night_time_str, "%H:%M").time()
    except ValueError:
        morning_time = time(8, 0)
        night_time = time(21, 0)

    # Remove old jobs before adding new ones
    for job_name in [f'morning_{chat_id}', f'night_{chat_id}', f'midnight_reset_{chat_id}']:
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
    
    context.job_queue.run_daily(reminder_job, morning_time, chat_id=chat_id, name=f'morning_{chat_id}', data='morning')
    context.job_queue.run_daily(reminder_job, night_time, chat_id=chat_id, name=f'night_{chat_id}', data='night')
    # Reset check-in status at midnight
    context.job_queue.run_daily(reset_checkin_job, time(0, 0, tzinfo=pytz.timezone('Asia/Yangon')), chat_id=chat_id, name=f'midnight_reset_{chat_id}')

    logger.info(f"Scheduled jobs for user {chat_id} at {morning_time_str} and {night_time_str}")

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    create_or_update_user(user.id, user.username)
    schedule_user_jobs(context, user.id)
    await update.message.reply_html(
        f"👋 Welcome {user.mention_html()}!\n\nI'm here to support your alcohol-free journey. Your streak starts today (Day 1)!\n\n"
        "Use /status to check your progress, and /motivate when you need a boost. You can do this! ✨"
    )

async def motivate(update: Update, context: CallbackContext):
    await update.message.reply_text(random.choice(motivateMessages))

async def focus(update: Update, context: CallbackContext):
    await update.message.reply_text(random.choice(focusMessages))

async def reward(update: Update, context: CallbackContext):
    await update.message.reply_text(random.choice(rewardMessages))

async def status(update: Update, context: CallbackContext):
    days = get_streak_days(update.effective_chat.id)
    await update.message.reply_text(f"You are on a ✨ {days} day-streak ✨. Keep going, you're doing great!")

async def relapse_start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        f"{random.choice(noJudgmentMessages)}\n\n"
        "If you're comfortable, could you share what happened? This is just for your personal log."
    )
    return RELAPSE_REASON

async def relapse_reason(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    reason = update.message.text
    
    timestamp = datetime.now(pytz.timezone('Asia/Yangon')).strftime('%Y-%m-%d %H:%M:%S')
    log_sheet.append_row([timestamp, str(user.id), user.username or "", reason])

    row_num = create_or_update_user(user.id, user.username)
    today_str = datetime.now(pytz.timezone('Asia/Yangon')).strftime("%Y-%m-%d")
    users_sheet.update_cell(row_num, 3, today_str)
    
    await update.message.reply_text("Thank you for sharing. Your streak has been reset to Day 0. Tomorrow is a new day. 🌱")
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text('Okay, no problem. I\'m here if you need anything.')
    return ConversationHandler.END

async def conversation_support(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if any(phrase in text for phrase in ["i want to drink", "feel like drinking", "craving"]):
        await update.message.reply_text(random.choice(cravingSupportMessages))
    elif any(phrase in text for phrase in ["i feel good", "feeling great", "so happy"]):
        await update.message.reply_text(random.choice(celebrationMessages))

async def reminder_job(context: CallbackContext):
    chat_id = context.job.chat_id
    user_data = get_user(chat_id)
    if not user_data or user_data[5] == 'TRUE': # Don't send if already checked in
        return

    keyboard = [[InlineKeyboardButton("✅ I didn't drink today", callback_data='checkin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text="Hey, just checking in with you. Remember your goal—one peaceful day, alcohol-free.",
        reply_markup=reply_markup
    )

async def checkin_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.effective_chat.id
    row_num = create_or_update_user(chat_id, query.effective_user.username)
    users_sheet.update_cell(row_num, 6, "TRUE")
    
    days = get_streak_days(chat_id)
    await query.edit_message_text(text=f"Awesome! Checked in for today. Your streak is now {days} days! 🎉")

async def reset_checkin_job(context: CallbackContext):
    chat_id = context.job.chat_id
    row_num = create_or_update_user(chat_id, "N/A")
    if row_num:
        users_sheet.update_cell(row_num, 6, "FALSE")
        logger.info(f"Reset check-in status for user {chat_id}")

# --- MAIN FUNCTION ---
async def main():
    if not all([TELEGRAM_TOKEN, GOOGLE_SHEET_NAME, GOOGLE_CREDENTIALS_JSON]):
        logger.critical("CRITICAL: One or more environment variables are missing. Bot cannot start.")
        return
        
    start_web_server()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    relapse_handler = ConversationHandler(
        entry_points=[CommandHandler('relapse', relapse_start)],
        states={ RELAPSE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, relapse_reason)] },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("motivate", motivate))
    application.add_handler(CommandHandler("focus", focus))
    application.add_handler(CommandHandler("reward", reward))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(relapse_handler)
    application.add_handler(CallbackQueryHandler(checkin_button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, conversation_support))
    
    logger.info("MiraNotification Bot (Full Version) starting...")

    await application.initialize()
    await application.updater.start_polling()
    await application.start()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Bot crashed with error: {e}")

