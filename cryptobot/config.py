"""
Configuration — all secrets loaded from environment variables
Copy .env.example to .env and fill in your keys
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── REQUIRED ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── OPTIONAL (improves data quality) ──────────────────────
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")   # Free tier works without this
LUNARCRUSH_API_KEY = os.getenv("LUNARCRUSH_API_KEY", "")

# ── API BASE URLS ──────────────────────────────────────────
BINANCE_BASE       = "https://api.binance.com/api/v3"
BINANCE_FUTURES    = "https://fapi.binance.com/fapi/v1"
COINGECKO_BASE     = "https://api.coingecko.com/api/v3"
FNG_URL            = "https://api.alternative.me/fng/"
POLYMARKET_BASE    = "https://gamma-api.polymarket.com"
DEXSCREENER_BASE   = "https://api.dexscreener.com/latest/dex"

# ── CLAUDE MODEL ───────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 2000

# ── TIMEOUTS ───────────────────────────────────────────────
HTTP_TIMEOUT = 10   # seconds per API call
POLY_POLL_INTERVAL = 900  # 15 minutes in seconds

# ── THRESHOLDS ─────────────────────────────────────────────
PRICE_MOVE_ALERT_PCT = 3.0   # Re-pull if price moves this % mid-session
POLY_SHIFT_ALERT_PCT = 15.0  # Flag Polymarket odds shift of this % in 24h
MIN_POLY_VOLUME_USD  = 10_000  # Ignore low-volume Polymarket markets

# Validate required keys on import
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN is not set in .env")
if not ANTHROPIC_API_KEY:
    raise ValueError("❌ ANTHROPIC_API_KEY is not set in .env")
