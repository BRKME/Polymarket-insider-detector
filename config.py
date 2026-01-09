# Configuration for Polymarket Insider Detector

# API Endpoints
GAMMA_API_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"

# Data Collection
TRADES_LIMIT = 500  # Maximum trades per page
MAX_PAGES = 20      # Maximum pages to fetch
MINUTES_BACK = 30   # Look back 30 minutes (was 10 - compensates for unreliable GitHub Actions cron)

# Rate Limiting
PAGE_DELAY = 0.2      # Delay between pages (200ms)
REQUEST_DELAY = 0.1   # Delay between requests (100ms)

# Retry Configuration
MAX_RETRIES = 3           # Maximum retry attempts
RETRY_DELAY = 2           # Base delay between retries (seconds)
RETRY_BACKOFF = 2         # Exponential backoff multiplier

# Rate Limit Handling
RATE_LIMIT_RETRY_DELAY = 60    # Wait 60s when rate limited
RATE_LIMIT_MAX_RETRIES = 2     # Max rate limit retries

# Detection Thresholds
MIN_BET_SIZE = 10000          # Minimum bet size ($10,000)
SUSPICION_THRESHOLD = 80      # Score threshold for alerts (0-110)

# Telegram Configuration (set via environment variables)
# TELEGRAM_BOT_TOKEN = "your_token_here"
# TELEGRAM_CHAT_ID = "your_chat_id_here"
