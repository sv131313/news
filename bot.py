import os
import csv
import io
import requests
import json
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
telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

if os.getenv('INSTRUCTIONS'):
    instructions = os.getenv('INSTRUCTIONS')
else:
    with open('.instructions', 'r') as file:
        instructions = file.read()

# Get feed URLs from environment variable
feed_urls_env = os.getenv('FEED_URLS')
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

def filter_entries_last_24_hours(entries):
    filtered_entries = []
    now = datetime.now(timezone(timedelta(hours=3)))  # Current time in GMT+3
    last_24_hours = now - timedelta(hours=24)

    for entry in entries:
        if hasattr(entry, 'published_parsed'):
            published = datetime.fromtimestamp(
                datetime(*entry.published_parsed[:6]).timestamp(),
                tz=timezone.utc
            ).astimezone(timezone(timedelta(hours=3)))  # Convert to GMT+3
            if published >= last_24_hours:
                filtered_entries.append(entry)

    return filtered_entries

def create_csv_data(entries):
    output = io.StringIO()
    csv_writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    csv_writer.writerow(['Date', 'Title', 'Description', 'Link'])

    for entry in entries:
        published = datetime.fromtimestamp(
            datetime(*entry.published_parsed[:6]).timestamp(),
            tz=timezone.utc
        ).astimezone(timezone(timedelta(hours=3)))  # Convert to GMT+3
        title = BeautifulSoup(entry.title, 'html.parser').get_text()  # Remove HTML tags from title
        description = BeautifulSoup(entry.summary, 'html.parser').get_text()  # Remove HTML tags from description
        csv_writer.writerow([published.strftime('%Y-%m-%d %H:%M:%S'), title, description, entry.link])

    return output.getvalue()

import requests
import json

def summarize(user_message):

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {openai_api_key}"
    }
    
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": f"{instructions}. \n\n NEWS in CSV format: {user_message}"}
        ],
        "temperature": 0.9
    }
    
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        data=json.dumps(data)
    )
    
    if response.status_code == 200:
        response_json = response.json()
        summary = response_json['choices'][0]['message']['content']
        return summary
    else:
        return f"Error: {response.status_code} - {response.text}"


async def get_response(thread_id):
    messages = await client.beta.threads.messages.list(thread_id=thread_id)
    message_content = messages.data[0].content[0].text

    # Remove annotations
    annotations = message_content.annotations
    for annotation in annotations:
        message_content.value = message_content.value.replace(annotation.text, '')

    response_message = message_content.value
    return response_message


def split_message(text, max_length=4000):
    """Split a message into chunks of specified maximum length."""
    out_messages = []
    current_message = ""
    
    # Split the text into paragraphs
    paragraphs = text.split('\n')
    
    for paragraph in paragraphs:
        # If adding this paragraph would exceed max_length
        if len(current_message) + len(paragraph) + 1 > max_length:
            # Save current message and start a new one
            if current_message:
                out_messages.append(current_message.strip())
            current_message = paragraph + '\n'
        else:
            # Add paragraph to current message
            current_message += paragraph + '\n'
    
    # Add the last message if it's not empty
    if current_message:
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

    filtered_entries = filter_entries_last_24_hours(entries)

    if not filtered_entries:
       print("No relevant articles from the last 24 hours.")
       return

    csv_data = create_csv_data(filtered_entries)

    summary = summarize(csv_data)

    if summary:
        await send_message(summary)
    else:
        print("No relevant summaries were generated.")

if __name__ == "__main__":
     asyncio.run(main())
