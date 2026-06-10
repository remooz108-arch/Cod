import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_MODE = os.getenv("ALPACA_MODE", "paper").lower()
PAPER = ALPACA_MODE == "paper"

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
RISK_PER_TRADE_USD = float(os.getenv("RISK_PER_TRADE_USD", "100"))
MAX_SHARES = int(os.getenv("MAX_SHARES", "50"))
TRADE_COOLDOWN = int(os.getenv("TRADE_COOLDOWN", "3600"))
LIVE_ORDERS = os.getenv("LIVE_ORDERS", "false").lower() == "true"

# Keywords — ALL three must appear in the same article to fire
REQUIRED_KEYWORDS = ["trump", "iran", "israel"]

# Tickers to trade when signal fires
# XLE = Energy ETF (oil/gas spikes on Middle East tension)
# GLD = Gold ETF (safe-haven flight)
SIGNAL_TICKERS = ["XLE", "GLD"]

# RSS feeds — no API key needed
RSS_FEEDS = [
    ("Reuters World",    "https://feeds.reuters.com/reuters/worldNews"),
    ("Reuters Politics", "https://feeds.reuters.com/Reuters/PoliticsNews"),
    ("BBC World",        "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera",       "https://www.aljazeera.com/xml/rss/all.xml"),
    ("AP Top News",      "https://rss.ap.org/feed/apf-topnews"),
    ("CNN World",        "http://rss.cnn.com/rss/cnn_world.rss"),
]

SEEN_ARTICLES_FILE = "seen_articles.json"
LOG_FILE = "signals.log"
