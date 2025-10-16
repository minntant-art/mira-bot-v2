# -*- coding: utf-8 -*-
import os
import json
import random
import logging
import asyncio
from datetime import datetime
from threading import Thread
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
import gspread

# --- Configuration ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8314100228:AAFw3iR_bHrjFyN2os3fjDF_-7v2Pv2tOv0")
SPREADSHEET_ID = "1ZZLEc6OsBt89Vc3rAwqdGjRek1Ut7YFcAUeWZVVOszY"
WEBHOOK_URL = "https://mira-bot-v2.onrender.com/webhook"

# --- Setup logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Flask app ---
app = Flask(__name__)

# --- Google Sheets setup ---
gc = gspread.service_account(filename="credentials.json")
sheet = gc.open_by_key(SPREADSHEET_ID)

# --- Message Pools ---
motivation_msgs = [
    "Stay strong today — one more alcohol-free day is a victory! 🌟",
    "သင့်စိတ်အားကောင်းတယ်။ ဒီနေ့လည်း အရက်မသောက်ဘဲ သံသယမရှိစွမ်းဆောင်နိုင်တယ်။ 💪",
    "Every sunrise sober is a gift to your mind and body 🌅",
    "တစ်နေ့သောက်မသောက်သက်သာတာတစ်သက်တန်တယ်။ ✨",
]
reward_msgs = [
    "Treat yourself to something nice — tea, movie, or massage 💆",
    "တန်ဖိုးရှိတဲ့နေ့ပါ။ သက်သာဖို့ စိတ်အေးအေးနဲ့ ငါးမိနစ်လောက်အနားယူပါ။ 🍵",
    "Small rewards grow big habits. You’re doing amazing! 🎁",
]
celebration_msgs = [
    "Another alcohol-free night — your body says thank you! 🥂",
    "အရက်မသောက်တဲ့ညလေး — သက်သာတဲ့အိပ်စက်မှုရရှိပါစေ။ 🌙",
    "Keep it up — tomorrow, you’ll be even prouder of yourself 💫",
]
no_judgement_msgs = [
    "It’s okay — one setback doesn’t erase your progress. 🌱",
    "အရမ်းမစိုးရိမ်ပါနဲ့။ မနေ့ကတော့လွဲသွားလို့ပေမဲ့ မနက်ဖြန်ပြန်စနိုင်တယ်။ ❤️",
    "Restart, don’t quit. You’ve come too far. 🔁",
]
craving_support = [
    "Take 3 deep breaths — craving passes faster than you think 🌬️",
    "မသောက်ရင် အေးချမ်းမှုကိုခံစားပါ။ ညအိပ်မက်ကောင်းလာပါလိမ့်မယ်။ 🌙",
    "Drink water, distract your mind — you are stronger than the urge 💧",
]

# --- Helper functions ---
def get_sheet(name):
    try:
        return sheet.worksheet(name)
    except Exception:
        return sheet.add_worksheet(title=name, rows=1000, cols=4)

def log_alcohol_entry(description):
    ws = get_sheet("Alcohol")
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([date, description])
    logger.info(f"📝 Logged alcohol entry: {description}")

def reset_streak():
    ws = get_sheet("Note")
    ws.append_row([datetime.now().strftime("%Y-%m-%d"), "Streak reset"])
    logger.info("⚠️ Streak reset to 0")

def get_random(arr):
    return random.choice(arr)

# --- Telegram Handlers ---
async def start(update: Update, context):
    await update.message.reply_text(
        "👋 Welcome to Mira Alcohol-Free Helper Bot!\n"
        "Type `/status` to see your progress.\n"
        "Type 'အရက်သောက်ချင်တယ်' when you crave.\n"
        "Type like `Beer 350ml x 5` to log a drink."
    )

async def status(update: Update, context):
    ws = get_sheet("Note")
    days = len(ws.col_values(1))
    await update.message.reply_text(f"📅 Alcohol-free days so far: {days} days ✅")

async def handle_message(update: Update, context):
    text = update.message.text.strip()
    logger.info(f"💬 Received: {text}")

    # Craving Detection
    if "အရက်သောက်ချင်တယ်" in text:
        msg = get_random(craving_support)
        await update.message.reply_text(f"💬 {msg}")
        return

    # Alcohol Logging
    if any(x in text.lower() for x in ["beer", "vodka", "rum", "whisky", "alcohol"]):
        log_alcohol_entry(text)
        reset_streak()
        msg = get_random(no_judgement_msgs)
        await update.message.reply_text(f"📝 Logged: {text}\n\n{msg}")
        return

    await update.message.reply_text("💡 Type `/help` for commands or record your alcohol-free progress.")

# --- Main Bot Application ---
def main():
    global app_instance
    logger.info("🚀 Starting Mira Alcohol-Free Bot (v8)...")
    app_instance = Application.builder().token(TELEGRAM_TOKEN).build()

    app_instance.add_handler(CommandHandler("start", start))
    app_instance.add_handler(CommandHandler("status", status))
    app_instance.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app_instance.bot.set_webhook(WEBHOOK_URL)
    return app_instance


# --- Flask Webhook Endpoint ---
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

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(process_update_async())
        Thread(target=loop.run_forever, daemon=True).start()

    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")

    return "OK", 200


@app.route("/")
def home():
    return "🍃 Mira Bot is running on Render!"


if __name__ == "__main__":
    app_instance = main()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
