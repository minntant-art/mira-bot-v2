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
    t = Thread(target=run_flask, daemon=True)
    t.start()

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "MiraNotificationDB")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")

RELAPSE_REASON, LOG_MOOD, LOG_REASON, SETTINGS_MORNING, SETTINGS_NIGHT = range(5)

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

        try:
            users_sheet = spreadsheet.worksheet("Users")
        except gspread.exceptions.WorksheetNotFound:
            users_sheet = spreadsheet.add_worksheet(title="Users", rows="100", cols="6")
            users_sheet.append_row(["Chat_ID", "Username", "Last_Sober_Date", "Morning_Time", "Night_Time", "Checked_In_Today"])

        try:
            log_sheet = spreadsheet.worksheet("Log")
        except gspread.exceptions.WorksheetNotFound:
            log_sheet = spreadsheet.add_worksheet(title="Log", rows="1000", cols="4")
            log_sheet.append_row(["Timestamp", "Chat_ID", "Username", "Relapse_Reason"])

        try:
            mood_sheet = spreadsheet.worksheet("MoodLog")
        except gspread.exceptions.WorksheetNotFound:
            mood_sheet = spreadsheet.add_worksheet(title="MoodLog", rows="1000", cols="4")
            mood_sheet.append_row(["Timestamp", "Chat_ID", "Mood", "Craving_Reason"])

        logger.info("Successfully connected to Google Sheets.")
except Exception as e:
    logger.error(f"An error occurred during Google Sheets setup: {e}")

# --- SHORTENED message lists (for brevity, use your full version here) ---
motivateMessages = [
    "You've come so far—one more alcohol-free day makes your mind stronger. 💪 | သင်ဟာ ခရီး weit weit ရောက်နေပါပြီ။ အရက်မသောက်တဲ့ နောက်ထပ်တစ်ရက်က သင့်စိတ်ကို ပိုပြီးကြံ့ခိုင်စေပါတယ်။ 💪",
    "Remember why you started. That reason is more powerful than any craving. ✨ | သင်ဘာကြောင့်စတင်ခဲ့သလဲဆိုတာကို ပြန်သတိရပါ။ အဲ့ဒီအကြောင်းผลက ဘယ်လိုတောင့်တမှုမျိုးထက်မဆို ပိုပြီးအစွမ်းထက်ပါတယ်။ ✨",
    "Every day you choose not to drink, you are healing. Be proud of that. 🌱 | သင်အရက်မသောက်ဖို့ ရွေးချယ်လိုက်တဲ့နေ့တိုင်းဟာ သင်ကိုယ်တိုင် ပြန်လည်ကုစားနေတာပါပဲ။ အဲ့ဒီအတွက် ဂုဏ်ယူပါ။ 🌱",
    "This moment will pass. Stay strong, and you'll wake up grateful tomorrow. 🌅 | ဒီအချိန်လေးက ပြီးသွားမှာပါ။ စိတ်ဓာတ်ခိုင်ခိုင်ထားပါ၊ မနက်ဖြန်နိုးလာတဲ့အခါ သင်ကျေးဇူးတင်နေပါလိမ့်မယ်။ 🌅",
    "Your future self will thank you for the choice you're making right now. ⏳ | သင်အခုချလိုက်တဲ့ ဆုံးဖြတ်ချက်အတွက် သင့်ရဲ့အနာဂတ်က သင့်ကိုကျေးဇူးတင်ပါလိမ့်မယ်။ ⏳",
    "Each sober day is a victory. Celebrate this win! 🏆 | အရက်မသောက်တဲ့နေ့တိုင်းဟာ အောင်ပွဲတစ်ခုပါ။ ဒီအောင်ပွဲကို ဂုဏ်ပြုလိုက်ပါ။ 🏆",
    "You are reclaiming your health, your time, and your peace. 🧘 | သင်ဟာ သင့်ကျန်းမာရေး၊ သင့်အချိန်နဲ့ သင့်ရဲ့ငြိမ်းချမ်းမှုကို ပြန်လည်ရယူနေတာပါ။ 🧘",
    "One day at a time. That's all it takes. You're doing it right now. 🕰️ | တစ်နေ့ချင်းစီပေါ့။ ဒါလေးပဲ လိုအပ်တာပါ။ သင်အခု လုပ်ဆောင်နေနိုင်ပါတယ်။ 🕰️",
    "Think of all the mornings you'll wake up clear-headed and proud. 🌞 | ကြည်လင်တဲ့စိတ်နဲ့ ဂုဏ်ယူစွာ နိုးထရမယ့် မနက်ခင်းတွေအကြောင်း စဉ်းစားပါ။ 🌞",
    "Your body is thanking you for this break. Listen to it. 🙏 | သင့်ခန္ဓာကိုယ်က ဒီလို အနားပေးတဲ့အတွက် သင့်ကို ကျေးဇူးတင်နေပါတယ်။ သူ့စကားကို နားထောင်ပါ။ 🙏",
    "Sobriety is a superpower. You're getting stronger every single day. 🦸 | အရက်ကင်းစင်ခြင်းဟာ စွမ်းအားတစ်ခုပါပဲ။ သင်နေ့တိုင်း ပိုပြီး သန်မာလာနေပါတယ်။ 🦸",
    "Don't let a bad moment ruin a day's progress. You are still moving forward. 🚶 | မကောင်းတဲ့ အခိုက်အတန့်တစ်ခုကြောင့် ကောင်းမွန်တဲ့နေ့တစ်နေ့ရဲ့ တိုးတက်မှုကို အဖျက်ဆီးမခံပါနဲ့။ သင်ရှေ့ဆက်သွားနေတုန်းပါပဲ။ 🚶",
    "The best apology to yourself is changed behavior. You're doing it. 💖 | ကိုယ့်ကိုယ်ကိုတောင်းပန်ဖို့ အကောင်းဆုံးနည်းလမ်းက အပြုအမူကိုပြောင်းလဲခြင်းပါပဲ။ သင်လုပ်ဆောင်နေပါတယ်။ 💖",
    "Clarity is a beautiful gift you're giving yourself. 🎁 | ကြည်လင်ပြတ်သားမှုဆိုတာ သင်ကိုယ့်ကိုယ်ကိုပေးနေတဲ့ လှပတဲ့လက်ဆောင်တစ်ခုပါ။ 🎁",
    "You are choosing freedom over a cage. Celebrate that freedom. 🕊️ | သင်ဟာ လှောင်အိမ်တစ်ခုအစား လွတ်လပ်မှုကို ရွေးချယ်နေတာပါ။ အဲ့ဒီလွတ်လပ်မှုကို ဂုဏ်ပြုပါ။ 🕊️",
    "Your journey inspires more people than you know. 🌟 | သင်ရဲ့ခရီးက သင်ထင်ထားတာထက် လူအများကြီးကို အားကျစေပါတယ်။ 🌟",
    "With every 'no' to alcohol, you're saying 'yes' to a better life. 👍 | အရက်ကို 'نه' လို့ပြောလိုက်တိုင်း ပိုကောင်းတဲ့ဘဝကို 'ဟုတ်ကဲ့' လို့ ပြောနေတာပါပဲ။ 👍",
    "This path isn't easy, but it is worth it. Keep going. 🛤️ | ဒီလမ်းက မလွယ်ကူပါဘူး၊ ဒါပေမယ့် တန်ပါတယ်။ ရှေ့ဆက်လျှောက်ပါ။ 🛤️",
    "You are rewriting your story, one sober day at a time. 📖 | သင်ဟာ သင့်ရဲ့ဇတ်လမ်းကို အရက်မသောက်တဲ့နေ့တစ်နေ့ချင်းစီနဲ့ ပြန်လည်ရေးသားနေတာပါ။ 📖",
    "The peace you're building within yourself is unbreakable. 💎 | သင် သင့်အတွင်းစိတ်ထဲမှာ တည်ဆောက်နေတဲ့ ငြိမ်းချမ်းမှုက မပျက်စီးနိုင်ပါဘူး။ 💎",
    "Let your progress be your motivation. Look how far you've come! 📈 | သင်ရဲ့တိုးတက်မှုကို သင်ရဲ့ခွန်အားအဖြစ်သုံးပါ။ သင်ဘယ်လောက် weit weit ရောက်နေပြီလဲ ကြည့်လိုက်ပါ။ 📈",
    "You are stronger than your cravings. Remember that. 💪 | သင်ဟာ သင့်ရဲ့တောင့်တမှုတွေထက် ပိုပြီးသန်မာပါတယ်။ ဒါကိုသတိရပါ။ 💪",
    "Choosing sobriety is an act of radical self-love. ❤️ | အရက်ကင်းစင်မှုကိုရွေးချယ်ခြင်းဟာ ကိုယ့်ကိုယ်ကို အဆုံးစွန်ချစ်ခြင်းတစ်မျိုးပါပဲ။ ❤️",
    "Every sunrise is a new opportunity to honor your commitment. 🌅 | နေထွက်ချိန်တိုင်းဟာ သင်ရဲ့ကတိကို လေးစားလိုက်နာဖို့ အခွင့်အရေးသစ်တစ်ခုပါ။ 🌅",
    "The small steps each day add up to a huge transformation. 🪜 | နေ့စဉ်လှမ်းနေတဲ့ ခြေလှမ်းသေးသေးလေးတွေက ကြီးမားတဲ့ပြောင်းလဲမှုကြီးတစ်ခု ဖြစ်လာစေပါတယ်။ 🪜",
    "You are capable of amazing things, and this is one of them. ✨ | သင်ဟာ အံ့ဩစရာကောင်းတဲ့အရာတွေကို လုပ်ဆောင်နိုင်စွမ်းရှိပြီး၊ ဒါက အဲ့ဒီထဲကတစ်ခုပါပဲ။ ✨",
    "Feel the pride in knowing you are in control of your choices. 🎮 | သင်ဟာ သင့်ရဲ့ရွေးချယ်မှုတွေကို ထိန်းချုပ်နိုင်တယ်ဆိုတာသိခြင်းရဲ့ ဂုဏ်ယူမှုကို ခံစားလိုက်ပါ။ 🎮",
    "Your mind is becoming clearer, and your spirit is becoming lighter. 🕊️ | သင့်စိတ်တွေ ပိုကြည်လင်လာပြီး သင့်ရဲ့ဝိညာဉ်က ပိုပေါ့ပါးလာနေပါတယ်။ 🕊️",
    "This journey is about progress, not perfection. Keep making progress. 👣 | ဒီခရီးက ပြည့်စုံဖို့မဟုတ်ဘဲ တိုးတက်ဖို့အတွက်ပါ။ ဆက်ပြီးတိုးတက်အောင်လုပ်ဆောင်ပါ။ 👣",
    "You are building a foundation for a happier, healthier future. 🏗️ | သင်ဟာ ပိုပျော်ရွှင်ပြီး ကျန်းမာတဲ့အနာဂတ်အတွက် အခြေခံအုတ်မြစ်ကို တည်ဆောက်နေတာပါ။ 🏗️",
    "The strength you're showing is incredible. Don't ever forget that. 💥 | သင်ပြသနေတဲ့ ကြံ့ခိုင်မှုက မယုံနိုင်စရာပါပဲ။ ဒါကို ဘယ်တော့မှမမေ့ပါနဲ့။ 💥",
    "Let go of who you were. Focus on who you are becoming. 🦋 | သင်ဘယ်သူဖြစ်ခဲ့လဲဆိုတာကို လက်လွှတ်လိုက်ပါ။ သင်ဘယ်သူဖြစ်လာနေလဲဆိုတာကိုပဲ အာရုံစိုက်ပါ။ 🦋",
    "You're not giving anything up; you're gaining everything back. 💯 | သင်ဘာကိုမှ စွန့်လွှတ်နေတာမဟုတ်ပါဘူး၊ သင်အရာအားလုံးကို ပြန်ရယူနေတာပါ။ 💯",
    "Your resilience is your greatest asset on this journey. 🛡️ | သင်ရဲ့ခံနိုင်ရည်ရှိမှုက ဒီခရီးမှာ သင့်ရဲ့အကြီးမားဆုံး အားသာချက်ပါပဲ။ 🛡️",
    "Keep your 'why' in your heart. It will guide you through the tough moments. ❤️‍🔥 | သင်ရဲ့ 'ဘာကြောင့်လဲ' ဆိုတဲ့အကြောင်းผลကို နှလုံးသားထဲမှာထားပါ။ ခက်ခဲတဲ့အချိန်တွေမှာ ဒါက သင့်ကိုလမ်းပြပါလိမ့်မယ်။ ❤️‍🔥",
    "The best version of you is waiting. Keep walking towards them. 🌟 | သင့်ရဲ့အကောင်းဆုံးဗားရှင်းက စောင့်နေပါတယ်။ သူတို့ဆီကို ဆက်လျှောက်သွားပါ။ 🌟",
    "Every moment you choose sobriety, you win. Keep winning. 🏅 | သင်အရက်ကင်းစင်မှုကို ရွေးချယ်လိုက်တဲ့အချိန်တိုင်း သင်နိုင်ပါတယ်။ ဆက်ပြီးအနိုင်ယူပါ။ 🏅",
    "Trust the process. Healing takes time, and you're giving yourself that time. ⏳ | လုပ်ငန်းစဉ်ကို ယုံကြည်လိုက်ပါ။ ကုစားခြင်းက အချိန်ယူရပြီး သင်က ကိုယ့်ကိုယ်ကို အဲ့ဒီအချိန်ကို ပေးနေတာပါ။ ⏳",
    "You are proving to yourself that you can do hard things. 🙌 | သင်ဟာ ခက်ခဲတဲ့အရာတွေကို လုပ်နိုင်တယ်ဆိုတာကို ကိုယ့်ကိုယ်ကို သက်သေပြနေတာပါ။ 🙌",
    "Your mind is a garden. By not drinking, you're pulling the weeds. 🌿 | သင့်စိတ်က ဥယျာဉ်တစ်ခုပါ။ အရက်မသောက်ခြင်းအားဖြင့် သင်ပေါင်းပင်တွေကို ရှင်းနေတာပါ။ 🌿",
    "Be patient with yourself. You are unlearning years of habits. 🐢 | ကိုယ့်ကိုယ်ကို စိတ်ရှည်ပါ။ သင်ဟာ နှစ်ပေါင်းများစွာက အကျင့်တွေကို ပြန်လည်ပြုပြင်နေတာပါ။ 🐢",
    "The energy you're saving is being invested in your growth. 🔋 | သင်ချွေတာနေတဲ့ စွမ်းအင်တွေက သင်ရဲ့ကြီးထွားမှုမှာ ရင်းနှီးမြှုပ်နှံနေတာပါ။ 🔋",
    "Notice the small joys that sobriety brings back into your life. 😊 | အရက်ကင်းစင်မှုက သင့်ဘဝထဲကို ပြန်ယူဆောင်လာတဲ့ ပျော်ရွှင်မှုသေးသေးလေးတွေကို သတိပြုပါ။ 😊",
    "You are not alone on this path. We are here with you. 🤝 | ဒီလမ်းမှာ သင်တစ်ယောက်တည်းမဟုတ်ပါဘူး။ ကျွန်တော်တို့ သင်နဲ့အတူရှိပါတယ်။ 🤝",
    "Your commitment to yourself is the ultimate act of strength. 💪 | သင်ကိုယ့်ကိုယ်ကို ပေးထားတဲ့ကတိက အခိုင်မာဆုံးသော စွမ်းအားတစ်ခုပါပဲ။ 💪",
    "Let peace of mind be your new addiction. 🧘‍♀️ | စိတ်၏ငြိမ်းချမ်းမှုကို သင်ရဲ့စွဲလမ်းမှုအသစ်ဖြစ်ပါစေ။ 🧘‍♀️",
    "You are worthy of a life free from the grip of alcohol. 💖 | သင်ဟာ အရက်ရဲ့ချုပ်ကိုင်မှုကနေ လွတ်မြောက်တဲ့ဘဝနဲ့ ထိုက်တန်ပါတယ်။ 💖",
    "Look in the mirror and be proud of the person looking back at you. ✨ | မှန်ထဲမှာကိုယ့်ကိုယ်ကိုကြည့်ပြီး ပြန်ကြည့်နေတဲ့သူအတွက် ဂုဏ်ယူလိုက်ပါ။ ✨",
    "Today, you are choosing you. And that's the most important choice. 🥇 | ဒီနေ့၊ သင်က သင့်ကိုယ်သင် ရွေးချယ်ခဲ့တယ်။ ဒါက အရေးကြီးဆုံး ရွေးချယ်မှုပါပဲ။ 🥇"
    ]
