import os
import json
import logging
import sqlite3
from functools import wraps

from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# =========================
# SETTINGS
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # @channelusername or -100123...
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DB_NAME = os.getenv("DB_NAME", "users.db")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("vardaanbha1bot")

ai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Conversation states
BROADCAST_MESSAGE = 1
SUPPORT_MESSAGE = 2


# =========================
# DATABASE
# =========================
def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL DEFAULT 'Friend',
            subscribed INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def save_user(chat_id: int, first_name: str):
    name = (first_name or "Friend").strip()[:100] or "Friend"
    conn = db()
    conn.execute(
        """
        INSERT INTO users (chat_id, first_name, subscribed, last_seen)
        VALUES (?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(chat_id) DO UPDATE SET
            first_name=excluded.first_name,
            subscribed=1,
            last_seen=CURRENT_TIMESTAMP
        """,
        (chat_id, name),
    )
    conn.commit()
    conn.close()


def set_subscribed(chat_id: int, value: int):
    conn = db()
    conn.execute(
        "UPDATE users SET subscribed=?, last_seen=CURRENT_TIMESTAMP WHERE chat_id=?",
        (value, chat_id),
    )
    conn.commit()
    conn.close()


def get_subscribers():
    conn = db()
    rows = conn.execute(
        "SELECT chat_id, first_name FROM users WHERE subscribed=1 ORDER BY chat_id"
    ).fetchall()
    conn.close()
    return rows


def get_user_count(active_only=True):
    conn = db()
    if active_only:
        row = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscribed=1"
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    conn.close()
    return int(row[0])


# =========================
# HELPERS
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid is None or not is_admin(uid):
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ Sirf authorized admin is feature ko use kar sakta hai."
                )
            return
        return await func(update, context)

    return wrapper


async def ask_ai(prompt: str) -> str:
    response = await ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert Telegram community content strategist. "
                    "Create concise, useful and natural content. Prefer Hindi/Hinglish "
                    "unless another language is requested. Avoid spammy clickbait."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


# =========================
# USER COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.effective_message:
        return

    # IMPORTANT: only first name is saved/shown. Username is not used.
    save_user(user.id, user.first_name)

    name = user.first_name or "Friend"

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🆘 Help & Support", callback_data="support")],
            [InlineKeyboardButton("📋 Commands", callback_data="commands")],
        ]
    )

    await update.effective_message.reply_text(
        f"👋 Welcome {name}!\n\n"
        "🎉 Hamari community me aapka swagat hai.\n"
        "Yahan useful posts, polls aur quizzes milenge.\n\n"
        "🟢 Aapka bot subscription active hai.",
        reply_markup=keyboard,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📌 Bot Commands\n\n"
        "/start — Bot start / subscription ON\n"
        "/stop — DM notifications OFF\n"
        "/status — Subscription status\n"
        "/support — Help & support\n"
        "/help — Commands\n\n"
        "Admin:\n"
        "/admin — Admin panel\n"
        "/broadcast — Users ko message bheje\n"
        "/stats — User count\n"
        "/reply CHAT_ID MESSAGE — Individual reply\n"
        "/post TOPIC — AI post\n"
        "/quiz TOPIC — AI quiz\n"
        "/poll TOPIC — AI poll\n"
        "/ideas — AI content ideas"
    )


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        set_subscribed(update.effective_user.id, 0)
    await update.effective_message.reply_text(
        "🔕 Notifications OFF kar di gayi hain.\n"
        "Dobara /start bhejne par notifications ON ho jayengi."
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    conn = db()
    row = conn.execute(
        "SELECT subscribed FROM users WHERE chat_id=?", (uid,)
    ).fetchone()
    conn.close()

    if row and row[0] == 1:
        text = "🟢 Aapki DM subscription ACTIVE hai."
    else:
        text = "🔴 Aapki DM subscription OFF hai.\n/start bhejkar ON karein."

    await update.effective_message.reply_text(text)


# =========================
# SUPPORT
# =========================
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        save_user(
            update.effective_user.id,
            update.effective_user.first_name,
        )

    await update.effective_message.reply_text(
        "🆘 Apni problem/message yahan bhejiye.\n"
        "Main ise admin tak forward kar dunga.\n\n"
        "Cancel karne ke liye /cancel bhejein."
    )
    return SUPPORT_MESSAGE


async def support_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return ConversationHandler.END

    name = user.first_name or "Friend"

    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "🆘 NEW SUPPORT REQUEST\n\n"
                    f"👤 Name: {name}\n"
                    f"🆔 Chat ID: {user.id}\n\n"
                    "User message:"
                ),
            )
            await message.copy(chat_id=admin_id)
            sent += 1
        except Exception:
            log.exception("Support forward failed")

    if sent:
        await message.reply_text(
            "✅ Aapka message admin ko bhej diya gaya hai."
        )
    else:
        await message.reply_text(
            "⚠️ Admin ko message bhejne me problem hui. Baad me try karein."
        )

    return ConversationHandler.END


