# main.py
# -*- coding: utf-8 -*-
import os
import json
import logging
import random
import re
import threading
import time
import datetime
import traceback
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict

# Telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Flask for webhook endpoint
from flask import Flask, request

# Optional Google Sheets
try:
    import gspread
    from gspread.exceptions import WorksheetNotFound, CellNotFound
    GS_AVAILABLE = True
except Exception:
    GS_AVAILABLE = False

# ---------------------------
# Configuration / Environment
# ---------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")  # JSON string of service account credentials
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "MiraNotificationDB")
TIMEZONE = "Asia/Yangon"
MORNING_HOUR = 8   # 08:00 local
NIGHT_HOUR = 21    # 21:00 local

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable is required. Set it in your Render (or host) secrets.")

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mira-bot")

# ---------------------------
# Message banks (shortened for readability; expand as you like)
# ---------------------------
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
    "It's okay to feel this way. The feeling is temporary. Try /focus for a short exercise. ✨",
    "Drink a large glass of water and wait 15 minutes. Sometimes cravings are just dehydration. 💧",
    "This craving is just a thought, not a command. You don't have to act on it. 🧠",
]

celebrationMessages = [
    "That's amazing to hear! 🎉 Celebrating this positive feeling with you.",
    "So happy for you! Keep embracing these good moments. ✨",
]

noJudgmentMessages = [
    "No judgment here. Recovery isn't a straight line. Be kind to yourself today. ❤️",
    "Falling down is part of learning. What matters is getting back up. You can do this. 💪",
]

# ---------------------------
# Storage (Google Sheets or in-memory fallback)
# ---------------------------
users_sheet = None
log_sheet = None
mood_sheet = None

# In-memory fallback dict: chat_id -> user row fields
_in_memory_users: Dict[str, Dict] = {}

def setup_google_sheets():
    global users_sheet, log_sheet, mood_sheet
    if not GS_AVAILABLE:
        logger.warning("gspread not available; using in-memory storage.")
        return False

    if not GOOGLE_CREDENTIALS:
        logger.warning("GOOGLE_CREDENTIALS not provided; using in-memory storage.")
        return False

    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        gc = gspread.service_account_from_dict(creds_dict)
        spreadsheet = gc.open(GOOGLE_SHEET_NAME)
    except Exception as e:
        logger.error(f"Google Sheets auth/open error: {e}")
        return False

    # Ensure worksheets exist
    try:
        users_sheet = spreadsheet.worksheet("Users")
    except WorksheetNotFound:
        users_sheet = spreadsheet.add_worksheet(title="Users", rows="100", cols="6")
        users_sheet.append_row(["Chat_ID", "Username", "Last_Sober_Date", "Morning_Time", "Night_Time", "Checked_In_Today"])

    try:
        log_sheet = spreadsheet.worksheet("Log")
    except WorksheetNotFound:
        log_sheet = spreadsheet.add_worksheet(title="Log", rows="1000", cols="4")
        log_sheet.append_row(["Timestamp", "Chat_ID", "Username", "Relapse_Reason"])

    try:
        mood_sheet = spreadsheet.worksheet("MoodLog")
    except WorksheetNotFound:
        mood_sheet = spreadsheet.add_worksheet(title="MoodLog", rows="1000", cols="4")
        mood_sheet.append_row(["Timestamp", "Chat_ID", "Mood", "Craving_Reason"])

    logger.info("Connected to Google Sheets.")
    return True

GS_OK = setup_google_sheets()

# ---------------------------
# Helper: user operations
# ---------------------------

def now_local_date_str():
    return datetime.datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")

def get_user_row(chat_id: int) -> Optional[List[str]]:
    """Return row values from Google Sheet or None. If using in-memory fallback, return dict as list-like."""
    if GS_OK and users_sheet:
        try:
            cell = users_sheet.find(str(chat_id))
            if cell and hasattr(cell, "row"):
                return users_sheet.row_values(cell.row)
        except CellNotFound:
            return None
        except Exception as e:
            logger.error(f"Error reading user from sheet: {e}")
            return None
    # in-memory fallback
    return _in_memory_users.get(str(chat_id))