focusMessages = [
    "Breathe in for 4 seconds, hold for 4, and breathe out for 6. Repeat 5 times. You are in control. 🌬️ | ၄ စက္ကန့်လောက် အသက်ရှူသွင်း၊ ၄ စက္ကန့်အောင့်ထားပြီး ၆ စက္ကန့်ကြာအောင် အသက်ရှူထုတ်ပါ။ ၅ ကြိမ်လုပ်ပါ။ သင်ထိန်းချုပ်နိုင်ပါတယ်။ 🌬️",
    "Find a quiet spot. Close your eyes and name 3 things you can hear. It brings you back to the present moment. 🧘 | တိတ်ဆိတ်တဲ့နေရာတစ်ခုရှာပါ။ မျက်စိမှိတ်ပြီး သင်ကြားနေရတဲ့အသံ ၃ ခုကို အမည်တပ်ကြည့်ပါ။ ဒါက သင့်ကို ပစ္စုပ္ပန်တည့်တည့်ကို ပြန်ခေါ်လာပါလိမ့်မယ်။ 🧘",
    "Splash some cold water on your face. It's a simple pattern interrupt that can reset your mind. 💧 | မျက်နှာကို ရေအေးအေးနဲ့ ပက်ဖျန်းလိုက်ပါ။ ဒါက သင့်စိတ်ကိုချက်ချင်းပြန်လည်လန်းဆန်းစေနိုင်တဲ့ နည်းလမ်းကောင်းတစ်ခုပါ။ 💧",
    "Slowly sip a glass of cold water. Focus only on the sensation of the water. 🧊 | ရေအေးတစ်ခွက်ကို ဖြည်းဖြည်းချင်းသောက်ပါ။ ရေရဲ့အထိအတွေ့ကိုပဲ အာရုံစိုက်ပါ။ 🧊",
    "Hold a piece of ice in your hand. Focus on the cold sensation until it melts. ❄️ | ရေခဲတုံးတစ်တုံးကို လက်ထဲမှာကိုင်ထားပါ။ အရည်ပျော်သွားတဲ့အထိ အေးစက်တဲ့ ခံစားမှုကိုပဲ အာရုံစိုက်ပါ။ ❄️",
    "Step outside for a minute. What's the temperature like? Can you feel a breeze? 🍃 | အပြင်ကို ခဏထွက်လိုက်ပါ။ အပူချိန် ဘယ်လိုနေလဲ။ လေပြေလေးကို ခံစားမိလား။ 🍃",
    "Put on your favorite calming song and just listen. Nothing else. 🎶 | သင်အကြိုက်ဆုံး စိတ်ငြိမ်စေတဲ့ သီချင်းကိုဖွင့်ပြီး နားထောင်လိုက်ပါ။ တခြားဘာမှ မလုပ်ပါနဲ့။ 🎶",
    "Look around you and find 5 blue things. Name them out loud. 🔵 | သင့်ပတ်ဝန်းကျင်ကိုကြည့်ပြီး အပြာရောင်ပစ္စည်း ၅ ခုကို ရှာပါ။ သူတို့ကို အသံထွက်ပြီး နာမည်ပြောကြည့်ပါ။ 🔵",
    "Tense all the muscles in your body for 5 seconds, then release. Feel the tension leaving. 😌 | သင့်ခန္ဓာကိုယ်က ကြွက်သားအားလုံးကို ၅ စက္ကန့်လောက်တင်းထားပြီးမှ လွှတ်လိုက်ပါ။ တင်းအားတွေ ထွက်သွားတာကို ခံစားလိုက်ပါ။ 😌",
    "Write down three things you are grateful for right now. ✍️ | သင်အခုအချိန်မှာ ကျေးဇူးတင်နေတဲ့အရာ ၃ ခုကို ချရေးလိုက်ပါ။ ✍️",
    "Watch a short, funny video online. Laughter is a great distraction. 😂 | အွန်လိုင်းပေါ်က ဟာသဗီဒီယိုတိုလေးတစ်ခု ကြည့်လိုက်ပါ။ ရယ်မောခြင်းက အာရုံလွှဲဖို့ အကောင်းဆုံးနည်းလမ်းတစ်ခုပါ။ 😂",
    "Do a simple 5-minute stretch. Focus on how your muscles feel. 🤸 | ၅ မိနစ်စာ ရိုးရှင်းတဲ့ အကြောလျှော့လေ့ကျင့်ခန်းလုပ်ပါ။ သင့်ကြွက်သားတွေ ဘယ်လိုခံစားရလဲဆိုတာကို အာရုံစိုက်ပါ။ 🤸",
    "Organize a small part of your room, like a drawer or a shelf. 整理 | သင့်အခန်းရဲ့ အစိတ်အပိုင်းသေးသေးလေးတစ်ခုကို စည်းဘောင်ကျအောင်လုပ်ပါ၊ ဥပမာ အံဆွဲတစ်ခု (သို့) စင်တစ်ခု။ 整理",
    "Smell something pleasant, like coffee, a flower, or a scented candle. 👃 | မွှေးရနံ့တစ်ခုခုကို ရှူရှိုက်ပါ၊ ဥပမာ ကော်ဖီ၊ ပန်း (သို့) အမွှေးတိုင်။ 👃",
    "Press your fingertips together firmly for 10 seconds. Focus on the pressure. 👉👈 | သင့်လက်ချောင်းထိပ်တွေကို စက္ကန့် ၃၀ လောက် ဖိထားပါ။ အဲ့ဒီဖိအားကိုပဲ အာရုံစိုက်ပါ။ 👉👈",
    "Say the alphabet backward. It requires concentration and distracts your mind. 🧠 | အက္ခရာတွေကို နောက်ပြန်ပြောကြည့်ပါ။ ဒါက အာရုံစူးစိုက်မှုလိုအပ်ပြီး သင့်စိတ်ကို အာရုံလွှဲပေးပါတယ်။ 🧠",
    "Look at a detailed picture or a plant. Notice all the small details. 🖼️ | အသေးစိတ်များတဲ့ ပုံတစ်ပုံ (သို့) အပင်တစ်ပင်ကို ကြည့်ပါ။ အသေးစိတ်အချက်အလက်အားလုံးကို သတိပြုပါ။ 🖼️",
    "Make a cup of herbal tea and focus on the warmth and taste. 🍵 | ဆေးဖက်ဝင်လက်ဖက်ရည်တစ်ခွက်ဖျော်ပြီး အနွေးဓာတ်နဲ့ အရသာကို အာရုံစိုက်ပါ။ 🍵",
    "Count down from 100 by 7s. (100, 93, 86...). 🔢 | ၁၀၀ ကနေ ၇ စီနှုတ်ပြီး နောက်ပြန်ရေတွက်ပါ။ (၁၀၀၊ ၉၃၊ ၈၆...)။ 🔢",
    "Walk around your home and touch 5 different textures. Notice how they feel. 🖐️ | သင့်အိမ်ပတ်ပတ်လည်လမ်းလျှောက်ပြီး မတူညီတဲ့ အထိအတွေ့ ၅ ခုကို ထိကြည့်ပါ။ ဘယ်လိုခံစားရလဲ သတိပြုပါ။ 🖐️",
    "If you have a pet, spend a few minutes just petting them. 🐾 | သင့်မှာ အိမ်မွေးတိရစ္ဆာန်ရှိရင် သူတို့နဲ့ ခဏလောက် အတူနေပေးလိုက်ပါ။ 🐾",
    "Listen to a guided meditation for 5 minutes. Apps like Calm or Headspace are great. 🎧 | ၅ မိနစ်စာ တရားထိုင်လမ်းညွှန်တစ်ခု နားထောင်ပါ။ Calm (သို့) Headspace လို app တွေက အရမ်းကောင်းပါတယ်။ 🎧",
    "Doodle or draw whatever comes to mind on a piece of paper. 🖍️ | စာရွက်တစ်ရွက်ပေါ်မှာ စိတ်ထဲပေါ်လာတာကို ဖြစ်သလို ရေးခြစ်ဆွဲလိုက်ပါ။ 🖍️",
    "Name a country for each letter of the alphabet. 🌍 | အက္ခရာတစ်လုံးချင်းစီအတွက် နိုင်ငံတစ်နိုင်ငံစီရဲ့ နာမည်ကို ပြောကြည့်ပါ။ 🌍",
    "Do a simple chore, like washing the dishes. Focus on the task. 🧼 | ပန်းကန်ဆေးတာလိုမျိုး ရိုးရှင်းတဲ့ အိမ်အလုပ်တစ်ခုလုပ်ပါ။ အဲ့ဒီအလုပ်ပေါ်မှာပဲ အာရုံစိုက်ပါ။ 🧼",
    "Wiggle your toes and focus on the sensation in your feet. 👣 | သင့်ခြေချောင်းလေးတွေကို လှုပ်ရှားပြီး ခြေဖဝါးက ခံစားမှုကို အာရုံစိုက်ပါ။ 👣",
    "Think of a happy memory in detail. Who was there? What did it smell like? 🧠 | ပျော်စရာကောင်းတဲ့ အမှတ်တရတစ်ခုကို အသေးစိတ်ပြန်တွေးပါ။ ဘယ်သူတွေရှိခဲ့လဲ။ ဘယ်လိုအနံ့အသက်တွေရခဲ့လဲ။ 🧠",
    "Rub your hands together quickly until they're warm, then place them over your eyes. 🙏 | သင့်လက်တွေကို ပူလာတဲ့အထိ အမြန်ပွတ်ပြီး မျက်လုံးပေါ်မှာ အုပ်ထားလိုက်ပါ။ 🙏",
    "Chew a piece of gum or a mint. Focus on the flavor. 🍬 | ပီကေ (သို့) ပူရှိန်းသကြားလုံး ဝါးစားပါ။ အရသာကို အာရုံစိုက်ပါ။ 🍬",
    "Step into a different room. A change of scenery can change your mindset. 🚪 | တခြားအခန်းထဲကို ဝင်သွားလိုက်ပါ။ ပတ်ဝန်းကျင်ပြောင်းလဲခြင်းက သင့်စိတ်ကို ပြောင်းလဲစေနိုင်ပါတယ်။ 🚪",
    "Cross your arms and give yourself a gentle hug for 20 seconds. 🤗 | သင့်လက်တွေကို ယှက်ပြီး စက္ကန့် ၂၀ လောက် ကိုယ့်ကိုယ်ကို ညင်သာစွာပွေ့ဖက်ထားပါ။ 🤗",
    "Try the 5-4-3-2-1 grounding technique: 5 things you see, 4 you feel, 3 you hear, 2 you smell, 1 you taste. 👀 | 5-4-3-2-1 နည်းလမ်းကိုသုံးပါ: သင်မြင်ရတဲ့အရာ ၅ ခု၊ ခံစားရတဲ့အရာ ၄ ခု၊ ကြားရတဲ့အရာ ၃ ခု၊ အနံ့ရတဲ့အရာ ၂ ခု၊ အရသာခံလို့ရတဲ့အရာ ၁ ခု။ 👀",
    "Write a short, positive message to a friend or family member. 💬 | မိတ်ဆွေ (သို့) မိသားစုဝင်တစ်ယောက်ဆီကို အကောင်းမြင်တဲ့ စာတိုလေးတစ်စောင်ပို့လိုက်ပါ။ 💬",
    "If you're sitting, stand up. If you're standing, sit down. Change your posture. 🧍 | သင်ထိုင်နေတယ်ဆိုရင် မတ်တပ်ရပ်ပါ။ သင်ရပ်နေတယ်ဆိုရင် ထိုင်ချလိုက်ပါ။ သင့်ရဲ့အနေအထားကို ပြောင်းလဲလိုက်ပါ။ 🧍",
    "Visualize a calm place, like a beach or a forest. Imagine yourself there. 🏞️ | ငြိမ်းချမ်းတဲ့နေရာတစ်ခုကို စိတ်ကူးထဲမှာမြင်ယောင်ကြည့်ပါ၊ ဥပမာ ပင်လယ်ကမ်းခြေ (သို့) တောအုပ်တစ်ခု။ သင်အဲ့ဒီမှာရောက်နေတယ်လို့ စိတ်ကူးပါ။ 🏞️",
    "Hum a tune for one minute. The vibration can be calming. 🎶 | သီချင်းတစ်ပုဒ်ကို တစ်မိနစ်လောက် ညည်းကြည့်ပါ။ တုန်ခါမှုက စိတ်ကိုတည်ငြိမ်စေနိုင်ပါတယ်။ 🎶",
    "Read one page of a book. It's a simple escape. 📖 | စာအုပ်တစ်အုပ်ရဲ့ စာမျက်နှာတစ်မျက်နှာကို ဖတ်ပါ။ ဒါက ရိုးရှင်းတဲ့ လွတ်မြောက်မှုတစ်ခုပါ။ 📖",
    "Look out a window and describe 10 things you see in detail. 🖼️ | ပြတင်းပေါက်ကနေ အပြင်ကိုကြည့်ပြီး သင်မြင်ရတဲ့အရာ ၁၀ ခုကို အသေးစိတ်ဖော်ပြပါ။ 🖼️",
    "Solve a simple puzzle, like a Sudoku or a crossword. 🧩 | Sudoku (သို့) စကားလုံးဆက်ပဟေဠိလိုမျိုး ရိုးရှင်းတဲ့ puzzle တစ်ခုကို ဖြေရှင်းပါ။ 🧩",
    "Clench your fist tightly for 10 seconds, then release it. Notice the difference. ✊ | သင့်လက်သီးကို စက္ကန့် ၃၀ လောက် တင်းတင်းဆုပ်ထားပြီးမှ လွှတ်လိုက်ပါ။ ကွာခြားမှုကို သတိပြုပါ။ ✊",
    "Drink a cup of hot chocolate. The warmth and sweetness can be comforting. ☕ | ချောကလက်ပူပူတစ်ခွက်သောက်ပါ။ အနွေးဓာတ်နဲ့ အချိုဓာတ်က နှစ်သိမ့်မှုပေးနိုင်ပါတယ်။ ☕",
    "Put your phone away for 10 minutes. No screens, just be with your thoughts. 📵 | သင့်ဖုန်းကို ၁၀ မိနစ်လောက် ဘေးဖယ်ထားပါ။ မျက်နှာပြင်မကြည့်ဘဲ သင့်အတွေးတွေနဲ့ပဲ နေပါ။ 📵",
    "List 3 of your personal strengths. Remind yourself of what you're good at. 💪 | သင်ရဲ့အားသာချက် ၃ ခုကို စာရင်းလုပ်ပါ။ သင်ဘာတွေတော်လဲဆိုတာ ကိုယ့်ကိုယ်ကို သတိပေးပါ။ 💪",
    "Imagine the craving as a wave. Watch it rise, crest, and then fall away. 🌊 | တောင့်တမှုကို လှိုင်းလုံးတစ်ခုလို သဘောထားပါ။ သူတက်လာတာ၊ အမြင့်ဆုံးရောက်တာ၊ ပြီးတော့ ပြန်ကျသွားတာကို စောင့်ကြည့်ပါ။ 🌊",
    "Do 10 simple jumping jacks or run in place for a minute. 🏃 | Jumping jack ၁၀ ခါ (သို့) နေရာမှာပဲ တစ်မိနစ်လောက် ပြေးပါ။ 🏃",
    "Repeat a calming mantra, such as 'This too shall pass' or 'I am calm'. 🙏 | 'ဒါလည်း ပြီးသွားမှာပါ' (သို့) 'ငါ စိတ်တည်ငြိမ်တယ်' လိုမျိုး စိတ်ငြိမ်စေတဲ့ စာသားတစ်ခုကို ထပ်ခါထပ်ခါ ရွတ်ဆိုပါ။ 🙏",
    "Plan a healthy meal for later. It gives you something positive to focus on. 🥗 | နောက်ပိုင်းစားဖို့ ကျန်းမာတဲ့အစားအစာတစ်ခု စီစဉ်ပါ။ ဒါက သင့်ကို အကောင်းမြင်တဲ့အရာတစ်ခုပေါ်မှာ အာရုံစိုက်စေပါတယ်။ 🥗",
    "Gently massage your hands or neck for a few minutes. 💆 | သင့်လက် (သို့) လည်ပင်းကို မိနစ်အနည်းငယ်လောက် ညင်သာစွာ နှိပ်နယ်ပေးပါ။ 💆",
    "Think about one small goal you can accomplish today. Break it down into steps. 📝 | ဒီနေ့ သင်ပြီးမြောက်နိုင်တဲ့ ပန်းတိုင်သေးသေးလေးတစ်ခုအကြောင်း စဉ်းစားပါ။ သူ့ကို အဆင့်လေးတွေခွဲလိုက်ပါ။ 📝"
    ]
