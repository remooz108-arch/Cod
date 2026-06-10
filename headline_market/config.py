import os
from dotenv import load_dotenv

load_dotenv()

TRIGGER_WORDS = [
    w.strip().lower()
    for w in os.getenv("TRIGGER_WORDS", "trump,iran,israel").split(",")
    if w.strip()
]

MARKET_DURATION_DAYS = int(os.getenv("MARKET_DURATION_DAYS", "7"))
POLL_INTERVAL        = int(os.getenv("POLL_INTERVAL", "120"))

RSS_FEEDS = [
    ("Reuters World",    "https://feeds.reuters.com/reuters/worldNews"),
    ("Reuters Politics", "https://feeds.reuters.com/Reuters/PoliticsNews"),
    ("BBC World",        "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera",       "https://www.aljazeera.com/xml/rss/all.xml"),
    ("AP Top News",      "https://rss.ap.org/feed/apf-topnews"),
    ("CNN World",        "http://rss.cnn.com/rss/cnn_world.rss"),
]

MARKET_FILE = "market.json"
LOG_FILE    = "market.log"

# ── Polymarket betting (optional) ────────────────────────────────────────────
POLY_PRIVATE_KEY    = os.getenv("POLY_PRIVATE_KEY", "")
POLY_FUNDER_ADDRESS = os.getenv("POLY_FUNDER_ADDRESS", "")
CLOB_HOST           = "https://clob.polymarket.com"
GAMMA_HOST          = "https://gamma-api.polymarket.com"
CHAIN_ID            = 137

# USDC to bet per matching market when signal fires
BET_AMOUNT_USDC = float(os.getenv("BET_AMOUNT_USDC", "10"))

# Only bet on markets priced between these bounds (avoid near-certain markets)
MIN_YES_PRICE = float(os.getenv("MIN_YES_PRICE", "0.05"))
MAX_YES_PRICE = float(os.getenv("MAX_YES_PRICE", "0.80"))

# Set to "true" to actually submit orders, "false" to print only
LIVE_BETTING = os.getenv("LIVE_BETTING", "false").lower() == "true"

# Polymarket search terms used when signal fires
POLY_SEARCH_TERMS = [
    "iran israel",
    "israel iran attack",
    "iran strike",
    "israel attack iran",
    "trump iran",
    "middle east war",
]
