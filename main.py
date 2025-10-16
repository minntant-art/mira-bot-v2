# -*- coding: utf-8 -*-
import os, json, random, logging, asyncio, pytz
from datetime import datetime
from flask import Flask, request
from threading import Thread
import gspread
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)

# ========== CONFIG ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "MiraAlcoholDB")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")

# ========== LOGGING ==========
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== FLASK ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "🍃 Mira Alcohol-Free Bot is alive!"

# ========== GOOGLE SHEETS ==========
try:
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    gc = gspread.service_account_from_dict(creds_dict)
    sh = gc.open(GOOGLE_SHEET_NAME)
    try:
        alcohol_sheet = sh.worksheet("Alcohol")
    except gspread.exceptions.WorksheetNotFound:
        alcohol_sheet = sh.add_worksheet(title="Alcohol", rows="100", cols="4")
        alcohol_sheet.append_row(["Date", "Description", "Quantity", "Unit"])

    try:
        users_sheet = sh.worksheet("Users")
    except gspread.exceptions.WorksheetNotFound:
        users_sheet = sh.add_worksheet(title="Users", rows="100", cols="4")
        users_sheet.append_row(["Chat_ID", "Username", "Last_Sober_Date", "Streak"])
    logger.info("✅ Connected to Google Sheets.")
except Exception as e:
    logger.error(f"❌ Sheets connection error: {e}")

# ========== MESSAGE POOLS ==========
motivate_msgs = [
    "Every alcohol-free morning builds your strength. 🌅",
    "Your mind feels clearer each sober day. 💡",
    "You're rewriting your story—one day at a time. 📖"
]
reward_msgs = [
    "Treat yourself to something nice today. 🎁",
    "Enjoy a peaceful cup of coffee—you earned it. ☕",
    "Take a break and smile. 😊"
]
celebration_msgs = [
    "That’s amazing progress! Keep going strong. 🎉",
    "Another alcohol-free day! You’re shining bright. 🌟",
    "You’re winning your peace back. 🌿"
]
nojudgement_msgs = [
    "It’s okay. Restart with kindness to yourself. 💫",
    "Every setback is a setup for a comeback. 🌱",
    "No judgment, only progress. 💪"
]
craving_msgs = [
    "It's okay to crave—it will pass soon. 🌬️",
    "You are stronger than the craving. 💪",
    "Drink water, breathe deeply. You’ve got this. 💧"
]

# ========== HELPERS ==========
def get_streak(chat_id):
    try:
        cell = users_sheet.find(str(chat_id))
        if cell:
            row = users_sheet.row_values(cell.row)
            last_sober = datetime.strptime(row[2], "%Y-%m-%d").date()
            today = datetime.now(pytz.timezone('Asia/Yangon')).date()
            return (today - last_sober).days
    except Exception:
        pass
    return 0

def reset_streak(chat_id, username):
    today = datetime.now(pytz.timezone('Asia/Yangon')).strftime("%Y-%m-%d")
    try:
        cell = users_sheet.find(str(chat_id))
        if cell:
            users_sheet.update_cell(cell.row, 2, today)
            users_sheet.update_cell(cell.row, 3, 0)
        else:
            users_sheet.append_row([str(chat_id), username, today, 0])
    except Exception as e:
        logger.error(f"Streak reset error: {e}")

def log_alcohol(description):
    now = datetime.now(pytz.timezone('Asia/Yangon')).strftime("%Y-%m-%d %H:%M")
    try:
        parts = description.split()
        qty = [p for p in parts if p.endswith("x")]
        amount = parts[-1] if len(parts) >= 2 else ""
        alcohol_sheet.append_row([now, description, amount, "entry"])
    except Exception as e:
        logger.error(f"Alcohol log error: {e}")

# ========== BOT HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    reset_streak(user.id, user.username)
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        "Welcome to Mira Alcohol-Free Helper Bot 🌿\n\n"
        "🧘 Type *အရက်သောက်ချင်တယ်* to get calm support\n"
        "🍺 Log drinking like: `Beer 350ml x 5`\n"
        "🌞 Morning reminders at 8AM\n"
        "🌙 Night encouragements at 9PM\n\n"
        "Let's build your streak together 💪",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    chat_id = user.id

    # craving detection
    if "အရက်သောက်ချင်" in text:
        await update.message.reply_text(random.choice(craving_msgs))
        return

    # alcohol log detection
    alcohol_types = ["beer", "rum", "vodka", "whisky", "wine"]
    if any(a.lower() in text.lower() for a in alcohol_types):
        log_alcohol(text)
        reset_streak(chat_id, user.username)
        await update.message.reply_text(
            random.choice(nojudgement_msgs) + "\n📝 Logged: " + text
        )
        return

    # fallback
    await update.message.reply_text("🪶 I'm here to help — try typing /start or /status.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    days = get_streak(chat_id)
    await update.message.reply_text(f"🌿 Alcohol-Free Streak: {days} days")

# ========== SCHEDULED REMINDERS ==========
async def morning_reminder(application):
    logger.info("⏰ Sending morning reminder...")
    users = users_sheet.get_all_records()
    for u in users:
        chat_id = u["Chat_ID"]
        days = get_streak(chat_id)
        text = (
            f"🌅 Good Morning!\n"
            f"🍀 Alcohol-Free Streak: {days} days\n\n"
            f"💬 Motivation: {random.choice(motivate_msgs)}\n"
            f"🎁 Reward idea: {random.choice(reward_msgs)}"
        )
        try:
            await application.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Morning reminder error: {e}")

async def night_reminder(application):
    logger.info("🌙 Sending night reminder...")
    users = users_sheet.get_all_records()
    for u in users:
        chat_id = u["Chat_ID"]
        days = get_streak(chat_id)
        text = (
            f"🌙 Good Night!\n"
            f"🍀 Alcohol-Free Streak: {days} days\n\n"
            f"🎉 {random.choice(celebration_msgs)}"
        )
        try:
            await application.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Night reminder error: {e}")

# ========== MAIN BOT ==========
def main():
    logger.info("🚀 Starting Mira Alcohol-Free Bot (v7) ...")
    app_instance = Application.builder().token(TELEGRAM_TOKEN).build()

    app_instance.add_handler(CommandHandler("start", start))
    app_instance.add_handler(CommandHandler("status", status))
    app_instance.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    WEBHOOK_URL = "https://mira-bot-v2.onrender.com/webhook"

   @app.route("/webhook", methods=["POST"])
    def webhook():
        try:
            data = request.get_json()
            if not data:
                return "No data", 200

            logger.info(f"📩 Incoming update: {data}")
            update = Update.de_json(data, app_instance.bot)

            async def process_update_async():
                try:
                    await app_instance.process_update(update)
                    logger.info("✅ Telegram handler executed successfully.")
                except Exception as e:
                    logger.error(f"Handler execution error: {e}")

            # Run without closing loop (safe persistent loop)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.create_task(process_update_async())

            # Don't close the loop — let it persist!
            Thread(target=loop.run_forever, daemon=True).start()

        except Exception as e:
            logger.error(f"❌ Webhook error: {e}")
        return "OK", 200


    async def run_bot():
        await app_instance.initialize()
        await app_instance.start()
        await app_instance.bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"🤖 Bot webhook set to {WEBHOOK_URL}")

        # Schedule reminders
        while True:
            now = datetime.now(pytz.timezone('Asia/Yangon')).strftime("%H:%M")
            if now == "08:00":
                await morning_reminder(app_instance)
            elif now == "21:00":
                await night_reminder(app_instance)
            await asyncio.sleep(60)

    def start_bot():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())

    Thread(target=start_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