rewardMessages = [
   "Treat yourself to your favorite meal tonight. You've earned it! 🍕 | ဒီည သင်အကြိုက်ဆုံးအစားအစာနဲ့ ကိုယ့်ကိုယ်ကို ဆုချပါ။ သင်နဲ့ထိုက်တန်ပါတယ်။ 🍕",
    "Watch that movie you've been wanting to see. Relax and enjoy. 🎬 | သင်ကြည့်ချင်နေတဲ့ ရုပ်ရှင်ကိုကြည့်လိုက်ပါ။ အပန်းဖြေပြီး ပျော်ရွှင်လိုက်ပါ။ 🎬",
    "Go for a a walk and listen to a podcast or your favorite music. 🎧 | လမ်းထွက်လျှောက်ပြီး podcast (သို့) သင်အကြိုက်ဆုံးသီချင်းကို နားထောင်ပါ။ 🎧",
    "Buy that book you've had your eye on. A reward for your mind. 📚 | သင်မျက်စိကျနေတဲ့ စာအုပ်ကိုဝယ်လိုက်ပါ။ သင့်ဦးနှောက်အတွက် ဆုတစ်ခုပေါ့။ 📚",
    "Take a long, warm bath or shower. Give yourself time to relax. 🛀 | ရေနွေးနွေးနဲ့ အချိန်ကြာကြာ ရေချိုး/စိမ်ပါ။ ကိုယ့်ကိုယ်ကို အနားပေးဖို့ အချိန်ပေးလိုက်ပါ။ 🛀",
    "Start a new TV series you've been wanting to watch. 📺 | သင်ကြည့်ချင်နေတဲ့ TV series အသစ်တစ်ခုကို စကြည့်လိုက်ပါ။ 📺",
    "Cook or order a fancy dessert. Enjoy every bite. 🍰 | အရသာရှိတဲ့ အချိုပွဲတစ်ခုကို ချက်စားပါ (သို့) မှာစားပါ။ တစ်ကိုက်ချင်းစီကို အရသာခံစားပါ။ 🍰",
    "Spend an hour on a hobby you love, guilt-free. 🎨 | သင်နှစ်သက်တဲ့ ဝါသနာတစ်ခုပေါ်မှာ အပြစ်မခံစားရဘဲ တစ်နာရီလောက် အချိန်ပေးလိုက်ပါ။ 🎨",
    "Plan a small day trip for the weekend. 🗺️ | စနေ၊တနင်္ဂနွေအတွက် ခရီးတိုလေးတစ်ခု စီစဉ်လိုက်ပါ။ 🗺️",
    "Buy a new plant for your room. It adds life and positivity. 🪴 | သင့်အခန်းအတွက် အပင်အသစ်တစ်ပင် ဝယ်လိုက်ပါ။ ဒါက ජීවနဲ့ အကောင်းမြင်စိတ်ကို တိုးစေပါတယ်။ 🪴",
    "Try a new recipe you've found online. 👨‍🍳 | အွန်လိုင်းမှာတွေ့ထားတဲ့ ဟင်းချက်နည်းအသစ်တစ်ခုကို စမ်းချက်ကြည့်ပါ။ 👨‍🍳",
    "Have a video call with a friend or family member you miss. 💻 | သင်လွမ်းနေတဲ့ မိတ်ဆွေ (သို့) မိသားစုဝင်တစ်ယောက်နဲ့ video call ပြောပါ။ 💻",
    "Take a nap without setting an alarm. 😴 | နှိုးစက်မပေးဘဲ တစ်ရေးအိပ်လိုက်ပါ။ 😴",
    "Buy yourself a small gift you've been wanting. 🎁 | သင်လိုချင်နေတဲ့ လက်ဆောင်သေးသေးလေးတစ်ခု ကိုယ့်ကိုယ်ကို ဝယ်ပေးလိုက်ပါ။ 🎁",
    "Visit a museum or art gallery. 🏛️ | ပြတိုက် (သို့) အနုပညာပြခန်းတစ်ခုကို သွားလည်ပါ။ 🏛️",
    "Spend some time in nature, like a park or by a lake. 🌳 | ပန်းခြံ (သို့) ကန်ဘေးလိုမျိုး သဘာဝထဲမှာ အချိန်အနည်းငယ်ကုန်ဆုံးပါ။ 🌳",
    "Get a massage or a manicure/pedicure. 💅 | Massage (သို့) လက်/ခြေသည်းနီဆိုးတာမျိုး လုပ်ပါ။ 💅",
    "Listen to a full album from an artist you love, from start to finish. 🎶 | သင်နှစ်သက်တဲ့ အဆိုတော်တစ်ယောက်ရဲ့ album တစ်ခုလုံးကို အစအဆုံးနားထောင်ပါ။ 🎶",
    "Do a home workout or some yoga. Reward your body with movement. 🧘‍♂️ | အိမ်မှာ လေ့ကျင့်ခန်းလုပ်ပါ (သို့) ယောဂကျင့်ပါ။ သင့်ခန္ဓာကိုယ်ကို လှုပ်ရှားမှုနဲ့ ဆုချပါ။ 🧘‍♂️",
    "Declutter and organize your space. A clean room is a clean mind. ✨ | သင့်နေရာကို ရှင်းလင်းပြီး စည်းကမ်းတကျထားပါ။ သန့်ရှင်းတဲ့အခန်းက သန့်ရှင်းတဲ့စိတ်ကို ဖြစ်စေပါတယ်။ ✨",
    "Learn a new skill online, like a new language or how to code. 💡 | ဘာသာစကားအသစ် (သို့) code ရေးနည်းလိုမျိုး အွန်လိုင်းကနေ သင်ခန်းစာအသစ်တစ်ခု သင်ယူပါ။ 💡",
    "Watch the sunset or sunrise. 🌅 | နေဝင်ချိန် (သို့) နေထွက်ချိန်ကို ကြည့်ပါ။ 🌅",
    "Write in a journal about your progress and how you're feeling. 📔 | သင်ရဲ့တိုးတက်မှုနဲ့ ခံစားချက်တွေအကြောင်း ဂျာနယ်ထဲမှာ ချရေးပါ။ 📔",
    "Try a new type of coffee or tea from a local cafe. ☕ | ဒေသကော်ဖီဆိုင်တစ်ခုက ကော်ဖီ (သို့) လက်ဖက်ရည်အမျိုးအစားအသစ်တစ်ခုကို စမ်းသောက်ကြည့်ပါ။ ☕",
    "Play a board game or a video game. 🎲 | Board game (သို့) video game ကစားပါ။ 🎲",
    "Re-watch your favorite comfort movie. 🍿 | သင်အကြိုက်ဆုံး ကြည့်နေကျရုပ်ရှင်ကို ပြန်ကြည့်ပါ။ 🍿",
    "Bake cookies or a cake. The process can be very therapeutic. 🍪 | ကွတ်ကီး (သို့) ကိတ်မုန့် ဖုတ်ပါ။ ဒီလုပ်ငန်းစဉ်က စိတ်ကိုအလွန်ကုစားပေးနိုင်ပါတယ်။ 🍪",
    "Go for a scenic drive. 🚗 | ရှုခင်းလှတဲ့နေရာကို ကားမောင်းထွက်ပါ။ 🚗",
    "Start planning your next vacation, even if it's far away. ✈️ | သင်ရဲ့နောက်ခရီးစဉ်ကို စီစဉ်ပါ၊ weit weit မှာဖြစ်နေရင်တောင်မှပေါ့။ ✈️",
    "Buy some new comfortable clothes, like a new hoodie or pajamas. 👕 | Hoodie အသစ် (သို့) ညဝတ်အိပ်စုံအသစ်လိုမျိုး သက်တောင့်သက်သာရှိတဲ့ အဝတ်အစားအသစ်တွေဝယ်ပါ။ 👕",
    "Donate to a charity you care about. Giving back feels good. ❤️ | သင်ဂရုစိုက်တဲ့ ပရဟိတလုပ်ငန်းတစ်ခုမှာ လှူဒါန်းပါ။ ပြန်လည်ပေးကမ်းခြင်းက ခံစားချက်ကောင်းစေပါတယ်။ ❤️",
    "Create a new music playlist. 🎶 | သီချင်း playlist အသစ်တစ်ခု ဖန်တီးပါ။ 🎶",
    "Visit a local market and buy some fresh produce. 🍓 | ဒေသဈေးတစ်ခုကိုသွားပြီး လတ်ဆတ်တဲ့ သစ်သီးဝလံတွေ ဝယ်ပါ။ 🍓",
    "Take a day off from social media. 📵 | လူမှုကွန်ရက်ကနေ တစ်ရက်လောက် အနားယူပါ။ 📵",
    "Light some candles and create a cozy atmosphere at home. 🕯️ | ဖယောင်းတိုင်တွေထွန်းပြီး အိမ်မှာ နွေးထွေးတဲ့ဝန်းကျင်တစ်ခု ဖန်တီးပါ။ 🕯️",
    "Go stargazing on a clear night. ✨ | ကြည်လင်တဲ့ညမှာ ကြယ်တွေကို သွားကြည့်ပါ။ ✨",
    "Do some gardening or potting a new plant. 🌱 | ဥယျာဉ်စိုက်ပျိုးတာ (သို့) အပင်အသစ်စိုက်တာမျိုး လုပ်ပါ။ 🌱",
    "Try a new restaurant in your city. 🍜 | သင့်မြို့က စားသောက်ဆိုင်အသစ်တစ်ခုမှာ စမ်းစားကြည့်ပါ။ 🍜",
    "Go to bed an hour earlier than usual. 🌙 | ပုံမှန်ထက် တစ်နာရီစောပြီး အိပ်ရာဝင်ပါ။ 🌙",
    "Write a letter to your future self. 💌 | သင်ရဲ့အနာဂတ်ကိုယ်သင်ဆီကို စာတစ်စောင်ရေးပါ။ 💌",
    "Go swimming or spend time near water. 🌊 | ရေသွားကူးပါ (သို့) ရေအနီးအနားမှာ အချိန်ကုန်ဆုံးပါ။ 🌊",
    "Learn to play a simple song on an instrument. 🎸 | တူရိယာတစ်ခုပေါ်မှာ ရိုးရှင်းတဲ့သီချင်းတစ်ပုဒ် တီးတတ်အောင်သင်ယူပါ။ 🎸",
    "Watch stand-up comedy. Laughter is the best medicine. 😂 | ဟာသပွဲတစ်ခု ကြည့်ပါ။ ရယ်မောခြင်းက အကောင်းဆုံးဆေးတစ်ခွက်ပါ။ 😂",
    "Do a DIY project you've been putting off. 🛠️ | သင်ရွှေ့ဆိုင်းထားတဲ့ DIY project တစ်ခုကို လုပ်ပါ။ 🛠️",
    "Listen to an inspiring talk or interview. 🎤 | အားကျစရာကောင်းတဲ့ ဟောပြောပွဲ (သို့) အင်တာဗျူးတစ်ခု နားထောင်ပါ။ 🎤",
    "Visit an animal shelter and spend time with the animals. 🐶 | တိရစ္ဆာန်ဂေဟာတစ်ခုကိုသွားပြီး တိရစ္ဆာန်တွေနဲ့ အချိန်ကုန်ဆုံးပါ။ 🐶",
    "Spend quality time with a loved one, distraction-free. ❤️ | ချစ်ရသူတစ်ယောက်နဲ့ အာရုံမပျံ့လွင့်ဘဲ အရည်အသွေးရှိတဲ့အချိန်ကို ကုန်ဆုံးပါ။ ❤️",
    "Explore a part of your city you've never been to before. 🏙️ | သင်မရောက်ဖူးသေးတဲ့ သင့်မြို့ရဲ့ အစိတ်အပိုင်းတစ်ခုကို စူးစမ်းလေ့လာပါ။ 🏙️",
    "Simply sit in silence for 10 minutes and enjoy the peace. 🧘‍♀️ | ၁၀ မိနစ်လောက် တိတ်ဆိတ်စွာထိုင်ပြီး ငြိမ်းချမ်းမှုကို ခံစားလိုက်ပါ။ 🧘‍♀️"
    ]
