import os
from dotenv import load_dotenv

load_dotenv()

# The three words that must ALL appear in a single headline to fire
TRIGGER_WORDS = ["trump", "iran", "israel"]

# RSS feeds — title-only matching (headlines, not full articles)
RSS_FEEDS = [
    ("Reuters World",    "https://feeds.reuters.com/reuters/worldNews"),
    ("Reuters Politics", "https://feeds.reuters.com/Reuters/PoliticsNews"),
    ("BBC World",        "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera",       "https://www.aljazeera.com/xml/rss/all.xml"),
    ("AP Top News",      "https://rss.ap.org/feed/apf-topnews"),
    ("CNN World",        "http://rss.cnn.com/rss/cnn_world.rss"),
]

# Polymarket
POLY_PRIVATE_KEY    = os.getenv("POLY_PRIVATE_KEY", "")
POLY_FUNDER_ADDRESS = os.getenv("POLY_FUNDER_ADDRESS", "")
CLOB_HOST           = "https://clob.polymarket.com"
GAMMA_HOST          = "https://gamma-api.polymarket.com"
CHAIN_ID            = 137

BET_AMOUNT_USDC = float(os.getenv("BET_AMOUNT_USDC", "10"))
POLL_INTERVAL   = int(os.getenv("POLL_INTERVAL", "120"))
LIVE_BETTING    = os.getenv("LIVE_BETTING", "false").lower() == "true"

# Polymarket keyword search terms used to find relevant markets when signal fires
_extra = os.getenv("MARKET_KEYWORDS", "war,attack,strike,conflict,military")
MARKET_SEARCH_TERMS = ["israel iran", "iran israel", "iran attack"] + [
    k.strip() for k in _extra.split(",") if k.strip()
]

SEEN_FILE   = "seen_headlines.json"
SIGNALS_LOG = "signals.log"
