# First install nest_asyncio if you haven't already
# !pip install nest_asyncio

from huggingface_hub import InferenceClient
import nest_asyncio
nest_asyncio.apply()

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
bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))  # Initialize the bot with the token from environment variable
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')  # Use environment variable for security
HF_API_KEY = os.getenv('HF_API_KEY')  # Use environment variable for security
if not HF_API_KEY:
    raise ValueError("No HF_API_KEY set")
#HF_MODEL = 'zai-org/GLM-4.7-Flash:novita'  # Free model
#HF_MODEL = 'mistralai/Mistral-7B-Instruct-v0.2'
HF_MODEL = 'meta-llama/Meta-Llama-3-8B-Instruct'                                       

# Initialize Hugging Face client

#os.environ["HF_API_TOKEN"] = HF_API_KEY
#os.environ["TELEGRAM_TOKEN"] = TELEGRAM_TOKEN
client = InferenceClient(
    api_key=HF_API_KEY,
)

# Flask app for webhook
app = Flask(__name__)
application = None
event_loop = None

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    global application, event_loop

    if application is None or event_loop is None:
        return "Bot not ready", 503

    data = request.get_json(force=True)
    update = Update.de_json(data, application.bot)

    # Run handler processing inside PTB's asyncio loop
    asyncio.run_coroutine_threadsafe(application.process_update(update), event_loop)

    return "ok", 200
    @app.get("/")
    def health():
        return "OK", 200


# Run app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render sets PORT automatically
    app.run(host="0.0.0.0", port=port)

# Your existing LLM prompt for extracting job details

EXTRACTION_PROMPT = """
You are a data extraction engine.

Your task is to extract structured information from the job post below.

You MUST follow these rules strictly:

1. Return ONLY plain text.
2. Do NOT return JSON.
3. Do NOT add explanations.
4. Do NOT add bullet points.
5. Do NOT add extra text before or after.
6. Output EXACTLY 8 lines.
7. Each line must follow this format:
   key|||value

The keys MUST appear in this exact order:

company|||
sector|||
location|||
target_group|||
opportunitytype|||
requirements|||
benefits|||
link|||

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
 Key opportunity requirements mentioned in the job post if stressed, otherwise leave empty. e.g, "must be a student", "at least 1 year of experience", "fresh graduates only", "must have a degree in X", etc. keep at a maximum of 2-3 requirements if mentioned, otherwise leave empty.
- benefits:
 Key benefits or perks mentioned in the job post if stressed, otherwise leave empty.

- link: URL to the job post or application page.
Job Post:
{job_post}
"""

# Your Telegram channel formatting template
TELEGRAM_FORMAT_TEMPLATE = """ New ** #{opportunitytype}** opportunity for **{target_group}** in **{sector}** sector !
🏢 {company}
📍 {location}

requirements:
{requirements}

Benefits:
{benefits}

🔗 Apply here: {link}
-----------------------
Subscribe to the channel for new opportunities! https://t.me/investproinmena
-----------------------"""


async def test_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Received /start command from {update.effective_user.first_name}")
    await update.message.reply_text("✅ Bot is working! /start command received.")

async def test_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Received text message: {update.message.text}")
    await update.message.reply_text(f"📝 You said: {update.message.text}")

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


async def format_job_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main function to format job posts"""
    job_post = update.message.text
    
    if not job_post.strip():
        await update.message.reply_text("Please send a job post to format! 📝")
        return

    await update.message.reply_text("🔍 Extracting job details... This may take a moment.")
    
    try:
        import asyncio
        from huggingface_hub import InferenceClient
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
        # In production, you'd want to use proper JSON parsing
        formatted_post = TELEGRAM_FORMAT_TEMPLATE.format(
    opportunitytype=data.get("opportunitytype", "Position"),
    target_group=data.get("target_group", "Level"),
    company=data.get("company", "Company"),
    location=data.get("location", "Location"),
    sector=data.get("sector", "Description"),
    requirements=data.get("requirements", "Requirements"),
    benefits=data.get("benefits", "Benefits"),
    link=data.get("link", "Link")
)

        
        # Send formatted post
        await update.message.reply_text(
            formatted_post + "\n\n" +
            f"#{data.get('location', 'Location').replace(',', '_').replace(' ', '_')} #{data.get('sector', 'Description').replace(',', '_').replace(' ', '_')} #{data.get('target_group', 'Target Group').replace(',', '_').replace(' ', '_')}",
            parse_mode='HTML'
        )
        
    except Exception as e:
        logging.error(f"Error processing job post: {e}")
        await update.message.reply_text(f"DEBUG ERROR:\n{str(e)}")
    

async def main():
    global application
    logging.info("Starting bot...")
    
    # Build the application
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("help", test_help))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), format_job_post))    
    
    # Initialize the application
    logging.info("Initializing application...")
    await application.initialize()
    
    logging.info("Bot is ready to receive messages")
    
    await application.start()
    print("PTB started (webhook mode).")
    await asyncio.Event().wait()


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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


