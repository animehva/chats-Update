import os
import io
import logging
import asyncio

import requests
from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from groq import Groq
from huggingface_hub import InferenceClient

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- Env vars ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var set karo.")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY env var set karo.")
if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN env var set karo.")

# ---------- Groq client ----------
groq_client = Groq(api_key=GROQ_API_KEY)

# Groq text model
GROQ_MODEL_NAME = "llama-3.3-70b-versatile"  # ensure ye model tumhare Groq account pe available ho

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

# ---------- HF InferenceClient (image) ----------
# yahi client tumne code me dikhaya tha
hf_client = InferenceClient(
    provider="fal-ai",
    api_key=HF_TOKEN,
)

# Flux image model (anime / waifu style ke liye prompt me likh sakte ho)
HF_IMAGE_MODEL = "black-forest-labs/FLUX.1-dev"

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


def is_nsfw_prompt(text: str) -> bool:
    t = normalize(text)
    bad_words = [
        "nude", "naked", "sex", "boobs", "b00bs", "nsfw",
        "bra", "panty", "lingerie", "bikini", "topless",
        "xxx", "hentai", "18+", "porn",
    ]
    return any(w in t for w in bad_words)


# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hey, main Akane hoon, ek virtual chat bot / ex-style dost.\n"
        "- Normal chat: bas message likho.\n"
        "- Anime / waifu style image: /img prompt"
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
        return "Abhi thoda error aa raha hai, baad me try karna."

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


# ---------- HF image call (sync, thread me chalega) ----------
def _generate_image_bytes(prompt: str) -> bytes | None:
    safe_prompt = (
        prompt
        + ", anime waifu style, high quality, safe, modest clothing, no nudity, no nsfw"
    )

    try:
        # client.text_to_image se PIL.Image milta hai (jaisa tumne snippet me diya)
        img = hf_client.text_to_image(
            safe_prompt,
            model=HF_IMAGE_MODEL,
        )
    except Exception as e:
        logger.exception("HF/Fal image error: %s", e)
        return None

    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


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


# ---------- Image command handler ----------
async def img_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.message.reply_text(
            "Kaisi anime / waifu image chahiye?\n"
            "Examples:\n"
            "/img akane coffee shop me baithi hai, cute anime style\n"
            "/img cute anime girl night sky me stars dekh rahi hai"
        )
        return

    if is_nsfw_prompt(prompt):
        await update.message.reply_text(
            "NSFW ya adult images nahi bana sakti. Kuch safe / normal prompt try karo."
        )
        return

    waiting_msg = await update.message.reply_text("Image bana rahi hoon, thoda wait karo...")

    try:
        image_bytes = await asyncio.to_thread(_generate_image_bytes, prompt)
    except Exception as e:
        logger.exception("Image generate thread error: %s", e)
        await waiting_msg.edit_text("Image generate nahi ho paayi, thodi der baad fir try karo.")
        return

    if not image_bytes:
        await waiting_msg.edit_text("Image generate nahi ho paayi, koi aur prompt try karo.")
        return

    bio = io.BytesIO(image_bytes)
    bio.name = "akane_anime.png"

    await waiting_msg.delete()
    await update.message.reply_photo(
        photo=InputFile(bio),
        caption="Lo, bana di 🙂",
    )


# ---------- Main ----------
def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("img", img_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    logger.info("Akane bot started (Groq + HF/Fal image)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