cravingSupportMessages = [
    "It's okay to feel this way. The feeling is temporary. Can you try a focus exercise with /focus? ✨ | ဒီလိုခံစားရတာ ဖြစ်တတ်ပါတယ်။ ဒီခံစားချက်က ခဏပါပဲ။ /focus command နဲ့ လေ့ကျင့်ခန်းတစ်ခုခု လုပ်ကြည့်လို့ရမလား? ✨",
    "I hear you. Remember the last time you felt great waking up without a hangover? Let's aim for that again. 🌅 | ကျွန်တော်နားလည်ပါတယ်။ အရက်နာမကျဘဲ နိုးထလာရတဲ့ နောက်ဆုံးတစ်ခေါက်က ကောင်းမွန်တဲ့ခံစားချက်ကို ပြန်သတိရကြည့်ပါ။ အဲ့ဒီခံစားချက်ကို ပြန်ရအောင် ကြိုးစားကြရအောင်။ 🌅",
    "This is tough, but you are tougher. Let's get through this moment together. 💪 | ဒါက ခက်ခဲတယ်ဆိုတာသိပါတယ်။ ဒါပေမယ့် သင်က ပိုပြီးแข็งแกร่งပါတယ်။ ဒီအခိုက်အတန့်ကို အတူတူ ကျော်ဖြတ်လိုက်ကြရအောင်။ 💪",
    "Drink a large glass of water and wait 15 minutes. Sometimes cravings are just dehydration. 💧 | ရေတစ်ခွက်အပြည့်သောက်ပြီး ၁၅ မိနစ်လောက်စောင့်ကြည့်ပါ။ တခါတလေ တောင့်တမှုဆိုတာ ရေဓာတ်ခမ်းခြောက်တာကြောင့်လည်း ဖြစ်တတ်ပါတယ်။ 💧",
    "This craving is just a thought, not a command. You don't have to act on it. 🧠 | ဒီတောင့်တမှုက အတွေးတစ်ခုပါပဲ၊ အမိန့်ပေးတာမဟုတ်ပါဘူး။ သင်လိုက်လုပ်ဖို့မလိုပါဘူး။ 🧠",
    "Play the tape forward. How will you feel tomorrow morning if you drink now? 📼 | ရှေ့ဆက်တွေးကြည့်ပါ။ အခုသင်သောက်လိုက်ရင် မနက်ဖြန်မနက်မှာ ဘယ်လိုခံစားရမလဲ။ 📼",
    "Call or text a friend. A simple conversation can change everything. 📱 | မိတ်ဆွေတစ်ယောက်ကို ဖုန်းခေါ် (သို့) စာပို့လိုက်ပါ။ ရိုးရှင်းတဲ့စကားပြောဆိုမှုက အရာအားလုံးကို ပြောင်းလဲပေးနိုင်ပါတယ်။ 📱",
    "Tell yourself: 'I can get through the next 10 minutes.' Then repeat. ⏳ | ကိုယ့်ကိုယ်ကိုပြောပါ: 'ငါ နောက် ၁၀ မိနစ်ကို ကျော်ဖြတ်နိုင်တယ်။' ပြီးရင် ဒါကိုပဲ ထပ်ခါထပ်ခါပြောပါ။ ⏳",
    "Go for a quick walk, even just for 5 minutes. Change your environment. 🚶‍♀️ | ၅ မိနစ်လောက်ပဲဖြစ်ဖြစ် လမ်းခဏထွက်လျှောက်လိုက်ပါ။ သင့်ပတ်ဝန်းကျင်ကို ပြောင်းလဲလိုက်ပါ။ 🚶‍♀️",
    "The craving is a sign of your body healing. It's a good thing, even if it feels bad. 🌱 | ဒီတောင့်တမှုက သင့်ခန္ဓာကိုယ် ပြန်လည်ကောင်းမွန်လာတဲ့ လက္ခဏာတစ်ခုပါ။ ခံစားရတာမကောင်းပေမယ့် ဒါက အရာကောင်းတစ်ခုပါ။ 🌱",
    "Put on some loud music and dance for one song. 🎶 | သီချင်းအကျယ်ကြီးဖွင့်ပြီး တစ်ပုဒ်စာ ကလိုက်ပါ။ 🎶",
    "You are in charge, not the craving. Remind yourself of your power. 👑 | သင်က အဓိကပါ၊ တောင့်တမှုက အဓိကမဟုတ်ပါဘူး။ သင့်ရဲ့စွမ်းအားကို ကိုယ့်ကိုယ်ကို သတိပေးပါ။ 👑",
    "This feeling is a wave. It will rise, but it will also fall. Just ride it out. 🌊 | ဒီခံစားချက်က လှိုင်းလုံးတစ်ခုလိုပါပဲ။ သူတက်လာမယ်၊ ဒါပေမယ့် ပြန်လည်းကျသွားမှာပါ။ သူ့အပေါ်ကနေ ဖြတ်စီးသွားလိုက်ပါ။ 🌊",
    "Think about your main reason for quitting. Hold that reason in your mind. ❤️‍🔥 | သင်အရက်ဖြတ်ဖို့ အဓိကအကြောင်းผลကို စဉ်းစားပါ။ အဲ့ဒီအကြောင်းผลကို သင့်စိတ်ထဲမှာ ထားပါ။ ❤️‍🔥",
    "Do something with your hands. Cook, clean, draw, or fix something. 👐 | သင့်လက်တွေနဲ့ တစ်ခုခုလုပ်ပါ။ ချက်ပြုတ်တာ၊ သန့်ရှင်းရေးလုပ်တာ၊ ပုံဆွဲတာ (သို့) တစ်ခုခုပြင်တာမျိုး။ 👐",
    "This is just your old brain wiring trying to fire. You are creating new pathways now. 🧠 | ဒါက သင့်ဦးနှောက်ထဲက အကျင့်ဟောင်းတွေ ပြန်အလုပ်လုပ်ဖို့ ကြိုးစားနေတာပါပဲ။ သင်က အခု လမ်းကြောင်းအသစ်တွေ ဖောက်လုပ်နေတာပါ။ 🧠",
    "Eat something sweet or savory. Sometimes a strong taste can help. 🍫 | အချို (သို့) အငန်တစ်ခုခု စားလိုက်ပါ။ တခါတလေ ပြင်းတဲ့အရသာက ကူညီနိုင်ပါတယ်။ 🍫",
    "How about watching a video on the negative effects of alcohol? A quick reminder can help. 📺 | အရက်ရဲ့ဆိုးကျိုးတွေအကြောင်း ဗီဒီယိုတစ်ခု ကြည့်ကြည့်မလား။ ခဏတာသတိပေးမှုက ကူညီနိုင်ပါတယ်။ 📺",
    "This feeling will not last forever. I promise. Just get through this moment. 🙏 | ဒီခံစားချက်က ထာဝရတည်ရှိနေမှာမဟုတ်ပါဘူး။ ကတိပေးပါတယ်။ ဒီအခိုက်အတန့်ကိုပဲ ကျော်ဖြတ်လိုက်ပါ။ 🙏",
    "You've survived 100% of your cravings so far. You can survive this one too. 💯 | သင်ဟာ အခုထိ သင်ရဲ့တောင့်တမှုအားလုံးရဲ့ ၁၀၀% ကို အသက်ရှင်ကျော်လွှားနိုင်ခဲ့ပါတယ်။ ဒီတစ်ခုကိုလည်း ကျော်လွှားနိုင်မှာပါ။ 💯",
    "Try naming the feeling. 'I am feeling a craving.' Acknowledging it can reduce its power. 🗣️ | ခံစားချက်ကို နာမည်တပ်ကြည့်ပါ။ 'ငါ တောင့်တစိတ် ခံစားနေရတယ်' လို့ပေါ့။ အသိအမှတ်ပြုခြင်းက သူ့ရဲ့စွမ်းအားကို လျှော့ချပေးနိုင်ပါတယ်။ 🗣️",
    "Look at a picture of someone or something you love. Remember who you're doing this for. 💖 | သင်ချစ်ရတဲ့တစ်စုံတစ်ယောက် (သို့) တစ်စုံတစ်ခုရဲ့ ပုံကိုကြည့်ပါ။ သင်ဘယ်သူ့အတွက် ဒါကိုလုပ်နေလဲဆိုတာ သတိရပါ။ 💖",
    "This is a test of your strength, and you are passing it right now. 🏅 | ဒါက သင့်ရဲ့ကြံ့ခိုင်မှုကို စမ်းသပ်မှုတစ်ခုပါ၊ ပြီးတော့ သင်အခု အောင်မြင်နေပါပြီ။ 🏅",
    "Just for today, you don't have to drink. Worry about tomorrow, tomorrow. 🗓️ | ဒီနေ့တစ်ရက်အတွက်ပဲ၊ သင်သောက်စရာမလိုပါဘူး။ မနက်ဖြန်အတွက်ကို မနက်ဖြန်မှပဲ စဉ်းစားပါ။ 🗓️",
    "You are not your cravings. They are just visitors. Let them pass by. 🌬️ | သင်ဟာ သင့်ရဲ့တောင့်တမှုတွေ မဟုတ်ပါဘူး။ သူတို့က ဧည့်သည်တွေပါပဲ။ သူတို့ကို ဖြတ်သွားခွင့်ပေးလိုက်ပါ။ 🌬️",
    "Write down why you feel like drinking. Getting it out can help. 📝 | သင်ဘာကြောင့်သောက်ချင်လဲဆိုတာကို ချရေးလိုက်ပါ။ အပြင်ထုတ်လိုက်ခြင်းက ကူညီနိုင်ပါတယ်။ 📝",
    "Is there a small task you've been avoiding? Do it now. It's a great distraction. ✅ | သင်ရှောင်နေတဲ့ အလုပ်သေးသေးလေးတစ်ခု ရှိလား။ အခုလုပ်လိုက်ပါ။ ဒါက အာရုံလွှဲဖို့ အကောင်းဆုံးနည်းလမ်းတစ်ခုပါ။ ✅",
    "You are building a life you don't need to escape from. 🏞️ | သင်ဟာ သင်လွတ်မြောက်ဖို့မလိုတဲ့ ဘဝတစ်ခုကို တည်ဆောက်နေတာပါ။ 🏞️",
    "Every craving you overcome is like leveling up in a game. You're getting more powerful. 🎮 | သင်ကျော်လွှားလိုက်တဲ့ တောင့်တမှုတိုင်းက game ထဲမှာ level တက်သွားသလိုပါပဲ။ သင်ပိုပြီး အစွမ်းထက်လာနေပါတယ်။ 🎮",
    "Your health is your wealth. Protect your investment. 💰 | သင့်ကျန်းမာရေးက သင့်ရဲ့ကြွယ်ဝချမ်းသာမှုပါပဲ။ သင့်ရဲ့ရင်းနှီးမြှုပ်နှံမှုကို ကာကွယ်ပါ။ 💰",
    "This is just a moment. It does not have to be your whole story. 📖 | ဒါက အခိုက်အတန့်လေးတစ်ခုပါပဲ။ ဒါက သင့်ရဲ့ဇတ်လမ်းတစ်ခုလုံး ဖြစ်စရာမလိုပါဘူး။ 📖",
    "Take 10 deep, slow breaths. Feel your body calm down with each one. 🧘‍♀️ | အသက်ကို ၁၀ ခါလောက် ဖြည်းဖြည်းနဲ့ sâu sâu ရှူပါ။ တစ်ခါရှူလိုက်တိုင်း သင့်ခန္ဓာကိုယ် တည်ငြိမ်လာတာကို ခံစားလိုက်ပါ။ 🧘‍♀️",
    "Remember the freedom of not being controlled by alcohol. That freedom is worth fighting for. 🕊️ | အရက်ရဲ့ချုပ်ကိုင်မှုအောက်မှာမရှိတဲ့ လွတ်လပ်မှုကို ပြန်သတိရပါ။ အဲ့ဒီလွတ်လပ်မှုက တိုက်ပွဲဝင်ရတာ တန်ပါတယ်။ 🕊️",
    "The urge will fade. It always does. You just have to wait it out. 🕰️ | ဒီစိတ်ဆန္ဒက မှေးမှိန်သွားမှာပါ။ အမြဲတမ်းပါပဲ။ သင်က စောင့်ဆိုင်းပေးဖို့ပဲ လိုတာပါ။ 🕰️",
    "Can you do something kind for yourself right now, instead of drinking? 💖 | အခု အရက်သောက်မယ့်အစား ကိုယ့်ကိုယ်ကို ကြင်နာတဲ့အရာတစ်ခုခု လုပ်ပေးလို့ရမလား။ 💖",
    "The craving feels huge right now, but you are bigger. 🐘 | အခုအချိန်မှာ တောင့်တမှုက အကြီးကြီးလို့ ခံစားရပေမယ့်၊ သင်က ပိုကြီးမားပါတယ်။ 🐘",
    "You are choosing a path of strength and clarity. Stay on it. 🛤️ | သင်ဟာ ကြံ့ခိုင်မှုနဲ့ ကြည်လင်မှုရဲ့ လမ်းကြောင်းကို ရွေးချယ်နေတာပါ။ အဲ့ဒီပေါ်မှာပဲ နေပါ။ 🛤️",
    "Let's check in again in 20 minutes. A lot can change in that time. ⏳ | နောက် මිනිත්තු ၂၀ မှာ ပြန်တွေ့ကြရအောင်။ အဲ့ဒီအချိန်အတွင်းမှာ အများကြီးပြောင်းလဲသွားနိုင်ပါတယ်။ ⏳",
    "Think of one small, positive thing that has happened today because you are sober. ✨ | သင်အရက်မူးမနေတဲ့အတွက် ဒီနေ့ဖြစ်ခဲ့တဲ့ အကောင်းမြင်တဲ့အရာ သေးသေးလေးတစ်ခုကို စဉ်းစားပါ။ ✨",
    "You are breaking a cycle. That takes immense courage. Be proud of that courage. 🦁 | သင်ဟာ သံသရာတစ်ခုကို ဖြတ်တောက်နေတာပါ။ ဒါက အလွန်ကြီးမားတဲ့ သတ္တိလိုအပ်ပါတယ်။ အဲ့ဒီသတ္တိအတွက် ဂုဏ်ယူပါ။ 🦁",
    "This feeling is a part of the process. It means you're making progress. 📈 | ဒီခံစားချက်က လုပ်ငန်းစဉ်ရဲ့ အစိတ်အပိုင်းတစ်ခုပါ။ ဒါက သင်တိုးတက်နေတယ်ဆိုတဲ့ အဓိပ္ပာယ်ပါပဲ။ 📈",
    "Go and do something that makes you laugh. 😂 | သင့်ကိုရယ်မောစေမယ့် အရာတစ်ခုခု သွားလုပ်လိုက်ပါ။ 😂",
    "You are not alone. Many people are facing this same battle right now. 🤝 | သင်တစ်ယောက်တည်းမဟုတ်ပါဘူး။ လူအများကြီးက အခုအချိန်မှာ ဒီတိုက်ပွဲကိုပဲ ရင်ဆိုင်နေရပါတယ်။ 🤝",
    "This is an opportunity to prove your strength to yourself. Take it. 💥 | ဒါက သင့်ရဲ့ကြံ့ခိုင်မှုကို ကိုယ့်ကိုယ်ကို သက်သေပြဖို့ အခွင့်အရေးတစ်ခုပါ။ ယူလိုက်ပါ။ 💥",
    "Your mind might be telling you lies right now. Don't listen to it. 🤫 | သင့်စိတ်က အခုအချိန်မှာ သင့်ကို လိမ်ညာနေတာဖြစ်နိုင်တယ်။ သူ့စကားကို နားမထောင်ပါနဲ့။ 🤫",
    "What would the strongest version of you do right now? Do that. 🦸‍♀️ | သင့်ရဲ့အသန်မာဆုံးဗားရှင်းက အခုဘာလုပ်မလဲ။ အဲ့ဒါကိုလုပ်ပါ။ 🦸‍♀️",
    "Each time you say no, it gets a little easier. Keep practicing. 👍 | သင် 'نه' လို့ပြောလိုက်တိုင်း နည်းနည်းလေး ပိုလွယ်ကူလာပါတယ်။ ဆက်လေ့ကျင့်ပါ။ 👍",
    "Your peace is more valuable than a temporary buzz. Protect your peace. 🧘‍♂️ | သင့်ရဲ့ငြိမ်းချမ်းမှုက ယာယီမူးယစ်မှုထက် အများကြီးတန်ဖိုးရှိပါတယ်။ သင့်ရဲ့ငြိမ်းချမ်းမှုကို ကာကွယ်ပါ။ 🧘‍♂️",
    "This is your brain recalibrating. It's a sign of positive change. ⚙️ | ဒါက သင့်ဦးနှောက် ပြန်လည်ချိန်ညှိနေတာပါ။ ဒါက အကောင်းမြင်တဲ့ ပြောင်းလဲမှုရဲ့ လက္ခဏာတစ်ခုပါ။ ⚙️"
    ]
