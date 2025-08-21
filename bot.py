import os
import csv
import io
import requests
import json
import re
import asyncio
from telegram.ext import Updater
from telegram import Update, Bot
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import feedparser
from bs4 import BeautifulSoup

# Load environment variables from .env file
load_dotenv()

# API keys and tokens
openai_api_key = os.getenv('OPENAI_API_KEY')
openai_model = os.getenv('OPENAI_MODEL')
telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

if os.getenv('INSTRUCTIONS'):
    instructions = os.getenv('INSTRUCTIONS')
else:
    with open('.instructions', 'r') as file:
        instructions = file.read()

# Get feed URLs from environment variable
feed_urls_env = os.getenv('FEED_URLS')
print(feed_urls_env)
if feed_urls_env:
    feed_urls = [url.strip() for url in feed_urls_env.split(',')]
else:
    feed_urls = []

import time

def fetch_feeds(feed_urls):
    entries = []
    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            entries.extend(feed.entries)
        except Exception as e:
            print(f"Error fetching {url}: {e}")
    return entries


def parse_published(entry):
    """Return publication datetime in GMT+3 timezone."""
    published_dt = None

    if getattr(entry, "published_parsed", None):
        published_dt = datetime(
            *entry.published_parsed[:6], tzinfo=timezone.utc
        )
    elif getattr(entry, "published", None):
        try:
            published_dt = datetime.strptime(
                entry.published.strip(), "%a, %m/%d/%Y - %H:%M"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    if published_dt is None:
        return None

    return published_dt.astimezone(timezone(timedelta(hours=3)))

def filter_entries_last_24_hours(entries):
    filtered_entries = []
    now = datetime.now(timezone(timedelta(hours=3)))  # Current time in GMT+3
    last_24_hours = now - timedelta(hours=24)

    for entry in entries:
        published = parse_published(entry)
        if published and published >= last_24_hours:
            filtered_entries.append(entry)

    return filtered_entries

def create_csv_data(entries):
    output = io.StringIO()
    csv_writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    csv_writer.writerow(['Date', 'Title', 'Description', 'Link'])

    for entry in entries:
        published = parse_published(entry)
        if not published:
            continue
        title = BeautifulSoup(entry.title, 'html.parser').get_text()  # Remove HTML tags from title
        description = BeautifulSoup(entry.summary, 'html.parser').get_text()  # Remove HTML tags from description
        csv_writer.writerow([published.strftime('%Y-%m-%d %H:%M:%S'), title, description, entry.link])

    return output.getvalue()

def _extract_text(response_json: dict) -> str:
    # 1) Responses API: SDK has "output_text", raw JSON has array "output"
    if "output_text" in response_json and response_json["output_text"]:
        return response_json["output_text"]
    if "output" in response_json and isinstance(response_json["output"], list):
        texts = []
        for item in response_json["output"]:
            # typical item from Responses API
            if item.get("type") == "output_text" and "text" in item:
                texts.append(item["text"])
            # sometimes text is nested within message->content
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text" and "text" in c:
                        texts.append(c["text"])
        if texts:
            return "".join(texts)
    # 2) Chat Completions fallback
    if "choices" in response_json:
        msg = response_json["choices"][0].get("message", {})
        if "content" in msg:
            return msg["content"]
    return ""


def summarize(
    user_message: str,
    instructions: str,
    openai_api_key: str,
    model: str = "gpt-5",
    temperature: float | None = None,
    top_p: float | None = None,
    extra: dict | None = None,
) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {openai_api_key}",
    }

    # Minimal payload compatible with Responses API
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": f"NEWS in CSV format:\n{user_message}"},
        ],
    }

    # Add parameters ONLY if explicitly provided
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if top_p is not None:
        payload["top_p"] = float(top_p)
    if extra:
        payload.update(extra)

    def _post(p):
        return requests.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            data=json.dumps(p),
        )

    resp = _post(payload)
    if resp.status_code == 200:
        return _extract_text(resp.json())

    # Remove unsupported args and retry once
    if resp.status_code in (400, 422):
        body = resp.text
        bad_fields = set(re.findall(r"Unrecognized request argument: (\w+)", body))
        if bad_fields:
            safe_payload = {k: v for k, v in payload.items() if k not in bad_fields}
            resp2 = _post(safe_payload)
            if resp2.status_code == 200:
                return _extract_text(resp2.json())
            return f"Error after retry: {resp2.status_code} - {resp2.text}"

    return f"Error: {resp.status_code} - {resp.text}"

def split_message(text, max_length=4000):
    """Split a message into chunks of specified maximum length without breaking Markdown formatting."""
    out_messages = []
    current_message = ""
    
    # Regular expression to detect Markdown entities
    markdown_entity_pattern = r"(_|\*|`|~|\[|\])"
    
    paragraphs = text.split('\n')
    open_entities = []
    
    for paragraph in paragraphs:
        # If adding this paragraph would exceed max_length
        if len(current_message) + len(paragraph) + 1 > max_length:
            # Make sure to close any open Markdown entities
            for entity in open_entities:
                current_message += entity
            
            out_messages.append(current_message.strip())
            current_message = paragraph + '\n'
            open_entities = []  # Reset open entities after a split
        else:
            # Add paragraph to current message
            current_message += paragraph + '\n'
            # Track open Markdown entities
            for match in re.finditer(markdown_entity_pattern, paragraph):
                entity = match.group()
                if entity in open_entities:
                    open_entities.remove(entity)
                else:
                    open_entities.append(entity)
    
    # Add the last message if it's not empty
    if current_message:
        # Close any open Markdown entities
        for entity in open_entities:
            current_message += entity
        out_messages.append(current_message.strip())
    
    return out_messages


async def send_message(text):
    print(text)
    bot = Bot(token=telegram_bot_token)
    try:
        message_chunks = split_message(text)
        
        # Send each chunk with a slight delay to maintain order
        for chunk in message_chunks:
            print(chunk)
            await bot.send_message(
                chat_id=telegram_chat_id,
                text=chunk,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            # Add a small delay between messages to maintain order
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f"Error sending message: {e}")


async def main():
    entries = fetch_feeds(feed_urls)

    print("Found:", len(entries), "entries" )

    filtered_entries = filter_entries_last_24_hours(entries)

    if not filtered_entries:
       print("No relevant articles from the last 24 hours.")
       return

    csv_data = create_csv_data(filtered_entries)

    summary = summarize(
        csv_data,
        instructions,
        openai_api_key,
        model=openai_model or "gpt-5",
    )

    if summary:
        await send_message(summary)
    else:
        print("No relevant summaries were generated.")

if __name__ == "__main__":
     asyncio.run(main())
