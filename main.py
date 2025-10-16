# -*- coding: utf-8 -*-
"""
MiraNotification Bot
- Uses TELEGRAM_TOKEN from environment (do NOT hardcode token)
- Uses GOOGLE_CREDENTIALS (JSON string) from environment for gspread.service_account_from_dict
- Webhook mode with Flask; safe event-loop handoff to telegram Application
- Parses relapse messages like "Beer 350ml x 5" and resets streak (Day 0)
- Morning (08:00 Yangon) -> send streak + motivate + reward
- Night (21:00 Yangon)   -> send streak + celebration/encouragement
"""
import os
import json
import logging
import random
import re
import asyncio
from threading import Thread
from datetime import datetime, date, time, timedelta

import pytz
import gspread
from flask import Flask, request

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    ContextTypes,
    filters,
)

# ---------- Configuration ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # MUST be set in env
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")  # JSON string of service account
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "MiraNotificationDB")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://mira-bot-v2.onrender.com/webhook")
TIMEZONE = pytz.timezone("Asia/Yangon")

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mira-bot")

# ---------- Google Sheets Setup ----------
users_sheet = None
log_sheet = None
mood_sheet = None

if GOOGLE_CREDENTIALS:
    try:
        creds = json.loads(GOOGLE_CREDENTIALS)
        gc = gspread.service_account_from_dict(creds)
        spreadsheet = gc.open(GOOGLE_SHEET_NAME)

        def ensure_worksheet(name, header):
            try:
                w = spreadsheet.worksheet(name)
            except gspread.exceptions.WorksheetNotFound:
                w = spreadsheet.add_worksheet(title=name, rows="2000", cols="20")
                w.append_row(header)
            return w

        users_sheet = ensure_worksheet("Users", ["Chat_ID", "Username", "Last_Sober_Date", "Morning_Time", "Night_Time", "Checked_In_Today"])
        log_sheet = ensure_worksheet("Log", ["Timestamp", "Chat_ID", "Username", "Relapse_Reason"])
        mood_sheet = ensure_worksheet("MoodLog", ["Timestamp", "Chat_ID", "Mood", "Craving_Reason"])

        logger.info("Connected to Google Sheets.")
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets: {e}")
else:
    logger.warning("No GOOGLE_CREDENTIALS provided; Sheets features disabled.")

# ---------- Messages (shortened here; paste full arrays as you have) ----------
motivateMessages = [
    "You've come so far—one more alcohol-free day makes your mind stronger. 💪",
    "Remember why you started. That reason is more powerful than any craving. ✨",
    "Every day you choose not to drink, you are healing. Be proud of that. 🌱",
]
focusMessages = [
    "Breathe in for 4 seconds, hold for 4, and breathe out for 6. Repeat 5 times. You are in control. 🌬️",
    "Find a quiet spot. Close your eyes and name 3 things you can hear. It brings you back to the present moment. 🧘",
]
rewardMessages = [
    "Treat yourself to your favorite meal tonight. You've earned it! 🍕",
    "Watch that movie you've been wanting to see. Relax and enjoy. 🎬",
]
cravingSupportMessages = [
    "It's okay to feel this way. The feeling is temporary. Can you try a focus exercise with /focus? ✨",
    "I hear you. Remember the last time you felt great waking up without a hangover? Let's aim for that again. 🌅",
]
celebrationMessages = [
    "That's amazing to hear! 🎉 Celebrating this positive feeling with you.",
    "So happy for you! Keep embracing these good moments. ✨",
]
noJudgmentMessages = [
    "No judgment here. Recovery isn't a straight line. Be kind to yourself today. We'll take it one day at a time. ❤️",
    "Falling down is part of learning. What matters is getting back up. You can do this. 💪",
]

# ---------- Helpers for Google Sheets ----------
def get_user_row(chat_id):
    """Return (row_index, row_values) or (None, None)"""
    if not users_sheet:
        return None, None
    try:
        cell = users_sheet.find(str(chat_id))
        if cell:
            row = users_sheet.row_values(cell.row)
            return cell.row, row
    except gspread.exceptions.CellNotFound:
        return None, None
    except Exception as e:
        logger.error(f"get_user_row error: {e}")
        return None, None