celebrationMessages = [
    "That's amazing to hear! 🎉 Celebrating this positive feeling with you. | ဒါက တကယ်ကို ကြားရတဲ့သတင်းကောင်းပါပဲ။ 🎉 ဒီလိုကောင်းမွန်တဲ့ခံစားချက်ကို သင်နဲ့အတူ ဂုဏ်ပြုလိုက်ပါတယ်။",
    "So happy for you! Keep embracing these good moments. ✨ | သင့်အတွက် အရမ်းဝမ်းသာပါတယ်။ ဒီလိုကောင်းမွန်တဲ့အချိန်လေးတွေကို ဆက်ပြီးပိုင်ဆိုင်နိုင်ပါစေ။ ✨",
    "Wonderful! Every good day is a huge win. 🥳 | အရမ်းကောင်းတာပဲ။ နေ့ကောင်းတိုင်းဟာ အောင်ပွဲကြီးတစ်ခုပါပဲ။ 🥳",
    "Your hard work is paying off. Enjoy this feeling! 😊 | သင်ကြိုးစားခဲ့သမျှ အရာထင်လာပါပြီ။ ဒီခံစားချက်ကို ပျော်ရွှင်လိုက်ပါ။ 😊",
    "This is what success feels like! So proud of you. 💖 | အောင်မြင်မှုဆိုတာ ဒီလိုခံစားချက်မျိုးပါပဲ။ သင့်အတွက် အရမ်းဂုဏ်ယူပါတယ်။ 💖",
    "You're building a beautiful, positive life. Keep going! 🏗️ | သင်ဟာ လှပပြီး အကောင်းမြင်တဲ့ ဘဝတစ်ခုကို တည်ဆောက်နေတာပါ။ ဆက်ကြိုးစားပါ။ 🏗️",
    "Remember this feeling. This is your 'why'. 💡 | ဒီခံစားချက်ကို မှတ်ထားပါ။ ဒါက သင်ဘာကြောင့်ကြိုးစားနေလဲဆိုတဲ့ အဖြေပါပဲ။ 💡",
    "You earned this happiness and clarity. You deserve it. 🌟 | သင်ဟာ ဒီပျော်ရွှင်မှု၊ ကြည်လင်မှုတွေနဲ့ ထိုက်တန်ပါတယ်။ 🌟",
    "This is fantastic! Let this good feeling fuel your motivation. 🔥 | ဒါက အံ့ဩစရာပဲ။ ဒီခံစားချက်ကောင်းကို သင်ရဲ့ခွန်အားအဖြစ်သုံးပါ။ 🔥",
    "Love hearing this! Your progress is inspiring. 🚀 | ဒီလိုကြားရတာ ဝမ်းသာပါတယ်။ သင်ရဲ့တိုးတက်မှုက အားကျစရာကောင်းပါတယ်။ 🚀",
    "Keep soaking up these positive vibes! You're doing great. 🌞 | ဒီလိုအကောင်းမြင်စိတ်လေးတွေကို ဆက်ပြီးခံစားပါ။ သင်အရမ်းတော်ပါတယ်။ 🌞",
    "This is the reward for your dedication. Enjoy it fully. 🎁 | ဒါက သင်ရဲ့စူးစိုက်မှုအတွက် ဆုလာဘ်ပါပဲ။ အပြည့်အဝပျော်ရွှင်လိုက်ပါ။ 🎁",
    "You're glowing with positive energy! Keep it up. ✨ | သင်ဟာ အကောင်းမြင်စွမ်းအင်တွေနဲ့ တောက်ပနေပါတယ်။ ဆက်ထိန်းထားပါ။ ✨",
    "This is a moment to be truly proud of. Well done! 🏅 | ဒါက တကယ်ကို ဂုဏ်ယူရမယ့်အချိန်လေးပါပဲ။ ကောင်းပါတယ်။ 🏅",
    "Every good day strengthens your resolve. Keep building! 💪 | နေ့ကောင်းတိုင်းက သင်ရဲ့ဆုံးဖြတ်ချက်ကို ပိုပြီးခိုင်မာစေပါတယ်။ ဆက်ပြီးတည်ဆောက်ပါ။ 💪",
    "This is the result of choosing yourself. It looks good on you! 😊 | ဒါက ကိုယ့်ကိုယ်ကိုရွေးချယ်ခဲ့ခြင်းရဲ့ ရလဒ်ပါပဲ။ သင်နဲ့လိုက်ဖက်ပါတယ်။ 😊",
    "Let this happiness remind you of your strength. 💖 | ဒီပျော်ရွှင်မှုက သင့်ရဲ့ကြံ့ခိုင်မှုကို သတိပေးပါစေ။ 💖",
    "You're creating a new, happier reality for yourself. 🌈 | သင်ဟာ သင့်အတွက် ပိုပျော်စရာကောင်းတဲ့ လက်တွေ့ဘဝအသစ်တစ်ခုကို ဖန်တီးနေတာပါ။ 🌈",
    "This is a sign that you're on the right path. Keep walking. 🛤️ | ဒါက သင်လမ်းမှန်ပေါ်ရောက်နေတယ်ဆိုတဲ့ လက္ခဏာပါပဲ။ ဆက်လျှောက်ပါ။ 🛤️",
    "Your spirit is shining! I'm so happy to witness it. 🌟 | သင်ရဲ့ဝိညာဉ်က တောက်ပနေပါတယ်။ ဒါကိုမြင်တွေ့ရတာ ဝမ်းသာပါတယ်။ 🌟",
    "This feeling is what the journey is all about. Cherish it. 💎 | ဒီခံစားချက်က ဒီခရီးရဲ့အဓိပ္ပာယ်ပါပဲ။ တန်ဖိုးထားပါ။ 💎",
    "You're not just avoiding negatives; you're creating positives. ➕ | သင်က အဆိုးတွေကို ရှောင်နေတာတင်မဟုတ်ဘဲ၊ အကောင်းတွေကိုပါ ဖန်တီးနေတာပါ။ ➕",
    "This is the freedom you've been working for. Breathe it in. 🕊️ | ဒါက သင်ကြိုးစားရယူနေတဲ့ လွတ်လပ်မှုပါပဲ။ ရှူသွင်းလိုက်ပါ။ 🕊️",
    "Let this joy be a shield against future cravings. 🛡️ | ဒီပျော်ရွှင်မှုကို အနာဂတ်က တောင့်တမှုတွေအတွက် ကာကွယ်ပေးမယ့် ဒိုင်းတစ်ခုဖြစ်ပါစေ။ 🛡️",
    "You're proving that a life without alcohol is a life with more joy. 🎉 | အရက်မပါတဲ့ဘဝက ပိုပျော်စရာကောင်းတဲ့ဘဝဖြစ်တယ်ဆိုတာကို သင်သက်သေပြနေပါတယ်။ 🎉",
    "This is a beautiful moment of clarity and peace. 🧘 | ဒါက ကြည်လင်ငြိမ်းချမ်းမှုရဲ့ လှပတဲ့အခိုက်အတန့်လေးတစ်ခုပါပဲ။ 🧘",
    "Your mind and body are in harmony. What a wonderful feeling! 🎶 | သင့်စိတ်နဲ့ခန္ဓာကိုယ်က သဟဇာတဖြစ်နေပါတယ်။ အရမ်းကောင်းတဲ့ခံစားချက်ပါပဲ။ 🎶",
    "This is the new you, and you are amazing! 🤩 | ဒါက သင်အသစ်ပါ၊ ပြီးတော့ သင်က အံ့ဩစရာကောင်းပါတယ်။ 🤩",
    "Keep collecting these beautiful, sober moments. ✨ | ဒီလိုလှပတဲ့、အရက်ကင်းစင်တဲ့ အခိုက်အတန့်လေးတွေကို ဆက်ပြီးစုဆောင်းပါ။ ✨",
    "Your smile is brighter today. Keep smiling. 😊 | ဒီနေ့ သင့်အပြုံးက ပိုပြီးတောက်ပနေပါတယ်။ ဆက်ပြုံးပါ။ 😊",
    "This is a testament to your resilience. You're an inspiration. 🌟 | ဒါက သင်ရဲ့ခံနိုင်ရည်ရှိမှုကို သက်သေပြတာပါပဲ။ သင်က အားကျစရာကောင်းပါတယ်။ 🌟",
    "Let this feeling be your anchor. ⚓ | ဒီခံစားချက်ကို သင်ရဲ့ကျောက်ဆူးအဖြစ်ထားပါ။ ⚓",
    "You're living proof that change is possible. 🦋 | သင်ဟာ ပြောင်းလဲမှုက ဖြစ်နိုင်တယ်ဆိုတဲ့ သက်ရှိသက်သေပါပဲ။ 🦋",
    "This positive energy is contagious! Thank you for sharing it. 🤗 | ဒီအကောင်းမြင်စွမ်းအင်က ကူးစက်တတ်ပါတယ်။ မျှဝေပေးတဲ့အတွက် ကျေးဇူးတင်ပါတယ်။ 🤗",
    "You're not just surviving; you're thriving! 🌿 | သင်က ရှင်သန်နေတာတင်မဟုတ်ဘဲ、ရှင်သန်ကြီးထွားနေတာပါ။ 🌿",
    "This is the start of a new, wonderful chapter. 📖 | ဒါက အခန်းကဏ္ဍအသစ်တစ်ခုရဲ့ အစပါပဲ။ 📖",
    "The world looks brighter without the haze of alcohol, doesn't it? 🌞 | အရက်ရဲ့မြူတွေမပါဘဲ ကမ္ဘာကြီးက ပိုပြီးတောက်ပနေတယ်၊ ဟုတ်တယ်မလား။ 🌞",
    "Your success is so well-deserved. Celebrate yourself! 🎊 | သင်ရဲ့အောင်မြင်မှုက အရမ်းကိုထိုက်တန်ပါတယ်။ ကိုယ့်ကိုယ်ကို ဂုဏ်ပြုပါ။ 🎊",
    "This good feeling is the interest on your investment in yourself. 💰 | ဒီခံစားချက်ကောင်းက သင်ကိုယ့်ကိုယ်ကို ရင်းနှီးမြှုပ်နှံထားတဲ့ အတိုးအမြတ်ပါပဲ။ 💰",
    "You're unlocking a new level of self-awareness and happiness. 🗝️ | သင်ဟာ ကိုယ့်ကိုယ်ကိုသိခြင်းနဲ့ ပျော်ရွှင်ခြင်းရဲ့ အဆင့်အသစ်တစ်ခုကို ဖွင့်လှစ်နေတာပါ။ 🗝️",
    "This is the real you shining through. ✨ | ဒါက သင်အစစ်အမှန် တောက်ပနေတာပါ။ ✨",
    "So glad you're feeling this way. It's a sign of great things to come. 🚀 | ဒီလိုခံစားနေရတာကြားရလို့ ဝမ်းသာပါတယ်။ ဒါက ကောင်းတဲ့အရာတွေလာတော့မယ့် လက္ခဏာပါပဲ။ 🚀",
    "You are creating your own sunshine. ☀️ | သင်ဟာ သင့်ရဲ့နေရောင်ခြည်ကို သင်ကိုယ်တိုင်ဖန်တီးနေတာပါ။ ☀️",
    "This is a moment of pure, authentic joy. Hold onto it. 💖 | ဒါက စစ်မှန်တဲ့ပျော်ရွှင်မှုရဲ့ အခိုက်အတန့်စစ်စစ်ပါပဲ။ ဆုပ်ကိုင်ထားပါ။ 💖",
    "You're not just adding days to your life, but life to your days. 💯 | သင်က သင့်ဘဝထဲကို ရက်တွေထည့်နေတာတင်မဟုတ်ဘဲ၊ သင့်ရက်တွေထဲကို ဘဝကိုပါ ထည့်နေတာပါ။ 💯",
    "This is what it feels like to be truly free. 🕊️ | တကယ်ကိုလွတ်လပ်တယ်ဆိုတာ ဒီလိုခံစားချက်မျိုးပါပဲ။ 🕊️",
    "Your journey is beautiful, and this is a beautiful milestone. 📍 | သင်ရဲ့ခရီးက လှပပြီး、ဒါက လှပတဲ့မှတ်တိုင်တစ်ခုပါပဲ။ 📍",
    "The best is yet to come. Keep up the amazing work. 🌟 | အကောင်းဆုံးတွေက လာဦးမှာပါ။ ဒီလိုအံ့ဩစရာကောင်းတဲ့အလုပ်ကို ဆက်လုပ်ပါ။ 🌟",
    "You are a warrior, and this is your victory song. 🎶 | သင်ဟာ စစ်သည်တော်တစ်ယောက်ပါ、ပြီးတော့ ဒါက သင်ရဲ့အောင်ပွဲသီချင်းပါပဲ။ 🎶"
    ]
