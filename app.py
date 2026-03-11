# First install nest_asyncio if you haven't already
# !pip install nest_asyncio

from huggingface_hub import InferenceClient
import nest_asyncio
nest_asyncio.apply()
import asyncio
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
import pytz
from flask import Flask, request #for webhook handling
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Configuration - REPLACE THESE WITH YOUR ACTUAL VALUES
#bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))  # Initialize the bot with the token from environment variable
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
FOOTER = os.getenv("FOOTER","" )      # Use environment variable for security
HF_API_KEY = os.getenv('HF_API_KEY')  # Use environment variable for security
if not HF_API_KEY:
    raise ValueError("No HF_API_KEY set")
#HF_MODEL = 'zai-org/GLM-4.7-Flash:novita'  # Free model
#HF_MODEL = 'mistralai/Mistral-7B-Instruct-v0.2'
HF_MODEL = 'meta-llama/Meta-Llama-3-8B-Instruct'                                       

# Initialize Hugging Face client
client = InferenceClient(
    api_key=HF_API_KEY,
)

telethon_client = TelegramClient(StringSession(TG_STRING_SESSION), TG_API_ID, TG_API_HASH)
async def start_telethon():
    await telethon_client.start()
    print("✅ Telethon connected")

# Flask app for webhook
app = Flask(__name__)
@app.get("/")
def health():
    return "OK", 200
application = None
event_loop = None
BOT_READY = False

#@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"] )
def webhook():
    global application, event_loop, BOT_READY
    
    data = request.get_json(silent=True)
    if not data:
        return "ok", 200

    # If bot not ready yet, don't 503 (Telegram will retry and pile up)
    if not BOT_READY or application is None or event_loop is None:
        return "ok", 200

    
    update = Update.de_json(data, application.bot)

    # Run handler processing inside PTB's asyncio loop
    asyncio.run_coroutine_threadsafe(application.process_update(update), event_loop)

    return "ok", 200
    
# Your existing LLM prompt for extracting job details

EXTRACTION_PROMPT = """
You are a data extraction engine.

Your task is to extract structured information from the job post below.

You MUST follow these rules strictly:

1. for requirements and benefits: they should be in bullet points format and a maximum of 2-3 point each and a minumum of 1. Do not leave empty.
2. Do NOT return JSON.
3. Do NOT add explanations.
4. Do NOT add extra text before or after.
5. Output EXACTLY 8 lines.
6. Each line must follow this format:
   key|||value

The keys MUST appear in this exact order:

company|||
sector|||
location|||
target_group|||
opportunitytype|||
requirements|||
benefits|||
How to Apply|||

If a value is unknown, leave it empty after the delimiter.

Definitions:

- company: Official company name.
- sector: Industry category (e.g, Consulting, VC, PE, Banking, Tech, Government, etc.)
- location: City and country if mentioned.
- target_group:
    Students
    Fresh Graduates
    Professionals 
- opportunitytype:
    COOP (which is a Cooperative Education Program for students)
    GDP (which is a fresh Graduate Development Program)
    Part Time
    Online Training Program
    Full Time
- requirements:
 Key opportunity requirements mentioned in the job post. e.g, "must be a student", "at least 1 year of experience", "fresh graduates only", "must have a degree in X", etc. 
- benefits:
 Key benefits or perks mentioned in the job post. If none are found, put "Competitive Salary"

- How to Apply: URL to the job post, application page link, or instructions on how to apply if mentioned (could be recruiter email, application link, or instructions like "apply through our website", etc.)
Job Post:
{job_post}
"""

# Your Telegram channel formatting template
TELEGRAM_FORMAT_TEMPLATE = """ New ** #{opportunitytype}** opportunity for **{target_group}** in **{sector}** sector !
🏢 {company}
📍 {location}

Requirements:
{requirements}

Benefits:
{benefits}

🔗 How to Apply: {how_to_apply}
-----------------------
{FOOTER}
-----------------------"""


async def test_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Received /start command from {update.effective_user.first_name}")
    await update.message.reply_text("✅ Bot is working! /start command received.")


async def test_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received /help command")
    await update.message.reply_text("🤖 Test Bot Commands:\n/start - Test start command\n/help - This help\nAny text - Echo test")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with instructions"""
    welcome_text = """
🤖 Job Post Formatter Bot

Hello! I'll help you format job posts for your Telegram channel.

📝 How to use:
1. Paste any job post from LinkedIn, Indeed, Wuzzuf, etc.
2. I'll extract the key details and format it perfectly
3. Copy the formatted result to your Telegram channel

🚀 Example:
Just send me:
"Senior Python Developer needed at TechCorp in San Francisco. Remote work available. Apply at https://example.com/job123"

