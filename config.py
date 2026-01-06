import os

GAMMA_API_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"

MIN_BET_SIZE = 10000        # $10k порог правильный для 30-минутных интервалов
ALERT_THRESHOLD = 80        # Строгий порог для качественных алертов
NEW_WALLET_DAYS_HIGH = 3
NEW_WALLET_DAYS_LOW = 7
LOW_ACTIVITY_THRESHOLD = 5
LOW_ODDS_THRESHOLD = 0.10   # Ставки с odds < 10%
TIME_TO_RESOLVE_HOURS = 24

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

SCORES = {
    "wallet_age_high": 40,
    "wallet_age_low": 20,
    "against_trend": 25,
    "large_bet": 20,
    "timing": 15,
    "low_activity": 10
}

REQUEST_DELAY = 0.5
