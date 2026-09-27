import os
import json
import logging
from datetime import datetime, timezone

from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, ChatMemberHandler
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("vardaanbha1bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # Example: @your_channel_username or -100...
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing")

ai = AsyncOpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
You are an expert Telegram community content strategist.
Create concise, attractive, useful and natural content for a Telegram channel.
Prefer Hindi/Hinglish unless the user requests another language.
Do not invent current facts. If a claim may be time-sensitive, phrase it cautiously.
Use emojis sparingly and avoid spammy clickbait.
"""

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid is None or not is_admin(uid):
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Sirf authorized admin is command ko use kar sakta hai.")
            return
        return await func(update, context)
    return wrapper

async def ask_ai(prompt: str) -> str:
    response = await ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 VardaanBha1Bot ready!\n\n"
        "Commands:\n"
        "/post <topic> — AI post draft\n"
        "/quiz <topic> — AI quiz\n"
        "/poll <topic> — AI poll\n"
        "/ideas — content ideas\n"
        "/help — commands\n\n"
        "Admin approval ke baad hi content publish hota hai."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Commands\n\n"
        "/post <topic>\n"
        "/quiz <topic>\n"
        "/poll <topic>\n"
        "/ideas\n\n"
        "Example: /post motivation for students"
    )

def publish_keyboard(kind: str, payload: str):
    # Telegram callback data has a practical size limit, so payload is stored in context.user_data.
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Publish", callback_data=f"pub:{kind}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{kind}")
        ]
    ])

@admin_only
async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args).strip()
    if not topic:
        await update.message.reply_text("Example: /post AI technology ke latest uses")
        return

    text = await ask_ai(
        f"Create one Telegram post about: {topic}\n"
        "Format: strong title, 3-6 short points, and a simple CTA/question at the end. "
        "Keep it mobile-friendly."
    )

    context.user_data["pending_post"] = text
    await update.message.reply_text(
        "📝 AI Post Preview:\n\n" + text,
        reply_markup=publish_keyboard("post", text)
    )

@admin_only
async def ideas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await ask_ai(
        "Give 10 varied Telegram channel content ideas designed for meaningful engagement: "
        "polls, quizzes, short posts, questions, mini challenges and educational posts. "
        "Return a numbered list."
    )
    await update.message.reply_text("💡 AI Content Ideas\n\n" + text)

@admin_only
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args).strip()
    if not topic:
        await update.message.reply_text("Example: /quiz Indian history")
        return

    raw = await ask_ai(
        f"Create ONE Telegram quiz question about {topic}. "
        "Return ONLY valid JSON with keys: question, options, correct_index, explanation. "
        "options must contain exactly 4 strings and correct_index must be 0-3."
    )

    try:
        data = json.loads(raw)
        question = str(data["question"])
        options = [str(x) for x in data["options"]]
        correct = int(data["correct_index"])
        explanation = str(data.get("explanation", ""))
        if len(options) != 4 or correct not in range(4):
            raise ValueError
    except Exception:
        await update.message.reply_text("⚠️ AI ne valid quiz format nahi diya. Dobara /quiz try karein.")
        return

    context.user_data["pending_quiz"] = {
        "question": question, "options": options,
        "correct": correct, "explanation": explanation
    }
    await update.message.reply_text(
        f"🧠 Quiz Preview\n\n{question}\n\n" +
        "\n".join(f"{i+1}. {x}" for i, x in enumerate(options)) +
        "\n\nPublish karna hai?",
        reply_markup=publish_keyboard("quiz", "")
    )

@admin_only
async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args).strip()
    if not topic:
        await update.message.reply_text("Example: /poll Aapko kaunsa content pasand hai?")
        return

    raw = await ask_ai(
        f"Create ONE engaging Telegram poll about {topic}. "
        "Return ONLY valid JSON with keys question and options. "
        "options must contain 2 to 8 short strings."
    )
    try:
        data = json.loads(raw)
        question = str(data["question"])
        options = [str(x) for x in data["options"]]
        if not 2 <= len(options) <= 8:
            raise ValueError
    except Exception:
        await update.message.reply_text("⚠️ AI ne valid poll format nahi diya. Dobara /poll try karein.")
        return

    context.user_data["pending_poll"] = {"question": question, "options": options}
    await update.message.reply_text(
        f"📊 Poll Preview\n\n{question}\n\n" +
        "\n".join(f"• {x}" for x in options) +
        "\n\nPublish karna hai?",
        reply_markup=publish_keyboard("poll", "")
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    action, kind = query.data.split(":", 1)

    if action == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    if not CHANNEL_ID:
        await query.edit_message_text(
            "⚠️ CHANNEL_ID Render environment variable me set nahi hai."
        )
        return

    try:
        if kind == "post":
            text = context.user_data.get("pending_post")
            if not text:
                await query.edit_message_text("⚠️ Pending post nahi mila.")
                return
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text)
            await query.edit_message_text("✅ Post channel me publish ho gaya.")

        elif kind == "quiz":
            q = context.user_data.get("pending_quiz")
            if not q:
                await query.edit_message_text("⚠️ Pending quiz nahi mila.")
                return
            await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=q["question"],
                options=q["options"],
                type="quiz",
                correct_option_id=q["correct"],
                is_anonymous=False
            )
            await query.edit_message_text("✅ Quiz channel me publish ho gaya.")

        elif kind == "poll":
            p = context.user_data.get("pending_poll")
            if not p:
                await query.edit_message_text("⚠️ Pending poll nahi mila.")
                return
            await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=p["question"],
                options=p["options"],
                is_anonymous=False
            )
            await query.edit_message_text("✅ Poll channel me publish ho gaya.")

    except Exception as e:
        log.exception("Publish failed")
        await query.edit_message_text(f"⚠️ Publish failed: {e}")

async def welcome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm:
        return

    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    if new not in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED}:
        return
    if old in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED}:
        return
    if cm.from_user.is_bot:
        return

    member = cm.new_chat_member.user
    name = member.first_name or "Friend"
    welcome = (
        f"👋 Welcome {name}!\n\n"
        "🎉 Hamari community me aapka swagat hai.\n"
        "Yahan quizzes, polls aur useful posts milenge.\n\n"
        "💬 Active rahiye, vote kijiye aur apni opinion share kijiye!"
    )
    try:
        await context.bot.send_message(chat_id=cm.chat.id, text=welcome)
    except Exception:
        log.exception("Welcome message failed")

def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("post", post_cmd))
    app.add_handler(CommandHandler("quiz", quiz_cmd))
    app.add_handler(CommandHandler("poll", poll_cmd))
    app.add_handler(CommandHandler("ideas", ideas_cmd))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(pub|cancel):"))
    app.add_handler(ChatMemberHandler(welcome_handler, ChatMemberHandler.CHAT_MEMBER))

    log.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
