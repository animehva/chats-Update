import os
import logging
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from groq import Groq
from datasets import load_dataset
from rapidfuzz import process, fuzz

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

# Group trigger word
TRIGGER_NAME = "akane"

# ---------- NSFW filter (dataset ke liye + replies ke liye) ----------
NSFW_KEYWORDS = [
    "nude", "naked", "sex", "boobs", "b00bs", "nsfw",
    "bra", "panty", "lingerie", "bikini", "topless",
    "xxx", "hentai", "18+", "porn", "fuck", "anal",
    "blowjob", "handjob", "breast",
]


def is_safe_text_simple(text: str) -> bool:
    t = text.lower()
    return not any(w in t for w in NSFW_KEYWORDS)


# ---------- HF dataset load + Q/A pairs banane ka kaam ----------
QA_PAIRS = []
QA_QUESTIONS = []


def load_dataset_pairs():
    global QA_PAIRS, QA_QUESTIONS
    try:
        logger.info("HF dataset load ho raha hai: kaushik-harsh-99/Uncensored-SFT-v2")
        ds = load_dataset("kaushik-harsh-99/Uncensored-SFT-v2", split="train")
    except Exception as e:
        logger.exception("Dataset load error: %s", e)
        QA_PAIRS = []
        QA_QUESTIONS = []
        return

    pairs = []
    for ex in ds:
        conv = ex.get("conversations") or []
        # ek human -> assistant pair nikal lo
        for i in range(len(conv) - 1):
            cur = conv[i]
            nxt = conv[i + 1]
            if cur.get("from") == "human" and nxt.get("from") != "human":
                q = str(cur.get("value", "")).strip()
                a = str(nxt.get("value", "")).strip()
                if not q or not a:
                    continue
                # NSFW filter
                if not is_safe_text_simple(q) or not is_safe_text_simple(a):
                    continue
                pairs.append((q, a))
                break

    QA_PAIRS = pairs
    QA_QUESTIONS = [q for q, _ in pairs]
    logger.info("Dataset se %d safe Q/A pairs load hue.", len(QA_PAIRS))


load_dataset_pairs()


def get_dataset_answer(user_text: str, threshold: int = 70) -> str | None:
    """
    User ke text se milta‑julta question dataset me dhundho,
    agar score high ho to uska answer return karo.
    """
    if not QA_PAIRS or not QA_QUESTIONS:
        return None

    try:
        match = process.extractOne(
            user_text,
            QA_QUESTIONS,
            scorer=fuzz.token_set_ratio,
        )
    except Exception as e:
        logger.exception("Fuzzy match error: %s", e)
        return None

    if not match:
        return None

    best_q, score, idx = match  # rapidfuzz: (match, score, index)
    if score < threshold:
        return None

    answer = QA_PAIRS[idx][1]
    if not is_safe_text_simple(answer):
        return None

    return answer.strip() or None


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
        "Hey, main Akane hoon, ek virtual chat bot / ex-style dost.\n"
        "- Normal chat: bas message likho.\n"
        "- Pehle main apne dataset se milta-julta answer dhoondhungi,\n"
        "  agar na mila to khud soch ke jawab dungi."
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

    # safety ke liye ek baar check
    if not is_safe_text_simple(text):
        return "Main aise topics pe baat nahi kar sakti, kuch aur pucho na."

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

    # --- Pehle dataset se answer try karo ---
    dataset_answer = get_dataset_answer(user_text)
    if dataset_answer:
        await update.message.reply_text(dataset_answer)
        return

    # --- Agar dataset se kuch useful na mila to Groq se reply ---
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

    logger.info("Akane bot started (Groq + HF dataset retrieval)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