def create_or_update_user(chat_id: int, username: Optional[str]) -> int:
    """Create user if not exists. Returns internal row id (1-based index or dict id)."""
    key = str(chat_id)
    today_str = now_local_date_str()
    if GS_OK and users_sheet:
        try:
            cell = users_sheet.find(key)
            if cell:
                # update username column
                users_sheet.update_cell(cell.row, 2, username or "")
                return cell.row
            else:
                new_row = [key, username or "", today_str, "08:00", "21:00", "FALSE"]
                users_sheet.append_row(new_row)
                # return new row number:
                return len(users_sheet.get_all_values())
        except Exception as e:
            logger.error(f"Error create/update sheet user: {e}")
            # fallback to memory
    # in-memory:
    if key not in _in_memory_users:
        _in_memory_users[key] = {
            "Chat_ID": key,
            "Username": username or "",
            "Last_Sober_Date": today_str,
            "Morning_Time": "08:00",
            "Night_Time": "21:00",
            "Checked_In_Today": "FALSE",
        }
    else:
        _in_memory_users[key]["Username"] = username or ""
    return chat_id

def set_last_sober_date(chat_id: int, date_str: Optional[str] = None):
    if date_str is None:
        date_str = now_local_date_str()
    key = str(chat_id)
    if GS_OK and users_sheet:
        try:
            cell = users_sheet.find(key)
            if cell:
                users_sheet.update_cell(cell.row, 3, date_str)
                return True
        except Exception as e:
            logger.error(f"Error setting last sober date in sheet: {e}")
            return False
    # fallback
    if key in _in_memory_users:
        _in_memory_users[key]["Last_Sober_Date"] = date_str
    else:
        _in_memory_users[key] = {
            "Chat_ID": key,
            "Username": "",
            "Last_Sober_Date": date_str,
            "Morning_Time": "08:00",
            "Night_Time": "21:00",
            "Checked_In_Today": "FALSE",
        }
    return True

def log_relapse(chat_id: int, username: str, reason: str):
    ts = datetime.datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    if GS_OK and log_sheet:
        try:
            log_sheet.append_row([ts, str(chat_id), username or "", reason])
            return True
        except Exception as e:
            logger.error(f"Failed logging relapse to sheet: {e}")
            return False
    # fallback: just print
    logger.info(f"(fallback log) {ts} relapse: {chat_id} {username} {reason}")
    return True

def get_streak_days(chat_id: int) -> int:
    row = get_user_row(chat_id)
    if not row:
        return 0
    # row from sheet: [Chat_ID, Username, Last_Sober_Date, ...]
    try:
        if isinstance(row, dict):
            last = row.get("Last_Sober_Date")
        else:
            last = row[2] if len(row) > 2 else None
        if not last:
            return 0
        last_date = datetime.date.fromisoformat(last)
        today = datetime.datetime.now(ZoneInfo(TIMEZONE)).date()
        return (today - last_date).days
    except Exception:
        return 0

# ---------------------------
# Parsing relapse messages
# ---------------------------
RE_DRINK = re.compile(
    r"(?P<name>\b(beer|rum|whisky|whiskey|vodka|wine)\b)\s*(?P<size>\d+ml)?\s*(?:x|×)?\s*(?P<qty>\d+)?",
    re.IGNORECASE
)

def parse_drink_message(text: str):
    """Return (name, size_ml, qty) or None."""
    m = RE_DRINK.search(text)
    if not m:
        return None
    name = m.group("name") or ""
    size = m.group("size")
    qty = m.group("qty")
    size_ml = int(size[:-2]) if size and size.lower().endswith("ml") else None
    qty_num = int(qty) if qty else 1
    return name.lower(), size_ml, qty_num

# ---------------------------
# Telegram Handlers
# ---------------------------
# These are simple and synchronous async defs for python-telegram-bot v20+
async def cmd_start(update: Update, context):
    user = update.effective_user
    create_or_update_user(user.id, user.username)
    days = get_streak_days(user.id)
    await update.message.reply_text(
        f"👋 Hello {user.first_name}! Your current streak is {days} day(s). Use /status to check anytime.\n"
        "Send messages like 'Beer 350ml x 5' if you relapsed, or 'အရက်သောက်ချင်တယ်' to get craving support."
    )

async def cmd_status(update: Update, context):
    chat_id = update.effective_chat.id
    days = get_streak_days(chat_id)
    await update.message.reply_text(f"You are on a ✨ {days} day-streak ✨. Keep going!")

async def send_random_from_list(chat_id: int, choices: List[str], bot, parse_mode=None):
    text = random.choice(choices)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Failed to send scheduled message to {chat_id}: {e}")