Let's get started! 🎯
"""
    await update.message.reply_text(welcome_text)

def parse_model_output(text):
    data = {}
    lines = text.strip().split("\n")

    for line in lines:
        if "|||" in line:
            key, value = line.split("|||", 1)
            data[key.strip()] = value.strip() if value.strip() else ""

    return data

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""

    # If we are waiting for content to schedule
    if user_id in pending_schedule:
        dt = pending_schedule.pop(user_id)

        if not CHANNEL_ID:
            await update.message.reply_text("CHANNEL_ID is not set.")
            return

        try:
            await schedule_channel_post(text, dt)
            dt_display = dt.strftime("%Y-%m-%d %H:%M %Z")
            save_last(dt_display)

            await update.message.reply_text(
                    f"✅ Scheduled in Telegram!\n"
                    f"📌 Last scheduled post: {dt_display}\n"
                    "Open your channel → Scheduled Messages to view it."
                )

        except Exception as e:
                logging.error(f"Failed to schedule via Telethon: {e}")
                await update.message.reply_text(f"Failed to schedule: {e}")

        return

    # Otherwise: your existing formatting flow
    await format_job_post(update, context)


async def format_job_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main function to format job posts"""
    job_post = update.message.text
    
    if not job_post.strip():
        await update.message.reply_text("Please send a job post to format! 📝")
        return

    await update.message.reply_text("🔍 Extracting job details... This may take a moment.")
    
    try:
        #import asyncio
        #from huggingface_hub import InferenceClient
        client = InferenceClient(api_key=HF_API_KEY)
        logging.info("✅ HuggingFace client initialized successfully")

        completion = client.chat.completions.create(
            model=HF_MODEL,
            messages=[
                {"role": "system", "content": "You extract structured job data and ALWAYS return valid JSON only."},
                {"role": "user", "content": EXTRACTION_PROMPT.format(job_post=job_post)}
            ],
            max_tokens=500,
            temperature=0
        )

        structured_data = completion.choices[0].message.content.strip()
        print("MODEL RAW OUTPUT:")
        print(structured_data)
        data = parse_model_output(structured_data)
        print("PARSED DATA:")
        print(data)


        # Parse the JSON-like response (basic parsing for demo)
        formatted_post = TELEGRAM_FORMAT_TEMPLATE.format(
    opportunitytype=data.get("opportunitytype", "Position"),
    target_group=data.get("target_group", "Level"),
    company=data.get("company", "Company"),
    location=data.get("location", "Location"),
    sector=data.get("sector", "Description"),
    requirements=data.get("requirements", "Requirements"),
    benefits=data.get("benefits", "Benefits"),
    how_to_apply=data.get("How to Apply", "how_to_apply"),
    FOOTER=os.getenv("FOOTER", "FOOTER")  # Add footer from environment variable
)

        
        # Send formatted post
        await update.message.reply_text(
            formatted_post + "\n\n" +
            f"#{data.get('location', 'Location').replace(',', '_').replace(' ', '_')} #{data.get('sector', 'Description').replace(',', '_').replace(' ', '_')} #{data.get('target_group', 'Target Group').replace(',', '_').replace(' ', '_')}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logging.error(f"Error processing job post: {e}")
        await update.message.reply_text(f"DEBUG ERROR:\n{str(e)}")
    
async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Expect: /schedule YYYY-MM-DD HH:MM
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n/schedule YYYY-MM-DD HH:MM\nExample:\n/schedule 2026-03-15 18:00"
        )
        return

    dt_str = f"{context.args[0]} {context.args[1]}"

    try:
        cairo = pytz.timezone("Africa/Cairo")
        dt = cairo.localize(datetime.strptime(dt_str, "%Y-%m-%d %H:%M"))
    except ValueError:
        await update.message.reply_text(
            "Invalid date format.\nUse:\n/schedule YYYY-MM-DD HH:MM"
        )
        return

    # store schedule state
    pending_schedule[user_id] = dt

    await update.message.reply_text(
        "🕒 Got it.\nNow send the formatted post you want to schedule."
    )    


async def schedule_channel_post(text: str, when_dt: datetime):
    """
    when_dt must be timezone-aware datetime.
    """
    print("Scheduling via Telethon")
    entity = await telethon_client.get_entity(CHANNEL_ID)

    # Telethon versions differ: some use schedule=, some schedule_date=
    try:
        return await telethon_client.send_message(entity, text, schedule=when_dt)
    except TypeError:
        return await telethon_client.send_message(entity, text, schedule_date=when_dt)


async def main():
    global application, BOT_READY
    logging.info("Starting bot...")
    
    # Build the application
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("help", test_help))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("schedule", schedule_cmd))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))   
    
    # Initialize the application
    logging.info("Initializing application...")
    await application.initialize()
    
    logging.info("Bot is ready to receive messages")
    
    await application.start()
    await telethon_client.start()
    me = await telethon_client.get_me()
    print("Telethon logged in as:", me.username or me.first_name, "bot?", me.bot)
    BOT_READY = True
   
    await asyncio.Event().wait()
    logging.info("bot is working...")

import threading

def run_ptb():
    global event_loop
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    event_loop.run_until_complete(main())

if __name__ == "__main__":
    # Start PTB (python-telegram-bot) in background
    t = threading.Thread(target=run_ptb, daemon=True)
    t.start()
    # Start Flask web server (required for Render)
    port = int(os.environ.get("PORT", 10000)) #5000 last commit
    app.run(host="0.0.0.0", port=port)
















