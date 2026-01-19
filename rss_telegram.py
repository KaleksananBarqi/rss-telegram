#!/usr/bin/env python3
import time
import json
import logging
import feedparser
import asyncio
from telegram import Bot
from telegram.constants import ParseMode
import re
import html
import config

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def strip_html(html_content: str) -> str:
    """Convert HTML to plain text by removing tags and unescaping entities."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html_content)
    # Unescape HTML entities and normalize whitespace
    text = html.unescape(text)
    return ' '.join(text.split())


def load_feeds():
    """Load RSS feeds from configuration file."""
    try:
        with open(config.FEEDS_FILE, 'r') as f:
            feeds = [line.strip() for line in f.readlines() if line.strip() and not line.strip().startswith('#')]
            logger.info(f"Loaded {len(feeds)} feeds from {config.FEEDS_FILE}")
            return feeds
    except FileNotFoundError:
        logger.warning(f"Feed file {config.FEEDS_FILE} not found. Creating empty file...")
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(config.FEEDS_FILE), exist_ok=True)
        except OSError:
            pass # Ignore if simple filename
            
        with open(config.FEEDS_FILE, 'w') as f:
            f.write("# Add your RSS feeds here, one per line\n")
        return []
    except Exception as e:
        logger.error(f"Error loading feeds: {e}")
        return []


def load_sent_items():
    """Load history of already sent articles."""
    try:
        with open(config.HISTORY_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_sent_items(sent_items):
    """Save history of sent articles."""
    with open(config.HISTORY_FILE, 'w') as f:
        json.dump(sent_items, f, indent=4)

async def send_telegram_message(bot, chat_id, message, topic_id=None):
    """Send a Telegram message asynchronously."""
    try:
        kwargs = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': ParseMode.MARKDOWN,
            'disable_notification': config.DISABLE_NOTIFICATION
        }
        if topic_id:
            kwargs['message_thread_id'] = int(topic_id)

        await bot.send_message(**kwargs)
        return True
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        return False

def extract_image(entry):
    """Extract image URL from RSS entry."""
    # 1. Try media_content (standard RSS Media MRSS)
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            if media.get('type', '').startswith('image/') or media.get('medium') == 'image':
                return media.get('url')

    # 2. Try enclosures
    if hasattr(entry, 'enclosures'):
        for enclosure in entry.enclosures:
            if enclosure.get('type', '').startswith('image/'):
                return enclosure.get('href')

    # 3. Try media_thumbnail
    if hasattr(entry, 'media_thumbnail') and len(entry.media_thumbnail) > 0:
        return entry.media_thumbnail[0].get('url')

    # 4. Parsing description for <img src="...">
    description = getattr(entry, 'description', '') or getattr(entry, 'summary', '')
    if description:
        match = re.search(r'<img[^>]+src=["\'](.*?)["\']', description, re.IGNORECASE)
        if match:
            return match.group(1)

    # 5. Try content / content:encoded
    if hasattr(entry, 'content'):
        for content in entry.content:
            value = content.get('value', '')
            match = re.search(r'<img[^>]+src=["\'](.*?)["\']', value, re.IGNORECASE)
            if match:
                return match.group(1)

    return None

async def send_single_article(bot, chat_id, entry, feed_title, topic_id=None):
    """Send a single article with image if available."""
    title = entry.title if hasattr(entry, 'title') else "No title"
    link = entry.link if hasattr(entry, 'link') else ""
    
    # Clean description
    raw_desc = getattr(entry, 'description', '') or getattr(entry, 'summary', '')
    description = strip_html(raw_desc) if config.INCLUDE_DESCRIPTION else ""

    # Truncate description to fit Telegram caption limit (1024 chars total)
    # Reserve ~200 chars for title, feed name, link, and formatting
    max_desc_len = 800
    if len(description) > max_desc_len:
        description = description[:max_desc_len-3] + "..."

    # Format Message
    message_text = f"• [{title}]({link})\n_{feed_title}_"
    if description:
        message_text += f"\n\n{description}"

    image_url = extract_image(entry)
    
    kwargs = {
        'chat_id': chat_id,
        'parse_mode': ParseMode.MARKDOWN,
        'disable_notification': config.DISABLE_NOTIFICATION,
    }
    if topic_id:
        kwargs['message_thread_id'] = int(topic_id)

    try:
        if image_url:
            await bot.send_photo(photo=image_url, caption=message_text, **kwargs)
        else:
            await bot.send_message(text=message_text, disable_web_page_preview=False, **kwargs)
        return True
    except Exception as e:
        logger.error(f"Error sending article (Image: {image_url}): {e}")
        # Fallback to text if image fails
        if image_url:
            try:
                await bot.send_message(text=message_text, disable_web_page_preview=False, **kwargs)
                return True
            except Exception as e2:
                logger.error(f"Error sending fallback text: {e2}")
        return False

async def check_feeds(bot):
    """Check RSS feeds for new articles."""
    sent_items = load_sent_items()
    feeds = load_feeds()

    if not feeds:
        logger.warning("No feeds to check. Add feeds to the configuration file.")
        return sent_items

    for feed_url in feeds:
        if not feed_url.strip():
            continue

        logger.info(f"Checking feed: {feed_url}")

        try:
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                logger.warning(f"No entries found in feed: {feed_url}")
                continue

            feed_title = feed.feed.title if hasattr(feed.feed, 'title') else feed_url
            sent_items.setdefault(feed_url, [])
            
            # Identify new entries
            new_entries = []
            for entry in feed.entries:
                entry_id = entry.id if hasattr(entry, 'id') else entry.link
                if entry_id not in sent_items[feed_url]:
                    new_entries.append(entry)

            # Process oldest new entries first
            for entry in reversed(new_entries):
                entry_id = entry.id if hasattr(entry, 'id') else entry.link
                
                logger.info(f"New entry found: {entry.get('title', 'No title')}")
                success = await send_single_article(bot, config.TELEGRAM_CHAT_ID, entry, feed_title, config.TELEGRAM_TOPIC_ID)
                
                if success:
                    sent_items[feed_url].append(entry_id)
                    save_sent_items(sent_items)
                    await asyncio.sleep(2)  # Delay between messages to avoid rate limits

        except Exception as e:
            logger.error(f"Error checking feed {feed_url}: {e}")

    return sent_items

async def main_async():
    logger.info("Starting RSS feed monitoring")
    logger.info(f"Configuration: INCLUDE_DESCRIPTION={config.INCLUDE_DESCRIPTION}, DISABLE_NOTIFICATION={config.DISABLE_NOTIFICATION}")

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("Missing environment variables. Make sure to set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    await send_telegram_message(
        bot, config.TELEGRAM_CHAT_ID,
        "🤖 *RSS Monitoring Bot started!*\nActive feed monitoring. Configuration loaded from file.",
        config.TELEGRAM_TOPIC_ID
    )

    while True:
        sent_items = await check_feeds(bot)
        save_sent_items(sent_items)
        logger.info(f"Next check in {config.CHECK_INTERVAL} seconds")
        await asyncio.sleep(config.CHECK_INTERVAL)


def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()