async def handle_message_async(update: Update, context):
    """Main message handler (async)."""
    text = update.message.text or ""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name or ""
    # First: detect craving phrases (Burmese text or english)
    lower = text.strip().lower()
    if "အရက်သောက်ချင်" in text or "want to drink" in lower or "i want to drink" in lower:
        # send craving support message
        await update.message.reply_text(random.choice(cravingSupportMessages))
        return

    # Detect relapse pattern
    parsed = parse_drink_message(text)
    if parsed:
        name, size_ml, qty = parsed
        # Reset streak (set last sober date to today)
        set_last_sober_date(chat_id, now_local_date_str())  # sets to today -> streak 0
        reason = f"{name} {size_ml or ''} x {qty}"
        log_relapse(chat_id, username, reason)
        # reply no-judgment and confirmation
        await update.message.reply_text(random.choice(noJudgmentMessages))
        await update.message.reply_text(f"Logged relapse: {reason}. Your streak has been reset to 0. We're with you — let's start again.")
        return

    # Other general commands: if user requests focus/motivate/reward words
    if lower.startswith("/motivate") or "motivate" in lower:
        await update.message.reply_text(random.choice(motivateMessages))
        return

    if lower.startswith("/focus") or "focus" in lower:
        await update.message.reply_text(random.choice(focusMessages))
        return

    if lower.startswith("/reward") or "reward" in lower:
        await update.message.reply_text(random.choice(rewardMessages))
        return

    # default helpful reply
    await update.message.reply_text("Thanks — I got your message. Use /status, /motivate, /focus, or send relapse info like 'Beer 350ml x 5' if a slip happened.")

# Thin wrapper to call async handler from application
async def handle_message(update: Update, context):
    await handle_message_async(update, context)

# ---------------------------
# Background async loop runner (thread) for running application coroutines
# ---------------------------
def start_async_loop_in_thread():
    """Create an asyncio loop in a background thread and return it."""
    import asyncio

    loop = asyncio.new_event_loop()

    def _run_loop():
        try:
            asyncio.set_event_loop(loop)
            loop.run_forever()
        except Exception as e:
            logger.critical(f"Background loop thread exception: {e}\n{traceback.format_exc()}")

    t = threading.Thread(target=_run_loop, daemon=True)
    t.start()
    # Wait a short time to ensure loop is running
    time.sleep(0.1)
    return loop

# ---------------------------
# Scheduler for morning/night messages
# ---------------------------
class DailyScheduler(threading.Thread):
    def __init__(self, loop, app_instance):
        super().__init__(daemon=True)
        self.loop = loop
        self.app = app_instance
        self.tz = ZoneInfo(TIMEZONE)
        # track which users have been sent today's morning/night message
        self.sent_morning = set()
        self.sent_night = set()
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        logger.info("DailyScheduler started (checking every 60s).")
        while not self._stop.is_set():
            try:
                now = datetime.datetime.now(self.tz)
                hh = now.hour
                mm = now.minute
                # Reset sets at midnight local time
                if hh == 0 and mm == 0:
                    self.sent_morning.clear()
                    self.sent_night.clear()

                # iterate users (sheet or in-memory)
                all_users = []
                if GS_OK and users_sheet:
                    try:
                        vals = users_sheet.get_all_values()[1:]  # skip header
                        for r in vals:
                            if len(r) >= 1 and r[0]:
                                all_users.append({"chat_id": int(r[0]), "username": r[1] if len(r) > 1 else ""})
                    except Exception:
                        logger.exception("Failed reading users from sheet for scheduler; falling back to in-memory")
                        for k,v in _in_memory_users.items():
                            all_users.append({"chat_id": int(k), "username": v.get("Username","")})
                else:
                    for k,v in _in_memory_users.items():
                        all_users.append({"chat_id": int(k), "username": v.get("Username","")})

                # morning: at MORNING_HOUR (exact minute 0)
                if hh == MORNING_HOUR and mm == 0:
                    for u in all_users:
                        cid = u["chat_id"]
                        if cid in self.sent_morning:
                            continue
                        try:
                            days = get_streak_days(cid)
                            # send streak + motivate + reward
                            coro1 = self.app.bot.send_message(chat_id=cid, text=f"Good morning! You are on a {days}-day streak. Keep going! 🌞")
                            coro2 = self.app.bot.send_message(chat_id=cid, text=random.choice(motivateMessages))
                            coro3 = self.app.bot.send_message(chat_id=cid, text=random.choice(rewardMessages))
                            import asyncio as _a
                            _a.run_coroutine_threadsafe(coro1, self.loop)
                            _a.run_coroutine_threadsafe(coro2, self.loop)
                            _a.run_coroutine_threadsafe(coro3, self.loop)
                            self.sent_morning.add(cid)
                        except Exception as e:
                            logger.error(f"Failed sending morning message to {cid}: {e}")

                # night: at NIGHT_HOUR (exact minute 0)
                if hh == NIGHT_HOUR and mm == 0:
                    for u in all_users:
                        cid = u["chat_id"]
                        if cid in self.sent_night:
                            continue
                        try:
                            days = get_streak_days(cid)
                            coro1 = self.app.bot.send_message(chat_id=cid, text=f"Good evening — you are on a {days}-day streak. Keep it up! 🌙")
                            coro2 = self.app.bot.send_message(chat_id=cid, text=random.choice(celebrationMessages))
                            import asyncio as _a
                            _a.run_coroutine_threadsafe(coro1, self.loop)
                            _a.run_coroutine_threadsafe(coro2, self.loop)
                            self.sent_night.add(cid)
                        except Exception as e:
                            logger.error(f"Failed sending night message to {cid}: {e}")

            except Exception:
                logger.exception("Scheduler loop error")
            # wait until next minute
            time.sleep(60)