# =========================
# ADMIN PANEL
# =========================
@admin_only
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👥 Users", callback_data="admin:users"),
                InlineKeyboardButton("📊 Stats", callback_data="admin:stats"),
            ],
            [
                InlineKeyboardButton(
                    "📢 Broadcast Help", callback_data="admin:broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    "🆘 Support Help", callback_data="admin:support"
                )
            ],
        ]
    )

    await update.effective_message.reply_text(
        "🔐 ADMIN PANEL\n\n"
        "📢 Broadcast: /broadcast\n"
        "👤 Individual reply: /reply CHAT_ID MESSAGE\n"
        "📊 Stats: /stats\n",
        reply_markup=keyboard,
    )


@admin_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active = get_user_count(True)
    total = get_user_count(False)
    await update.effective_message.reply_text(
        f"📊 User Statistics\n\n"
        f"🟢 Active subscribers: {active}\n"
        f"👥 Total saved users: {total}"
    )


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    action = query.data

    if action == "admin:users" or action == "admin:stats":
        active = get_user_count(True)
        total = get_user_count(False)
        await query.edit_message_text(
            f"📊 USERS\n\n"
            f"🟢 Active: {active}\n"
            f"👥 Total saved: {total}"
        )

    elif action == "admin:broadcast":
        await query.edit_message_text(
            "📢 BROADCAST\n\n"
            "Admin chat me /broadcast bhejiye.\n"
            "Uske baad jo bhi ONE message bhejoge, "
            "woh active subscribers ko forward/copy ho jayega."
        )

    elif action == "admin:support":
        await query.edit_message_text(
            "🆘 SUPPORT\n\n"
            "User support request ke saath Chat ID milega.\n"
            "Reply ke liye:\n"
            "/reply CHAT_ID MESSAGE"
        )


# =========================
# BROADCAST
# =========================
@admin_only
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📢 Broadcast mode ON.\n\n"
        "Ab apna ONE message bhejiye.\n"
        "Text, photo, video, document, etc. bhej sakte hain.\n\n"
        "Cancel: /cancel"
    )
    return BROADCAST_MESSAGE


async def broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    admin_id = update.effective_user.id

    if not message:
        return ConversationHandler.END

    users = get_subscribers()
    success = 0
    failed = 0
    blocked_ids = []

    status_message = await message.reply_text(
        f"📤 Broadcast start...\n👥 Recipients: {len(users)}"
    )

    for chat_id, first_name in users:
        try:
            await message.copy(chat_id=chat_id)
            success += 1
        except Exception as e:
            failed += 1
            error_text = str(e).lower()

            # If user blocked/deactivated the bot, deactivate them.
            if (
                "blocked" in error_text
                or "chat not found" in error_text
                or "deactivated" in error_text
                or "user is deactivated" in error_text
            ):
                blocked_ids.append(chat_id)

    for chat_id in blocked_ids:
        set_subscribed(chat_id, 0)

    await status_message.edit_text(
        "✅ Broadcast complete\n\n"
        f"📨 Sent: {success}\n"
        f"⚠️ Failed: {failed}\n"
        f"🚫 Deactivated/blocked users disabled: {len(blocked_ids)}"
    )

    return ConversationHandler.END


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# =========================
# INDIVIDUAL ADMIN REPLY
# =========================
@admin_only
async def reply_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.effective_message.reply_text(
            "Usage:\n/reply CHAT_ID Your message here"
        )
        return

    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("⚠️ Invalid Chat ID.")
        return

    text = " ".join(context.args[1:]).strip()

    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
        await update.effective_message.reply_text("✅ Message sent.")
    except Exception as e:
        await update.effective_message.reply_text(
            f"⚠️ Message send failed: {e}"
        )


# =========================
# AI CONTENT
# =========================
def publish_keyboard(kind: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Publish", callback_data=f"pub:{kind}"
                ),
                InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"cancel:{kind}"
                ),
            ]
        ]
    )


@admin_only
async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args).strip()
    if not topic:
        await update.effective_message.reply_text(
            "Example: /post AI technology ke uses"
        )
        return

    text = await ask_ai(
        f"Create one Telegram post about: {topic}. "
        "Use a strong title, 3-6 short points and a simple CTA/question. "
        "Keep it mobile-friendly."
    )

    context.user_data["pending_post"] = text
    await update.effective_message.reply_text(
        "📝 AI POST PREVIEW\n\n" + text,
        reply_markup=publish_keyboard("post"),
    )


@admin_only
async def ideas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await ask_ai(
        "Give 10 varied Telegram community content ideas: "
        "polls, quizzes, questions, mini challenges and educational posts. "
        "Return a numbered list."
    )
    await update.effective_message.reply_text(
        "💡 AI CONTENT IDEAS\n\n" + text
    )