def create_or_update_user(chat_id, username):
    if not users_sheet:
        return None
    try:
        row_index, row = get_user_row(chat_id)
        today_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        if row_index:
            users_sheet.update_cell(row_index, 2, username or "")
            return row_index
        else:
            new_row = [str(chat_id), username or "", today_str, "08:00", "21:00", "FALSE"]
            users_sheet.append_row(new_row)
            vals = users_sheet.get_all_values()
            return len(vals)
    except Exception as e:
        logger.error(f"Error creating/updating user: {e}")
        return None

def set_last_sober_date(chat_id, dt: date):
    if not users_sheet:
        return False
    try:
        row_index, row = get_user_row(chat_id)
        if not row_index:
            return False
        users_sheet.update_cell(row_index, 3, dt.strftime("%Y-%m-%d"))
        return True
    except Exception as e:
        logger.error(f"set_last_sober_date error: {e}")
        return False

def append_log(chat_id, username, reason):
    if not log_sheet:
        return
    try:
        ts = datetime.now(TIMEZONE).isoformat()
        log_sheet.append_row([ts, str(chat_id), username or "", reason])
    except Exception as e:
        logger.error(f"append_log error: {e}")

def get_all_users():
    """Return list of dicts: {chat_id, username, morning_time, night_time, last_sober_date}"""
    if not users_sheet:
        return []
    try:
        rows = users_sheet.get_all_records()
        results = []
        for r in rows:
            try:
                results.append({
                    "chat_id": int(r.get("Chat_ID")),
                    "username": r.get("Username"),
                    "last_sober": r.get("Last_Sober_Date"),
                    "morning_time": r.get("Morning_Time", "08:00"),
                    "night_time": r.get("Night_Time", "21:00"),
                })
            except Exception:
                continue
        return results
    except Exception as e:
        logger.error(f"get_all_users error: {e}")
        return []

def get_streak_days_from_date_string(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now(TIMEZONE).date()
        return (today - d).days
    except Exception:
        return 0

# ---------- Telegram handlers ----------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username)
    text = (
        f"👋 Hello {user.first_name}!\n\n"
        "Welcome to Mira Alcohol-Free Helper Bot 🍃\n\n"
        "Commands:\n"
        "/motivate - daily motivation\n"
        "/focus - quick grounding\n"
        "/reward - small reward idea\n"
        "/status - see your streak\n\n"
        "If you're struggling, just tell me (e.g. 'Beer 350ml x 5') and I'll support you — no judgment."
    )
    await update.message.reply_text(text)

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    _, row = get_user_row(chat_id)
    if not row:
        await update.message.reply_text("No record yet — send /start to register.")
        return
    last_sober = row[2] if len(row) > 2 else None
    days = get_streak_days_from_date_string(last_sober) if last_sober else 0
    await update.message.reply_text(f"✨ You are on a {days} day streak. Keep going!")

async def motivate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(motivateMessages))

async def focus_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(focusMessages))

async def reward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(rewardMessages))

# Pattern to detect drinks like "Beer 350ml x 5" or "Rum 50ml x2"
DRINK_PATTERN = re.compile(r"(?P<type>\b(Rum|Whisky|Beer|Vodka|Wine)\b)\s*(?P<size>\d+)\s*(?:ml|mL|ML)?\s*[x×*]?\s*(?P<count>\d+)", re.IGNORECASE)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    user = update.effective_user
    # If user types english "I want to drink" or in Myanmar language, we can check simple keyword
    if DRINK_PATTERN.search(text):
        m = DRINK_PATTERN.search(text)
        drink_type = m.group("type")
        size = m.group("size")
        count = m.group("count")
        reason_str = f"{drink_type} {size}ml x {count}"
        # Log relapse and reset streak (set Last_Sober_Date to today so streak becomes 0)
        set_last_sober_date(chat_id, datetime.now(TIMEZONE).date())
        append_log(chat_id, user.username, reason_str)
        # reply with no-judgement + craving support
        await update.message.reply_text(random.choice(noJudgmentMessages))
        await update.message.reply_text(f"Logged: {reason_str}. If you need support, try /focus or /motivate.")
        return

    # if message contains "အရက်" (Myanmar word for alcohol) or "I want to drink"
    lower = text.lower()
    if "drink" in lower or "အရက်" in text:
        # Generic craving support
        await update.message.reply_text(random.choice(cravingSupportMessages))
        return

    # Otherwise echo or unknown
    await update.message.reply_text("I didn't understand that. Try /motivate, /focus, /status or tell me if you drank (e.g. 'Beer 350ml x 5').")