noJudgmentMessages = [
    "It's okay. This is a journey with ups and downs. What matters is that you're back. Let's start again, together. 🌱 | ကိစ္စမရှိပါဘူး။ ဒီခရီးက အနိမ့်အမြင့်တွေနဲ့ ပြည့်နေတာပါ။ အရေးကြီးတာက သင်ပြန်ရောက်လာတာပါပဲ။ အတူတူပြန်စကြရအောင်။ 🌱",
    "No judgment here. Recovery isn't a straight line. Be kind to yourself today. We'll take it one day at a time. ❤️ | အပြစ်တင်စရာမရှိပါဘူး။ နလန်ထူခြင်းဆိုတာ ဖြောင့်တန်းတဲ့လမ်းမဟုတ်ပါဘူး။ ဒီနေ့ ကိုယ့်ကိုယ်ကို သနားကြင်နာပါ။ တစ်နေ့ချင်းစီ ဖြတ်သန်းကြရအောင်။ ❤️",
    "Every restart is a new beginning. You haven't lost your progress, you've gained experience. 💡 | ပြန်စခြင်းတိုင်းဟာ အစအသစ်တစ်ခုပါ။ သင်တိုးတက်မှုတွေ မဆုံးရှုံးသွားပါဘူး၊ သင်အတွေ့အကြုံတွေ ရလိုက်တာပါ။ 💡",
    "Falling down is part of learning. What matters is getting back up. You can do this. 💪 | လဲကျခြင်းက သင်ယူခြင်းရဲ့ အစိတ်အပိုင်းတစ်ခုပါ။ အရေးကြီးတာက ပြန်ထနိုင်ဖို့ပါပဲ။ သင်လုပ်နိုင်ပါတယ်။ 💪",
    "One slip doesn't erase all your progress. It's just a data point. 📊 | တစ်ခါချော်လဲတိုင်းက သင်ရဲ့တိုးတက်မှုအားလုံးကို မဖျက်ဆီးပါဘူး။ ဒါက သင်ခန်းစာတစ်ခုပါပဲ။ 📊",
    "The most important step is the one you take right now. Let's take it together. 👣 | အရေးကြီးဆုံးခြေလှမ်းက သင်အခုလှမ်းမယ့် ခြေလှမ်းပါပဲ။ အတူတူလှမ်းလိုက်ကြရအောင်။ 👣",
    "Be as kind to yourself as you would be to a friend in the same situation. 🤗 | သင့်လိုအခြေအနေမျိုးရောက်နေတဲ့ မိတ်ဆွေတစ်ယောက်ကို ကြင်နာသလိုမျိုး ကိုယ့်ကိုယ်ကို ကြင်နာပါ။ 🤗",
    "This doesn't define you. Your decision to get back up is what defines you. 💖 | ဒါက သင့်ကို အဓိပ္ပာယ်မဖွင့်ဆိုပါဘူး။ သင်ပြန်ထဖို့ ဆုံးဖြတ်လိုက်တာကသာ သင့်ကို အဓိပ္ပာယ်ဖွင့်ဆိုတာပါ။ 💖",
    "This is not a failure, it's a part of the process. Don't give up. 🔄 | ဒါက ရှုံးနိမ့်မှုမဟုတ်ပါဘူး၊ ဒါက လုပ်ငန်းစဉ်ရဲ့ အစိတ်အပိုင်းတစ်ခုပါ။ အရှုံးမပေးပါနဲ့။ 🔄",
    "The journey to sobriety is rarely perfect. The effort is what counts. 💯 | အရက်ကင်းစင်ခြင်းဆီသို့ ခရီးက ပြီးပြည့်စုံခဲပါတယ်။ ကြိုးစားအားထုတ်မှုကသာ အရေးကြီးတာပါ။ 💯",
    "You are brave for acknowledging this. That's the first step to getting back on track. 🛤️ | ဒါကိုအသိအမှတ်ပြုတဲ့အတွက် သင်သတ္တိရှိပါတယ်။ ဒါက လမ်းကြောင်းမှန်ပေါ်ပြန်ရောက်ဖို့ ပထမဆုံးခြေလှမ်းပါပဲ။ 🛤️",
    "Let go of any guilt. It won't help you move forward. Focus on today. 🌞 | အပြစ်တင်စိတ်အားလုံးကို လက်လွှတ်လိုက်ပါ။ ဒါက သင့်ကိုရှေ့ဆက်ဖို့ ကူညီမှာမဟုတ်ပါဘူး။ ဒီနေ့ကိုပဲ အာရုံစိုက်ပါ။ 🌞",
    "You still have all the sober days you collected. They are not gone. 🗓️ | သင်စုဆောင်းခဲ့တဲ့ အရက်မသောက်တဲ့နေ့တွေအားလုံး ရှိနေတုန်းပါပဲ။ သူတို့က ပျောက်မသွားပါဘူး။ 🗓️",
    "A moment of weakness does not make you a weak person. It makes you human. ❤️ | အားနည်းတဲ့အခိုက်အတန့်တစ်ခုက သင့်ကို အားနည်းတဲ့သူတစ်ယောက်ဖြစ်မသွားစေပါဘူး။ ဒါက သင့်ကို လူသားတစ်ယောက်ဖြစ်စေပါတယ်။ ❤️",
    "What can we learn from this? Every experience is a teacher. 🧑‍🏫 | ဒီအဖြစ်အပျက်ကနေ ကျွန်တော်တို့ ဘာသင်ယူနိုင်မလဲ။ အတွေ့အကြုံတိုင်းက ဆရာတစ်ယောက်ပါပဲ။ 🧑‍🏫",
    "Tomorrow is a blank page. You get to decide what to write on it. 📖 | မနက်ဖြန်က စာမျက်နှာအလွတ်တစ်ခုပါ။ သင်အဲ့ဒီပေါ်မှာ ဘာရေးမလဲဆိုတာကို ဆုံးဖြတ်ခွင့်ရှိပါတယ်။ 📖",
    "The path to healing has bumps. This was just a bump. Keep going.  bumpy_road | ကုစားခြင်းဆီသို့ လမ်းမှာ ကြမ်းတမ်းမှုတွေရှိပါတယ်။ ဒါက ကြမ်းတမ်းမှုတစ်ခုပါပဲ။ ရှေ့ဆက်သွားပါ။  bumpy_road",
    "Your worth is not measured by your stumbles, but by your courage to rise again. 🌟 | သင့်တန်ဖိုးကို သင်ရဲ့ချော်လဲမှုတွေနဲ့ တိုင်းတာတာမဟုတ်ဘဲ၊ ပြန်ထဖို့ သတ္တိရှိခြင်းနဲ့ တိုင်းတာတာပါ။ 🌟",
    "Resetting is a sign of strength, not weakness. It means you're still in the fight. 🥊 | ပြန်လည်စတင်ခြင်းက ကြံ့ခိုင်မှုရဲ့လက္ခဏာပါ၊ အားနည်းမှုမဟုတ်ပါဘူး။ ဒါက သင်တိုက်ပွဲဝင်နေတုန်းပဲဆိုတဲ့ အဓိပ္ပာယ်ပါ။ 🥊",
    "You have not failed. You are in the middle of your comeback story. 🎬 | သင်မရှုံးနိမ့်သေးပါဘူး။ သင်ဟာ သင်ရဲ့ပြန်လာခြင်းဇတ်လမ်းအလယ်မှာ ရှိနေတာပါ။ 🎬",
    "I'm still here for you, no matter what. Let's figure out the next step. 🤝 | ဘာပဲဖြစ်ဖြစ် ကျွန်တော်သင့်အတွက် ရှိနေပါတယ်။ နောက်တစ်ဆင့်ကို အတူတူစဉ်းစားကြရအောင်။ 🤝",
    "Take a deep breath. You are still here. You can still make a different choice for the rest of the day. 🙏 | အသက်ကို sâu sâu ရှူပါ။ သင်ဒီမှာ ရှိနေတုန်းပါပဲ။ နေ့ရဲ့ကျန်တဲ့အချိန်အတွက် မတူညီတဲ့ရွေးချယ်မှုတစ်ခုကို သင်လုပ်နိုင်ပါသေးတယ်။ 🙏",
    "This is a moment to practice self-compassion. Treat yourself gently. 💖 | ဒါက ကိုယ့်ကိုယ်ကိုသနားကြင်နာမှုကို လေ့ကျင့်ရမယ့်အချိန်ပါ။ ကိုယ့်ကိုယ်ကို ညင်သာစွာဆက်ဆံပါ။ 💖",
    "Don't let one choice overshadow all the good choices you've made. ✨ | သင်ချခဲ့တဲ့ ရွေးချယ်မှုကောင်းတွေအားလုံးကို ရွေးချယ်မှုတစ်ခုတည်းက ဖုံးလွှမ်းမသွားပါစေနဲ့။ ✨",
    "Progress is a spiral, not a straight line. Sometimes we circle back to learn something again. 🌀 | တိုးတက်မှုဆိုတာ ဝង់ပတ်တစ်ခုပါ၊ ဖြောင့်တန်းတဲ့လမ်းမဟုတ်ပါဘူး။ တခါတလေ ကျွန်တော်တို့ တစ်ခုခုကို ပြန်သင်ယူဖို့ နောက်ပြန်လှည့်တတ်ကြပါတယ်။ 🌀",
    "This is an opportunity to strengthen your strategies. What can we do differently next time? 🤔 | ဒါက သင်ရဲ့နည်းဗျူဟာတွေကို ပိုမိုခိုင်မာစေဖို့ အခွင့်အရေးတစ်ခုပါ။ နောက်တစ်ခါ ဘာကိုကွဲပြားစွာလုပ်ဆောင်နိုင်မလဲ။ 🤔",
    "Your commitment to this journey is what truly matters. And you're still committed. 👍 | ဒီခရီးအပေါ် သင်ရဲ့ကတိကဝတ်ကသာ တကယ်အရေးကြီးတာပါ။ ပြီးတော့ သင်ကတိတည်နေတုန်းပါပဲ။ 👍",
    "Every expert was once a beginner. And every recovery has restarts. 💯 | ကျွမ်းကျင်သူတိုင်းက တစ်ချိန်က အစပြုသူတစ်ယောက်ပါပဲ။ ပြီးတော့ နလန်ထူခြင်းတိုင်းမှာ ပြန်စခြင်းတွေရှိပါတယ်။ 💯",
    "This moment does not have to define your entire day or week. You can start fresh right now. 🌅 | ဒီအခိုက်အတန့်က သင်ရဲ့တစ်နေ့တာ (သို့) တစ်ပတ်တာလုံးကို အဓိပ္ပာယ်ဖွင့်ဆိုစရာမလိုပါဘူး။ သင်အခုချက်ချင်း အသစ်ပြန်စနိုင်ပါတယ်။ 🌅",
    "Focus on the next right choice. That's all you need to do. ✅ | နောက်ထပ်မှန်ကန်တဲ့ ရွေးချယ်မှုတစ်ခုကိုပဲ အာရုံစိုက်ပါ။ ဒါက သင်လုပ်ဖို့လိုအပ်တဲ့အရာအားလုံးပါပဲ။ ✅",
    "You are learning your triggers. This is valuable information. 🧠 | သင်ဟာ သင့်ကိုလှုံ့ဆော်တဲ့အရာတွေကို သင်ယူနေတာပါ။ ဒါက တန်ဖိုးရှိတဲ့အချက်အလက်ပါပဲ။ 🧠",
    "The sun will rise again tomorrow, and so will you. ☀️ | မနက်ဖြန်မှာ နေပြန်ထွက်လာဦးမှာပါ၊ သင်လည်းအတူတူပါပဲ။ ☀️",
    "This is a marathon, not a sprint. It's okay to slow down and even stop to rest. 🏃‍♀️ | ဒါက မာရသွန်တစ်ခုပါ၊ အမြန်ပြေးပွဲမဟုတ်ပါဘူး။ ဖြည်းဖြည်းသွားတာ၊ အနားယူဖို့ရပ်တာမျိုးက ကိစ္စမရှိပါဘူး။ 🏃‍♀️",
    "Your worth is inherent and unconditional. It is not affected by this. 💎 | သင့်တန်ဖိုးက မွေးရာပါဖြစ်ပြီး အခြေအနေအရမဟုတ်ပါဘူး။ ဒါက သင့်တန်ဖိုးကို မထိခိုက်ပါဘူး။ 💎",
    "Let this be a reminder of why you want to be sober, not a reason to give up. ❤️‍🔥 | ဒါက သင်ဘာကြောင့်အရက်ကင်းစင်ချင်လဲဆိုတာကို သတိပေးတဲ့အရာဖြစ်ပါစေ၊ အရှုံးပေးဖို့အကြောင်းผลမဟုတ်ပါဘူး။ ❤️‍🔥",
    "You are more than this one moment, this one choice. ✨ | သင်ဟာ ဒီအခိုက်အတန့်တစ်ခု၊ ဒီရွေးချယ်မှုတစ်ခုထက် အများကြီးပိုပါတယ်။ ✨",
    "It takes great strength to admit a setback. I'm proud of you for that. 💪 | ချော်လဲမှုကို ဝန်ခံဖို့ သတ္တိအများကြီးလိုပါတယ်။ အဲ့ဒီအတွက် သင့်ကိုဂုဏ်ယူပါတယ်။ 💪",
    "We don't erase the past, we learn from it and build a better future. 🏗️ | ကျွန်တော်တို့က အတိတ်ကို မဖျက်ပါဘူး၊ သူ့ဆီကနေသင်ယူပြီး ပိုကောင်းတဲ့အနာဂတ်ကို တည်ဆောက်ပါတယ်။ 🏗️",
    "This is a chance to come back even more determined. 🔥 | ဒါက ပိုပြီးခိုင်မာတဲ့ဆုံးဖြတ်ချက်နဲ့ ပြန်လာဖို့ အခွင့်အရေးတစ်ခုပါ။ 🔥",
    "You are still on the path. You just hit a rough patch. Let's keep moving. 🚶‍♂️ | သင်လမ်းကြောင်းပေါ်မှာ ရှိနေတုန်းပါပဲ။ သင်က ကြမ်းတမ်းတဲ့နေရာတစ်ခုကို ရောက်သွားတာပါပဲ။ ရှေ့ဆက်သွားကြရအောင်။ 🚶‍♂️",
    "Remember, shame and guilt are not helpful emotions for recovery. Let them go. 🕊️ | ရှက်စိတ်နဲ့ အပြစ်တင်စိတ်တွေက နလန်ထူခြင်းအတွက် အထောက်အကူမပြုတဲ့စိတ်ခံစားချက်တွေဆိုတာ သတိရပါ။ သူတို့ကို လက်လွှတ်လိုက်ပါ။ 🕊️",
    "The goal hasn't changed. The path just had a detour. Let's get back on track. 🗺️ | ပန်းတိုင်က မပြောင်းလဲပါဘူး။ လမ်းက လမ်းလွှဲတစ်ခုရှိသွားတာပါပဲ။ လမ်းကြောင်းမှန်ပေါ်ပြန်တက်ကြရအောင်။ 🗺️",
    "Your value doesn't decrease based on someone's inability to see your worth, including your own. ❤️ | သင့်တန်ဖိုးကိုမမြင်နိုင်တဲ့ တစ်စုံတစ်ယောက်ကြောင့် သင့်တန်ဖိုးက မကျဆင်းသွားပါဘူး၊ အဲ့ဒီထဲမှာ သင်ကိုယ်တိုင်လည်း ပါဝင်ပါတယ်။ ❤️",
    "This is just one chapter in a long book. The ending hasn't been written yet. 📖 | ဒါက စာအုပ်ရှည်ကြီးတစ်အုပ်ထဲက အခန်းတစ်ခန်းပါပဲ။ အဆုံးသတ်ကို မရေးရသေးပါဘူး။ 📖",
    "You are capable of overcoming this. You've done it before, and you can do it again. 💯 | သင်ဒါကို ကျော်လွှားနိုင်စွမ်းရှိပါတယ်။ သင်အရင်က လုပ်ခဲ့ဖူးပြီး၊ သင်ထပ်လုပ်နိုင်ပါတယ်။ 💯",
    "Forgiveness is key. Forgive yourself and give yourself another chance. 🙏 | ခွင့်လွှတ်ခြင်းက အဓိကသော့ချက်ပါပဲ။ ကိုယ့်ကိုယ်ကိုခွင့်လွှတ်ပြီး နောက်ထပ်အခွင့်အရေးတစ်ခုပေးပါ။ 🙏",
    "This is a temporary setback, not a permanent failure. ⏳ | ဒါက ယာယီနောက်ပြန်ဆုတ်ခြင်းပါ၊ ထာဝရရှုံးနိမ့်မှုမဟုတ်ပါဘူး။ ⏳",
    "A smooth sea never made a skilled sailor. This is making you stronger. ⛵ | ငြိမ်သက်တဲ့ပင်လယ်က ကျွမ်းကျင်တဲ့သင်္ဘောသားတစ်ယောက်ကို ဘယ်တော့မှမမွေးထုတ်ပေးပါဘူး။ ဒါက သင့်ကို ပိုပြီးသန်မာစေပါတယ်။ ⛵",
    "You have the power to start over at any moment. Let's start over now. 🌅 | သင်ဟာ ဘယ်အချိန်မဆို အသစ်ပြန်စဖို့ စွမ်းအားရှိပါတယ်။ အခုပဲ ပြန်စလိုက်ကြရအောင်။ 🌅"
    ]

