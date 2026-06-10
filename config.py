import os
from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
CHAIN_ID = int(os.getenv("CHAIN_ID", "137"))
CLOB_HOST = os.getenv("CLOB_HOST", "https://clob.polymarket.com")

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"

# Batumi, Georgia coordinates
BATUMI_LAT = 41.6168
BATUMI_LON = 41.6367
BATUMI_CITY = "Batumi,GE"

MAX_BET_USDC = float(os.getenv("MAX_BET_USDC", "10"))
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.05"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

GAMMA_API = "https://gamma-api.polymarket.com"
