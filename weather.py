"""Fetch weather data for Batumi, Georgia via OpenWeatherMap."""

import requests
from dataclasses import dataclass
from typing import Optional
import config


@dataclass
class WeatherSnapshot:
    city: str
    temp_c: float
    humidity: int
    description: str
    # Probability of precipitation 0-100
    rain_probability: int
    # mm of rain expected in next 24 hours
    rain_mm_24h: float
    # Raw forecast rain probabilities for each 3-hour slot (up to 8 slots = 24h)
    hourly_pop: list[float]


def _get_current(api_key: str) -> dict:
    resp = requests.get(
        f"{config.WEATHER_API_BASE}/weather",
        params={"q": config.BATUMI_CITY, "appid": api_key, "units": "metric"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _get_forecast(api_key: str) -> dict:
    resp = requests.get(
        f"{config.WEATHER_API_BASE}/forecast",
        params={"q": config.BATUMI_CITY, "appid": api_key, "units": "metric", "cnt": 8},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_weather(api_key: Optional[str] = None) -> WeatherSnapshot:
    key = api_key or config.WEATHER_API_KEY
    if not key:
        raise ValueError("WEATHER_API_KEY is not set")

    current = _get_current(key)
    forecast = _get_forecast(key)

    slots = forecast.get("list", [])
    hourly_pop = [slot.get("pop", 0) * 100 for slot in slots]

    # Highest probability of precipitation across the next 24h
    max_pop = max(hourly_pop) if hourly_pop else 0

    # Accumulated rain mm across next 24h
    rain_mm = sum(
        slot.get("rain", {}).get("3h", 0) for slot in slots
    )

    return WeatherSnapshot(
        city=current.get("name", "Batumi"),
        temp_c=current["main"]["temp"],
        humidity=current["main"]["humidity"],
        description=current["weather"][0]["description"],
        rain_probability=round(max_pop),
        rain_mm_24h=round(rain_mm, 2),
        hourly_pop=hourly_pop,
    )


def summarise(ws: WeatherSnapshot) -> str:
    lines = [
        f"Location : {ws.city}, Georgia",
        f"Conditions: {ws.description}  {ws.temp_c:.1f}°C  {ws.humidity}% humidity",
        f"Rain prob : {ws.rain_probability}% (next 24 h)",
        f"Rain total: {ws.rain_mm_24h} mm expected",
        f"Hourly PoP: {[f'{p:.0f}%' for p in ws.hourly_pop]}",
    ]
    return "\n".join(lines)