@admin_only
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args).strip()
    if not topic:
        await update.effective_message.reply_text(
            "Example: /quiz Indian history"
        )
        return

    raw = await ask_ai(
        f"Create ONE Telegram quiz question about {topic}. "
        "Return ONLY valid JSON with keys: question, options, correct_index, explanation. "
        "options exactly 4 strings; correct_index 0-3."
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
        await update.effective_message.reply_text(
            "⚠️ Valid quiz format nahi mila. Dobara try karein."
        )
        return

    context.user_data["pending_quiz"] = {
        "question": question,
        "options": options,
        "correct": correct,
        "explanation": explanation,
    }

    await update.effective_message.reply_text(
        "🧠 QUIZ PREVIEW\n\n"
        f"{question}\n\n"
        + "\n".join(
            f"{i + 1}. {option}"
            for i, option in enumerate(options)
        ),
        reply_markup=publish_keyboard("quiz"),
    )


@admin_only
async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args).strip()
    if not topic:
        await update.effective_message.reply_text(
            "Example: /poll Aapko kaunsa content pasand hai?"
        )
        return

    raw = await ask_ai(
        f"Create ONE engaging Telegram poll about {topic}. "
        "Return ONLY valid JSON with keys question and options. "
        "options must contain 2-8 short strings."
    )

    try:
        data = json.loads(raw)
        question = str(data["question"])
        options = [str(x) for x in data["options"]]

        if not 2 <= len(options) <= 8:
            raise ValueError
    except Exception:
        await update.effective_message.reply_text(
            "⚠️ Valid poll format nahi mila. Dobara try karein."
        )
        return

    context.user_data["pending_poll"] = {
        "question": question,
        "options": options,
    }

    await update.effective_message.reply_text(
        "📊 POLL PREVIEW\n\n"
        f"{question}\n\n"
        + "\n".join(f"• {x}" for x in options),
        reply_markup=publish_keyboard("poll"),
    )


async def publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
            )
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
                is_anonymous=False,
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
                is_anonymous=False,
            )
            await query.edit_message_text("✅ Poll channel me publish ho gaya.")

    except Exception:
        log.exception("Publish failed")
        await query.edit_message_text(
            "⚠️ Publish failed. Channel permissions/CHANNEL_ID check karein."
        )


# =========================
# CHANNEL/GROUP WELCOME
# =========================
async def welcome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm:
        return

    old = cm.old_chat_member.status
    new = cm.new_chat_member.status

    if new not in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    }:
        return

    if old in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    }:
        return

    if cm.from_user.is_bot:
        return

    member = cm.new_chat_member.user

    # IMPORTANT: username is NOT shown.
    name = member.first_name or "Friend"

    welcome = (
        f"👋 Welcome {name}!\n\n"
        "🎉 Hamari community me aapka swagat hai.\n"
        "Yahan quizzes, polls aur useful posts milenge.\n\n"
        "💬 Active rahiye, vote kijiye aur apni opinion share kijiye!"
    )

    try:
        await context.bot.send_message(
            chat_id=cm.chat.id,
            text=welcome,
        )
    except Exception:
        log.exception("Welcome message failed")


# =========================
# CALLBACK ROUTER
# =========================
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data.startswith("admin:"):
        await admin_panel_callback(update, context)
        return

    if query.data.startswith("pub:") or query.data.startswith("cancel:"):
        await publish_callback(update, context)
        return

    if query.data == "commands":
        await query.answer()
        await query.edit_message_text(
            "📌 Commands\n\n"
            "/start — Start / subscribe\n"
            "/stop — Notifications OFF\n"
            "/status — Status\n"
            "/support — Help & Support\n"
            "/help — Commands"
        )
        return

    if query.data == "support":
        await query.answer()
        await query.edit_message_text(
            "🆘 Support ke liye /support bhejiye."
        )
        return

    await query.answer()


# =========================
# MAIN
# =========================
def main():
    init_db()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # Support conversation
    support_conversation = ConversationHandler(
        entry_points=[CommandHandler("support", support_start)],
        states={
            SUPPORT_MESSAGE: [
                MessageHandler(
                    ~filters.COMMAND & filters.ALL,
                    support_receive,
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    # Admin broadcast conversation
    broadcast_conversation = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_MESSAGE: [
                MessageHandler(
                    ~filters.COMMAND & filters.ALL,
                    broadcast_receive,
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    app.add_handler(support_conversation)
    app.add_handler(broadcast_conversation)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("status", status_cmd))

    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("reply", reply_user_cmd))

    app.add_handler(CommandHandler("post", post_cmd))
    app.add_handler(CommandHandler("quiz", quiz_cmd))
    app.add_handler(CommandHandler("poll", poll_cmd))
    app.add_handler(CommandHandler("ideas", ideas_cmd))

    app.add_handler(
        CallbackQueryHandler(
            button_router,
            pattern=r"^(admin:|pub:|cancel:|support$|commands$)",
        )
    )

    app.add_handler(
        ChatMemberHandler(
            welcome_handler,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    log.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
