import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Secret Configuration (Loaded from .env) ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_TOPIC_ID = os.getenv('TELEGRAM_TOPIC_ID')

# --- App Configuration ---
# Interval pemeriksaan feed dalam detik (Default: 3600 = 1 jam)
CHECK_INTERVAL = 3600

# Path file feeds
FEEDS_FILE = 'data/feeds.txt'

# Path file history
HISTORY_FILE = 'data/sent_items.json'
MAX_HISTORY_ITEMS = 200

# Format Pesan
INCLUDE_DESCRIPTION = False
DISABLE_NOTIFICATION = False

# Batas karakter pesan Telegram
MAX_MESSAGE_LENGTH = 4096
