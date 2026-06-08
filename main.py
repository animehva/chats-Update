import os
import logging
import asyncio

from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google import genai
from google.genai import types

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- Environment vars ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var set karo.")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY env var set karo.")

# ---------- Gemini client ----------
client = genai.Client(api_key=GEMINI_API_KEY)

# Text + image models (AI Studio se exact naam copy karke yahan daal sakte ho)
TEXT_MODEL_NAME = "gemini-1.5-flash-8b"       # fast text model
IMAGE_MODEL_NAME = "gemini-2.5-flash-image"   # image generation model

# Text generation config: max output + fast reply
SYSTEM_PROMPT = """
Tum Akane ho, ek virtual ex-girlfriend style chat bot.
Rules:

- Normal situation me short Hinglish replies do (1–3 chhoti sentences).
- Agar user specifically detail maange to lamba answer de sakti ho.
- Tone: casual, thodi flirty / caring, par hamesha respect rakho.
- Gali, adult (18+), ya vulgar content mat dena.
- Kabhi mat bolo ki tum real human ho ya tumhara physical body hai.
- Jab koi pooche tum kya ho (insaan, bot, etc.) to bolo:
  "Main Akane naam ka virtual chat bot hoon, real insaan nahi, sirf chat ke liye."
- Apne answers me "AI", "artificial", "language model", "machine learning" jaisi technical cheezen mat bolo.
- Agar koi tumhari age pooche to hamesha bolo ki tum 21 saal ki ho.
"""

TEXT_GENERATION_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    temperature=0.8,
    top_p=0.9,
    max_output_tokens=512,  # lamba output allow, par model ko short bola hai
)

IMAGE_GENERATION_CONFIG = types.GenerateContentConfig(
    response_modalities=["IMAGE"],
)

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


# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hey, main Akane hoon, ek virtual chat bot / ex-style dost. "
        "Text chat ke liye normal message bhejo, image ke liye /img prompt likho."
    )


# ---------- Gemini text call (sync, thread me chalega) ----------
def _call_gemini_text(user_text: str) -> str:
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_text)],
        )
    ]
    resp = client.models.generate_content(
        model=TEXT_MODEL_NAME,
        contents=contents,
        config=TEXT_GENERATION_CONFIG,
    )
    text = (resp.text or "").strip()
    if not text:
        return "Thoda clear likho na, fir se pucho."
    return text


# ---------- Gemini image call (sync, thread me chalega) ----------
def _generate_image_bytes(prompt: str) -> bytes | None:
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )
    ]

    image_bytes = None

    for chunk in client.models.generate_content_stream(
        model=IMAGE_MODEL_NAME,
        contents=contents,
        config=IMAGE_GENERATION_CONFIG,
    ):
        if not chunk.parts:
            continue
        part = chunk.parts[0]
        if getattr(part, "inline_data", None) and part.inline_data.data:
            # Har naya chunk latest image data la sakta hai; last wala le lo
            image_bytes = part.inline_data.data

    return image_bytes


# ---------- Main chat handler (text) ----------
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user_text = update.message.text

    # --- Simple fixed rules ---

    # Naam
    if is_asking_name(user_text):
        await update.message.reply_text("Mera naam Akane hai.")
        return

    # Age
    if is_asking_age(user_text):
        await update.message.reply_text("Main 21 saal ki hoon.")
        return

    # Identity (bot / human)
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
            # Na "akane" likha, na hi bot ke message ko reply kiya -> ignore
            return

    # --- Gemini se reply (background thread me) ---
    try:
        answer = await asyncio.to_thread(_call_gemini_text, user_text)
    except Exception as e:
        logger.exception("Gemini text error: %s", e)
        await update.message.reply_text(
            "Abhi thoda error aa raha hai, thodi der baad fir try kar lena."
        )
        return

    await update.message.reply_text(answer)


# ---------- Image command handler ----------
async def img_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    # /img ke baad jo bhi likha hai use prompt bana do
    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.message.reply_text(
            "Kis type ki image chahiye? Example:\n"
            "/img akane beach pe sunset dekh rahi hai"
        )
        return

    # Image generate karte time user ko bata do thoda wait kare
    waiting_msg = await update.message.reply_text("Image bana rahi hoon, thoda wait karo...")

    try:
        image_bytes = await asyncio.to_thread(_generate_image_bytes, prompt)
    except Exception as e:
        logger.exception("Gemini image error: %s", e)
        await waiting_msg.edit_text("Image generate nahi ho paayi, thodi der baad fir try karo.")
        return

    if not image_bytes:
        await waiting_msg.edit_text("Image generate nahi ho paayi, koi aur prompt try karo.")
        return

    photo = InputFile(image_bytes, filename="akane_image.png")
    await waiting_msg.delete()
    await update.message.reply_photo(
        photo=photo,
        caption="Lo, bana di 🙂",
    )


# ---------- Main ----------
def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("img", img_handler))  # /img command
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    logger.info("Akane bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