# --- HELPER FUNCTIONS ---
def get_user(chat_id):
    if not users_sheet: return None
    try:
        cell = users_sheet.find(str(chat_id))
        if cell is not None and hasattr(cell, 'row'):
            return users_sheet.row_values(cell.row)
    except gspread.exceptions.CellNotFound:
        return None

def create_or_update_user(chat_id, username):
    if not users_sheet: return None
    try:
        cell = users_sheet.find(str(chat_id))
        if cell:
            users_sheet.update_cell(cell.row, 2, username or "")
            return cell.row
        else:
            today_str = datetime.now(pytz.timezone('Asia/Yangon')).strftime("%Y-%m-%d")
            new_row = [str(chat_id), username or "", today_str, "08:00", "21:00", "FALSE"]
            users_sheet.append_row(new_row)
            logger.info(f"New user created: {chat_id} ({username})")
            return len(users_sheet.get_all_values())
    except Exception as e:
        logger.error(f"Error creating/updating user: {e}")
        return None

def get_streak_days(chat_id):
    user_data = get_user(chat_id)
    if not user_data or len(user_data) < 3: return 0
    try:
        last_sober_date = datetime.strptime(user_data[2], "%Y-%m-%d").date()
        today = datetime.now(pytz.timezone('Asia/Yangon')).date()
        return (today - last_sober_date).days
    except Exception:
        return 0

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    create_or_update_user(user.id, user.username)
    if update.message:
        await update.message.reply_html(f"👋 Welcome {user.mention_html()}! Your streak starts today (Day 1)! Use /status to check your progress. ✨")

