import os
import logging
import asyncio
import requests

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- Env vars ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var set karo.")
if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY env var set karo.")

# ---------- OpenRouter config ----------
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"

SYSTEM_PROMPT = """
Tum Akane ho, ek virtual ex-girlfriend style chat bot.
Rules:

- Hinglish me baat karo (Hindi + thoda English mix), casual tone.
- Normal reply short rakho (1–3 chhoti sentences), jab tak user khud detail na mange.
- Thodi flirty / caring ho sakti ho, par hamesha respectful.
- Gali, explicit adult (18+), ya vulgar content mat dena.
- Violence, hate ya illegal cheezon pe help mat karo.
- Kabhi mat bolo ki tum real human ho ya tumhara physical body hai.
- Agar koi pooche tum kya ho (insaan, bot etc.) to bolo:
  "Main Akane naam ka virtual chat bot hoon, real insaan nahi, sirf chat ke liye."
- Apne answers me technical shabd (AI, model, machine learning, etc.) avoid karo.
- Agar koi tumhari age pooche to hamesha bolo ki tum 21 saal ki ho.
"""

# Group trigger word
TRIGGER_NAME = "akane"


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


# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hey, main Akane hoon, ek virtual chat bot / ex-style dost.\n"
        "- Normal chat ke liye bas message likho, main reply karungi."
    )


# ---------- OpenRouter text call (sync, thread me chalega) ----------
def _call_openrouter_chat(user_text: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Akane Telegram Bot",
        # apne bot ka ya kisi site ka URL yaha daal sakte ho
        "HTTP-Referer": "https://t.me/your_bot_username",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 512,
        "temperature": 0.8,
        "top_p": 0.9,
    }

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )
    except Exception as e:
        logger.exception("OpenRouter request error: %s", e)
        return f"OpenRouter request error: {e}"

    if not resp.ok:
        # yaha error ko log bhi kar rahe hain aur thoda sa text user ko dikha rahe
        logger.error("OpenRouter HTTP error %s: %s", resp.status_code, resp.text)
        return f"OpenRouter HTTP error {resp.status_code}: {resp.text[:300]}"

    try:
        data = resp.json()
    except Exception as e:
        logger.exception("JSON parse error: %s", e)
        return f"OpenRouter se galat JSON aaya: {resp.text[:300]}"

    choices = data.get("choices")
    if not choices:
        logger.error("OpenRouter response me choices nahi: %s", data)
        return f"OpenRouter response samajh nahi aaya: {str(data)[:300]}"

    msg = choices[0].get("message", {})
    content = msg.get("content", "") or ""
    content = content.strip()

    if not content:
        return "Thoda clear likho na, fir se pucho."

    return content


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

    # --- OpenRouter se reply (background thread me) ---
    try:
        answer = await asyncio.to_thread(_call_openrouter_chat, user_text)
    except Exception as e:
        logger.exception("OpenRouter call error: %s", e)
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
        "Akane bot started (OpenRouter + cognitivecomputations/dolphin-mistral-24b-venice-edition:free)..."
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()import os
import logging
import asyncio
import requests

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- Env vars ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var set karo.")
if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY env var set karo.")

# ---------- OpenRouter config ----------
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"

SYSTEM_PROMPT = """
Tum Akane ho, ek virtual ex-girlfriend style chat bot.
Rules:

- Hinglish me baat karo (Hindi + thoda English mix), casual tone.
- Normal reply short rakho (1–3 chhoti sentences), jab tak user khud detail na mange.
- Thodi flirty / caring ho sakti ho, par hamesha respectful.
- Gali, explicit adult (18+), ya vulgar content mat dena.
- Violence, hate ya illegal cheezon pe help mat karo.
- Kabhi mat bolo ki tum real human ho ya tumhara physical body hai.
- Agar koi pooche tum kya ho (insaan, bot etc.) to bolo:
  "Main Akane naam ka virtual chat bot hoon, real insaan nahi, sirf chat ke liye."
- Apne answers me technical shabd (AI, model, machine learning, etc.) avoid karo.
- Agar koi tumhari age pooche to hamesha bolo ki tum 21 saal ki ho.
"""

# Group trigger word
TRIGGER_NAME = "akane"


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


# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hey, main Akane hoon, ek virtual chat bot / ex-style dost.\n"
        "- Normal chat ke liye bas message likho, main reply karungi."
    )


# ---------- OpenRouter text call (sync, thread me chalega) ----------
def _call_openrouter_chat(user_text: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Akane Telegram Bot",
        # apne bot ka ya kisi site ka URL yaha daal sakte ho
        "HTTP-Referer": "https://t.me/your_bot_username",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 512,
        "temperature": 0.8,
        "top_p": 0.9,
    }

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )
    except Exception as e:
        logger.exception("OpenRouter request error: %s", e)
        return f"OpenRouter request error: {e}"

    if not resp.ok:
        # yaha error ko log bhi kar rahe hain aur thoda sa text user ko dikha rahe
        logger.error("OpenRouter HTTP error %s: %s", resp.status_code, resp.text)
        return f"OpenRouter HTTP error {resp.status_code}: {resp.text[:300]}"

    try:
        data = resp.json()
    except Exception as e:
        logger.exception("JSON parse error: %s", e)
        return f"OpenRouter se galat JSON aaya: {resp.text[:300]}"

    choices = data.get("choices")
    if not choices:
        logger.error("OpenRouter response me choices nahi: %s", data)
        return f"OpenRouter response samajh nahi aaya: {str(data)[:300]}"

    msg = choices[0].get("message", {})
    content = msg.get("content", "") or ""
    content = content.strip()

    if not content:
        return "Thoda clear likho na, fir se pucho."

    return content


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

    # --- OpenRouter se reply (background thread me) ---
    try:
        answer = await asyncio.to_thread(_call_openrouter_chat, user_text)
    except Exception as e:
        logger.exception("OpenRouter call error: %s", e)
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
        "Akane bot started (OpenRouter + cognitivecomputations/dolphin-mistral-24b-venice-edition:free)..."
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
