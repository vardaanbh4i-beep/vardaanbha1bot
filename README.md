# VardaanBha1Bot

AI-powered Telegram channel/community assistant.

## Features
- AI-generated posts
- AI-generated quizzes
- AI-generated polls
- AI content ideas
- Preview -> Approve -> Publish workflow
- Personalized welcome message for new group members
- Admin-only commands
- Telegram native polls and quizzes

## Commands
- `/start`
- `/help`
- `/post <topic>`
- `/quiz <topic>`
- `/poll <topic>`
- `/ideas`

## Required environment variables
- `BOT_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (optional)
- `CHANNEL_ID`
- `ADMIN_IDS`

## Telegram setup
1. Create the bot with BotFather.
2. Add the bot as an administrator in the target channel.
3. Give it permission to post messages and polls.
4. For welcome messages, add the bot to the group/supergroup and allow it to see member updates/send messages.
5. Put secrets only in Render Environment Variables. Do not upload `.env` or the real token to GitHub.

## Render
Use a Background Worker and start command:

`python bot.py`

Build command:

`pip install -r requirements.txt`
