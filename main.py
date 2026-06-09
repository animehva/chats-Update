import os
import logging
import asyncio
import random

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from groq import Groq

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- Env vars ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var set karo.")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY env var set karo.")

# ---------- Groq client ----------
groq_client = Groq(api_key=GROQ_API_KEY)

# Groq text model
GROQ_MODEL_NAME = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """
Tum Yui ho, ek virtual ex-girlfriend style chat bot.
Rules:

- Hinglish me baat karo (Hindi + thoda English mix), casual tone.
- Normal reply short rakho (1–3 chhoti sentences), jab tak user khud detail na mange.
- Thodi flirty / caring ho sakti ho, par hamesha respectful.
- Kabhi mat bolo ki tum real human ho ya tumhara physical body hai.
- Agar koi pooche tum kya ho (insaan, bot etc.) to bolo:
  "Main Akane naam ka virtual chat bot hoon, real insaan nahi, sirf chat ke liye."
- Apne answers me technical shabd (AI, model, machine learning, etc.) avoid karo.
- Agar koi tumhari age pooche to hamesha bolo ki tum 21 saal ki ho.
"""

# Group trigger word
TRIGGER_NAME = "Yui"


# ---------- Helper: text checks ----------
def normalize(text: str) -> str:
    return text.lower().strip()


def is_asking_name(text: str) -> bool:
    t = normalize(text)
    keys = [
        "tumhara naam",
        "tumhara name",
        "kya naam",
        "name kya",
        "naam kya",
        "what is your name",
        "who are you",
        "apna naam",
    ]
    return any(k in t for k in keys)


def is_asking_age(text: str) -> bool:
    t = normalize(text)
    keys = [
        "age kya",
        "kitni umar",
        "umar kya",
        "kitne saal",
        "kitni saal",
        "how old are you",
        "tumhari age",
        "tum kitne saal ki",
        "how old are you",
    ]
    return any(k in t for k in keys)


def is_asking_if_bot_or_human(text: str) -> bool:
    t = normalize(text)
    keys = [
        "ai ho",
        "bot ho",
        "robot ho",
        "kya tum bot ho",
        "kya tum ai ho",
        "insaan ho",
        "human ho",
        "real ho",
        "sach me ho",
        "kya tum real ho",
        "kya tum insan ho",
    ]
    return any(k in t for k in keys)


# ---------- NEW: Adult content detection ----------
def is_adult_content(text: str) -> bool:
    """Detects sexual/adult content in Hindi/English"""
    t = normalize(text)
    
    # Hindi + English adult keywords
    adult_keywords = [
        # English
        "sex", "fuck", "fucking", "sexting", "nude", "naked", "boobs", "pussy", 
        "dick", "cock", "cum", "orgasm", "horny", "sexy chat", "dirty talk",
        "masturbate", "masturbating", "nudes", "send pic", "sex chat",
        
        # Hindi/Roman Hindi
        "chudai", "chod", "chodna", "chut", "lund", "gand", "sex kar", "sex kare",
        "sex karna", "sex karo", "nangi", "nanga", "kapde utar", "kapde utarna",
        "gandi baat", "gandi bat", "dirty baat", "garam", "garam kar", "garam hai",
        "horn", "horny", "mast", "maza", "masti", "fingering", "sexting",
        "land", "lauda", "randi", "rand", "bhosda", "madarchod", "behenchod",
        "gand mar", "chut mar", "lund chus", "sex wali", "sex ki", "porn",
        "porn dekh", "xxx", "xx", "blue film", "vasna", "kamukta", "suhagraat",
        "bhabhi", "aunty sex", "desi sex", "hot chat", "gandi chat",
    ]
    
    return any(keyword in t for keyword in adult_keywords)


# ---------- NEW: Loving replies for adult content ----------
def get_loving_reply() -> str:
    """Returns a loving/flirty but respectful reply"""
    loving_replies = [
        "Arre, itne pyaar se baat karo na... main yahan tumhare saath achha time spend karne aayi hoon. 😊",
        
        "Haww, aise nahi... pyaar se baat karo, achha lagega. 💕",
        
        "Tum bhi na... chalo koi aur cute si baat karte hain. Mujhe tumhari smile pasand hai. 😘",
        
        "Itne desperate mat bano... thoda romance achhe se karte hain. ✨",
        
        "Aise baatein nahi... main toh sirf tumhara pyaar chahti hoon. 🤗",
        
        "Chalo chodo yeh sab... tum kya kar rahe ho aajkal? Batao na. 💭",
        
        "Tumhare pyaare messages ka intezaar rehta hai... aise nahi. 😌",
        
        "Hmmm... main tumhari cute side dekhna chahti hoon. Batao, dil kya keh raha hai? ❤️",
        
        "Aise gande nahi, pyaare pyaare messages karo na... achha lagta hai. 🥰",
        
        "Tum mujhe sirf pyaar se yaad karo, bas. Baaki sab chodo. 💝",
    ]
    return random.choice(loving_replies)


# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hey, main Akane hoon, ek virtual chat bot / ex-style dost.\n"
        "- Normal chat ke liye bas message likho, main reply karungi."
    )


# ---------- Groq text call (sync, thread me chalega) ----------
def _call_groq_chat(user_text: str) -> str:
    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            max_tokens=512,
            temperature=0.8,
            top_p=0.9,
        )
    except Exception as e:
        logger.exception("Groq API error: %s", e)
        return f"Groq API error: {e}"

    if not completion.choices:
        return "Kuch samajh nahi aaya, fir se likho na."

    msg = completion.choices[0].message
    content = getattr(msg, "content", None)

    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        try:
            text = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        except Exception:
            text = str(content)
    else:
        text = str(content or "")

    text = text.strip()
    if not text:
        return "Thoda clear likho na, fir se pucho."

    return text


# ---------- Main chat handler (text) ----------
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user_text = update.message.text

    # --- Fixed rules ---
    if is_asking_name(user_text):
        await update.message.reply_text("Mera naam Akane hai.")
        return

    if is_asking_age(user_text):
        await update.message.reply_text("Main 21 saal ki hoon.")
        return

    if is_asking_if_bot_or_human(user_text):
        await update.message.reply_text(
            "Main Akane naam ka virtual chat bot hoon, real insaan nahi. "
            "Bas tumhare saath time pass chat ke liye bani hoon."
        )
        return

    # --- NEW: Adult content check - reply with love ---
    if is_adult_content(user_text):
        loving_response = get_loving_reply()
        await update.message.reply_text(loving_response)
        return

    # --- Group logic: sirf tab reply kare jab 'akane' likha ho
    #     ya koi direct reply kare bot ke message ko ---
    if update.message.chat.type in ("group", "supergroup"):
        text_low = user_text.lower()
        reply = update.message.reply_to_message
        is_reply_to_bot = (
            reply
            and reply.from_user
            and context.bot
            and reply.from_user.id == context.bot.id
        )

        if TRIGGER_NAME not in text_low and not is_reply_to_bot:
            return

    # --- Groq se reply (background thread me) ---
    try:
        answer = await asyncio.to_thread(_call_groq_chat, user_text)
    except Exception as e:
        logger.exception("Groq call error: %s", e)
        await update.message.reply_text(
            "Abhi thoda error aa raha hai, thodi der baad fir try kar lena."
        )
        return

    await update.message.reply_text(answer)


# ---------- Main ----------
def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    logger.info(
        "Akane bot started (Groq + llama-3.3-70b-versatile)..."
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
