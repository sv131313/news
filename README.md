# News Telegram Bot

This script collects news from RSS feeds, summarizes the content with the OpenAI Responses API and sends the result to a Telegram group.

## Installation
1. Clone this repository and navigate into it.
2. (Optional) Create a virtual environment.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Creating a Telegram bot and group
1. In Telegram, talk to **@BotFather** and create a new bot. Copy the token.
2. Create a new Telegram group or choose an existing one.
3. Add the bot to the group. Make sure it has permission to send messages.
4. Obtain the group chat ID – for example by inviting **@userinfobot** to the group and asking for info.

## Configuration
Create a `.env` file in the project root and fill it with the following variables:
```env
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
TELEGRAM_BOT_TOKEN=telegram_bot_token
TELEGRAM_CHAT_ID=group_chat_id
FEED_URLS=https://news.example/rss,https://another.example/rss
INSTRUCTIONS=Summary instructions here
```
You can also place the summary instructions in a `.instructions` file instead of the `INSTRUCTIONS` variable.

## Usage
Run the script:
```bash
python bot.py
```
The script fetches entries from the specified RSS feeds, keeps only items published within the last 24 hours.
It converts them into CSV, sends the data to the OpenAI model to generate a summary, and finally posts the summary to the configured Telegram group.