async def motivate(update: Update, context: CallbackContext):
    await update.message.reply_text(random.choice(motivateMessages))

async def focus(update: Update, context: CallbackContext):
    await update.message.reply_text(random.choice(focusMessages))

async def reward(update: Update, context: CallbackContext):
    await update.message.reply_text(random.choice(rewardMessages))

async def status(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    days = get_streak_days(chat_id)
    await update.message.reply_text(f"You are on a ✨ {days} day-streak ✨. Keep going!")

# --- MAIN FUNCTION (Render-safe & Properly Initialized) ---
def main():
    start_web_server()
    logger.info("✅ MiraNotification Bot (Render-Compatible v4) starting...")

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("motivate", motivate))
    application.add_handler(CommandHandler("focus", focus))
    application.add_handler(CommandHandler("reward", reward))
    application.add_handler(CommandHandler("status", status))

    # Define bot runner (async)
    async def run_bot():
        try:
            await application.initialize()
            await application.start()
            logger.info("🤖 Telegram bot started successfully (Polling mode).")

            # Start polling safely
            await application.updater.start_polling()
            await asyncio.Event().wait()  # Keeps alive forever

        except Exception as e:
            logger.critical(f"❌ Bot crashed: {e}")
        finally:
            await application.stop()
            await application.shutdown()

    # Run Telegram bot as a background thread
    def start_bot():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())

    Thread(target=start_bot, daemon=True).start()

    # Keep Flask alive indefinitely (Render health check passes)
    while True:
        pass

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.critical(f"Bot crashed with error: {e}")