# ---------- Scheduling background jobs ----------
async def send_user_message(bot, chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")

async def morning_job(app):
    """Send morning messages (streak + motivate + reward) to all users who have morning_time set to 08:00 (or all users)."""
    bot = app.bot
    users = get_all_users()
    for u in users:
        try:
            streak = get_streak_days_from_date_string(u.get("last_sober") or datetime.now(TIMEZONE).strftime("%Y-%m-%d"))
            msgs = [
                f"Good morning! 🌞 Your current streak: {streak} days.",
                f"Motivation: {random.choice(motivateMessages)}",
                f"Reward idea: {random.choice(rewardMessages)}"
            ]
            for m in msgs:
                await send_user_message(bot, u["chat_id"], m)
        except Exception as e:
            logger.error(f"morning_job error for user {u}: {e}")

async def night_job(app):
    """Send night messages (streak + celebration encouragement)."""
    bot = app.bot
    users = get_all_users()
    for u in users:
        try:
            streak = get_streak_days_from_date_string(u.get("last_sober") or datetime.now(TIMEZONE).strftime("%Y-%m-%d"))
            msgs = [
                f"Good evening! 🌙 Your current streak: {streak} days.",
                f"Encouragement: {random.choice(celebrationMessages)}"
            ]
            for m in msgs:
                await send_user_message(bot, u["chat_id"], m)
        except Exception as e:
            logger.error(f"night_job error for user {u}: {e}")

async def scheduler_loop(app):
    """Persistent scheduler that runs morning_job at 08:00 and night_job at 21:00 Asia/Yangon daily."""
    logger.info("Scheduler loop started.")
    while True:
        try:
            now = datetime.now(TIMEZONE)
            # next morning 08:00
            today_morning = TIMEZONE.localize(datetime.combine(now.date(), time(8, 0)))
            today_night = TIMEZONE.localize(datetime.combine(now.date(), time(21, 0)))
            # choose next event
            if now < today_morning:
                next_run = today_morning
                job = morning_job
            elif now < today_night:
                next_run = today_night
                job = night_job
            else:
                # next day's morning
                next_run = TIMEZONE.localize(datetime.combine(now.date() + timedelta(days=1), time(8, 0)))
                job = morning_job
            wait_seconds = (next_run - now).total_seconds()
            logger.info(f"Scheduler sleeping for {int(wait_seconds)}s until {next_run.isoformat()}")
            await asyncio.sleep(wait_seconds + 1)  # wake just after target
            # run job
            logger.info(f"Scheduler running job {job.__name__} at {datetime.now(TIMEZONE).isoformat()}")
            await job(app)
            # small sleep to avoid immediate double-run
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            # avoid tight loop on error
            await asyncio.sleep(30)

# ---------- Flask webhook server ----------
flask_app = Flask(__name__)

# We'll store a reference to the Application instance and its event loop
app_instance = None
app_loop = None

@flask_app.route("/", methods=["GET"])
def home():
    return "Mira Bot is live and listening via webhook."

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    """
    Receives incoming update JSON from Telegram (webhook).
    Uses asyncio.run_coroutine_threadsafe to hand off processing to the bot's event loop.
    """
    global app_instance, app_loop
    try:
        data = request.get_json(force=True)
        if not data:
            logger.warning("Empty webhook payload")
            return "No data", 200
        logger.info(f"📩 Incoming update: {data}")
        if not app_instance or not app_loop:
            logger.error("App instance or loop not ready to process updates.")
            return "Not ready", 503
        update = Update.de_json(data, app_instance.bot)
        # schedule processing on the bot event loop
        fut = asyncio.run_coroutine_threadsafe(app_instance.process_update(update), app_loop)
        # Optionally attach callback to log exceptions
        def _cb(f):
            try:
                f.result()
            except Exception as e:
                logger.error(f"Exception in process_update: {e}")
        fut.add_done_callback(_cb)
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook handling error: {e}")
        return "Error", 500

# ---------- Main startup ----------
def main():
    global app_instance, app_loop
    if not TELEGRAM_TOKEN:
        logger.critical("TELEGRAM_TOKEN is not set in environment. Exiting.")
        return

    logger.info("Starting MiraNotification Bot (webhook mode)...")

    # Build the Application
    app_instance = Application.builder().token(TELEGRAM_TOKEN).build()

    # Register handlers
    app_instance.add_handler(CommandHandler("start", start_handler))
    app_instance.add_handler(CommandHandler("status", status_handler))
    app_instance.add_handler(CommandHandler("motivate", motivate_handler))
    app_instance.add_handler(CommandHandler("focus", focus_handler))
    app_instance.add_handler(CommandHandler("reward", reward_handler))
    app_instance.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run the bot on its own event loop in a background thread
    def start_bot_loop():
        nonlocal_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(nonlocal_loop)
        # run initialization and webhook set
        async def _run():
            try:
                await app_instance.initialize()
                # delete any previous webhook to avoid conflict (safe)
                try:
                    await app_instance.bot.delete_webhook()
                except Exception as e:
                    logger.debug(f"delete_webhook warning: {e}")
                # set webhook to our URL
                try:
                    await app_instance.bot.set_webhook(url=WEBHOOK_URL)
                    logger.info(f"🤖 Bot webhook set to {WEBHOOK_URL}")
                except Exception as e:
                    logger.error(f"Failed to set webhook: {e}")

                # start application (starts internal tasks)
                await app_instance.start()
                # schedule the persistent scheduler_loop
                nonlocal_loop.create_task(scheduler_loop(app_instance))
                logger.info("Bot started and scheduler scheduled.")
                # keep loop running forever
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                logger.info("Bot loop cancelled.")
            except Exception as e:
                logger.critical(f"Bot loop error: {e}")

        try:
            nonlocal_loop.run_until_complete(_run())
        finally:
            try:
                nonlocal_loop.run_until_complete(app_instance.stop())
                nonlocal_loop.run_until_complete(app_instance.shutdown())
            except Exception:
                pass
            nonlocal_loop.close()

    # start bot thread and capture the loop reference
    bot_thread = Thread(target=start_bot_loop, daemon=True)
    bot_thread.start()

    # Wait briefly until app_instance._running_loop gets set (we'll introspect)
    # The Application object inside python-telegram-bot will be running on the created loop.
    # We need the loop object for run_coroutine_threadsafe; to avoid fragile internals,
    # we find the currently running loop in the bot thread by waiting a little.
    # (This is a pragmatic approach for Render-style single-process deployments.)
    attempts = 0
    while attempts < 20:
        loop_guess = getattr(app_instance, "_running_loop", None)
        if loop_guess:
            app_loop = loop_guess
            logger.info("✅ Application event loop obtained successfully.")
            break
        attempts += 1
        import time as _t
        _t.sleep(0.3)
    # Try to get the loop: Application has attribute `_running_loop` when started
    # We'll poll until it's available
    poll_count = 0
    while poll_count < 50:
        loop_guess = getattr(app_instance, "_running_loop", None)
        if loop_guess:
            app_loop = loop_guess
            logger.info("Obtained bot event loop for webhook handoff.")
            break
        poll_count += 1
        import time as _t
        _t.sleep(0.2)
    if not app_loop:
        logger.warning("Could not obtain bot event loop; webhook may fail to hand off updates.")

    # Finally run Flask in main thread (Render will bind the port)
    port = int(os.environ.get("PORT", "8080"))
    logger.info(f"Starting Flask server on port {port}")
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.critical(f"Unhandled exception in main: {exc}", exc_info=True)
