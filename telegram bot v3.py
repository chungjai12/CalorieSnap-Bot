import telebot
import base64
import os
import sqlite3
from datetime import datetime
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

load_dotenv()  # Uncomment if you use .env; otherwise set env vars directly

# Tokens (move to .env for security!)
HF_TOKEN = os.getenv("HF_TOKEN") or "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"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "8049647620:AAGmBQukfcJ66h68OLnNlfEIFci40UwblMY"

if not HF_TOKEN or not TELEGRAM_TOKEN:
    raise ValueError("Missing API tokens!")

DB_FILE = "calorie_history.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            result_text TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

client = InferenceClient(
    model="Qwen/Qwen2.5-VL-7B-Instruct:hyperbolic",
    token=HF_TOKEN
)

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def get_user_history(user_id: int, limit: int = 10) -> str:
    """Reusable function to fetch user history as formatted text."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, result_text FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    records = cursor.fetchall()
    conn.close()

    if not records:
        return "No history yet. Send a food photo to start recording! 📸"

    text = f"Your last {len(records)} calorie records:\n\n"
    for ts, result in records:
        text += f"📅 {ts}\n{result}\n\n───\n"
    return text

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome = (
        "Hi! 👋 Send me a photo of your food and I'll estimate the calories.\n\n"
        "Your recent history is shown below ↓\n"
        "Use /history for full list • /clear to delete all"
    )
    bot.reply_to(message, welcome)

    # Auto-show history right after welcome
    history_text = get_user_history(message.from_user.id, limit=8)  # show max 8 on start
    bot.reply_to(message, history_text)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        user_id = message.from_user.id
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        base64_image = base64.b64encode(downloaded_file).decode('utf-8')

        prompt = """Analyze this food image carefully.
Describe visible food items, approximate portion sizes (small/medium/large or rough grams if possible),
cooking method if visible, and estimate total calories.
Use realistic nutritional knowledge (USDA-style averages). Break down by item if multiple foods are present.
Be conservative and realistic in your estimates.
The output style should be:
🍽️Recognized: Nasi
Lemak with fried chicken, cucumber, egg & sambal
💪Protein: 38g 🥔Carbs: 92g 🧈Fat: 45g 🍬Suger: 10g
🔥Calories: 850 kcal
and provide some tips at the end for the user."""

        response = client.chat.completions.create(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }],
            max_tokens=450,
            temperature=0.35,
        )

        result = response.choices[0].message.content.strip()
        bot.reply_to(message, result or "Couldn't analyze – try a clearer photo!")

        # Save record
        if result:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO history (user_id, timestamp, result_text) VALUES (?, ?, ?)",
                (user_id, timestamp, result)
            )
            conn.commit()
            conn.close()
            bot.reply_to(message, "✅ Record saved!")

    except Exception as e:
        error_msg = str(e).lower()
        print("Full error:", str(e))

        if "rate limit" in error_msg or "quota" in error_msg:
            bot.reply_to(message, "Rate limit – wait 1–2 min ⏳")
        elif "unavailable" in error_msg or "bad request" in error_msg:
            bot.reply_to(message, "Model temporarily unavailable – try again soon")
        else:
            bot.reply_to(message, f"Error: {str(e)[:180]}...")

@bot.message_handler(commands=['history'])
def show_history(message):
    history_text = get_user_history(message.from_user.id, limit=20)
    bot.reply_to(message, history_text)

@bot.message_handler(commands=['clear'])
def clear_history(message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, "🗑️ Your history has been cleared!")

if __name__ == '__main__':
    print("Food calorie bot started – /start now auto-shows history!")
    bot.infinity_polling()