# ---------------------------
# Flask app + webhook handing
# ---------------------------
flask_app = Flask(__name__)

# We'll fill these in main()
_app_instance: Optional[Application] = None
_background_loop = None
_scheduler = None

@flask_app.route("/", methods=["GET"])
def health_check():
    return "MiraNotification Bot is alive!"

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    """Receive Telegram update JSON and hand over to application.process_update via background loop."""
    global _app_instance, _background_loop
    try:
        data = request.get_json()
        if not data:
            return "No data", 200
        logger.info(f"📩 Incoming update: {data}")

        # Build Update object
        update = Update.de_json(data, _app_instance.bot)

        # Schedule processing on background loop
        import asyncio
        future = asyncio.run_coroutine_threadsafe(_app_instance.process_update(update), _background_loop)
        # Optionally we can wait for completion or not; we won't wait to keep webhook fast
        # result = future.result(timeout=5)
        logger.info("✅ Webhook update scheduled to application.")
        return "OK", 200
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}\n{traceback.format_exc()}")
        return "OK", 200

# ---------------------------
# Main startup
# ---------------------------
def main():
    global _app_instance, _background_loop, _scheduler
    logger.info("Starting MiraNotification Bot (webhook-only mode) ...")

    # Create Telegram application
    _app_instance = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    _app_instance.add_handler(CommandHandler("start", cmd_start))
    _app_instance.add_handler(CommandHandler("status", cmd_status))
    # generic text messages
    _app_instance.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start background loop thread
    _background_loop = start_async_loop_in_thread()

    # Initialize & start application on background loop
    import asyncio as _asyncio
    try:
        # Initialize
        fut_init = _asyncio.run_coroutine_threadsafe(_app_instance.initialize(), _background_loop)
        fut_init.result(10)  # wait up to 10s for init
        logger.info("Application.initialize() completed.")
    except Exception as e:
        logger.critical(f"Failed to initialize application: {e}\n{traceback.format_exc()}")
        # proceed but will likely fail

    try:
        # start application (does not block)
        fut_start = _asyncio.run_coroutine_threadsafe(_app_instance.start(), _background_loop)
        fut_start.result(10)
        logger.info("Application.start() completed.")
    except Exception as e:
        logger.critical(f"Failed to start application: {e}\n{traceback.format_exc()}")

    # Set webhook on Telegram
    WEBHOOK_URL = os.getenv("WEBHOOK_URL") or f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME','mira-bot-v2.onrender.com')}/webhook"
    try:
        fut_wh = _asyncio.run_coroutine_threadsafe(_app_instance.bot.delete_webhook(drop_pending_updates=True), _background_loop)
        fut_wh.result(5)
    except Exception:
        pass
    try:
        fut_set = _asyncio.run_coroutine_threadsafe(_app_instance.bot.set_webhook(url=WEBHOOK_URL), _background_loop)
        fut_set.result(10)
        logger.info(f"🤖 Bot webhook set to {WEBHOOK_URL}")
    except Exception as e:
        logger.critical(f"Failed to set webhook: {e}\n{traceback.format_exc()}")

    # Start scheduler thread
    _scheduler = DailyScheduler(_background_loop, _app_instance)
    _scheduler.start()

    # Finally: run Flask server (blocking)
    port = int(os.environ.get("PORT", "10000"))
    logger.info(f"Starting Flask server on port {port}")
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception in main: {e}\n{traceback.format_exc()}")
