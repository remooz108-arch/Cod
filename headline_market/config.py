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
