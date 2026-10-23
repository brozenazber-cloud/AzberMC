AzberMc - Telegram Minecraft rank shop bot

Files:
- bot.py: bot source.
- main.py: same source for hosts that expect main.py.
- requirements.txt: dependencies.

Setup:
1. Set environment variables required by the source:
   MAIN_BOT_TOKEN
   ADMIN_BOT_TOKEN
   ADMIN_IDS
   CARD_NUMBER
   Optional: CARD_NAME, SUPPORT_USERNAME, SERVER_ADDRESS, DB_PATH
2. Install dependencies: pip install -r requirements.txt
3. Run: python bot.py (or python main.py)

Keep tokens private. Ensure the hosting plan supports persistent long-running Python processes,
environment variables, and persistent storage for the SQLite database.
