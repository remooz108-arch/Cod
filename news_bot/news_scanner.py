"""
Fetch articles from RSS feeds and optionally NewsAPI.
Returns a flat list of Article dicts: {id, title, body, url, source, published}.
"""

from dataclasses import dataclass
from typing import Optional
import hashlib
import requests
import feedparser
import config


@dataclass
class Article:
    id: str          # stable hash of URL or GUID
    title: str
    body: str        # summary / description
    url: str
    source: str
    published: str


def _make_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _fetch_rss(name: str, url: str) -> list[Article]:
    try:
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries:
            link = entry.get("link", "")
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            published = entry.get("published", "") or entry.get("updated", "")
            articles.append(Article(
                id=_make_id(link or title),
                title=title,
                body=summary,
                url=link,
                source=name,
                published=published,
            ))
        return articles
    except Exception as exc:
        print(f"  [warn] RSS fetch failed ({name}): {exc}")
        return []


def _fetch_newsapi(api_key: str) -> list[Article]:
    """Pull top headlines mentioning geopolitical topics from NewsAPI."""
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={
                "apiKey": api_key,
                "language": "en",
                "category": "general",
                "pageSize": 50,
            },
            timeout=10,
        )
        resp.raise_for_status()
        articles = []
        for item in resp.json().get("articles", []):
            url = item.get("url", "")
            articles.append(Article(
                id=_make_id(url),
                title=item.get("title", "") or "",
                body=(item.get("description", "") or "") + " " + (item.get("content", "") or ""),
                url=url,
                source=item.get("source", {}).get("name", "NewsAPI"),
                published=item.get("publishedAt", ""),
            ))
        return articles
    except Exception as exc:
        print(f"  [warn] NewsAPI fetch failed: {exc}")
        return []


def fetch_all_articles() -> list[Article]:
    articles: list[Article] = []

    for name, url in config.RSS_FEEDS:
        batch = _fetch_rss(name, url)
        articles.extend(batch)

    if config.NEWS_API_KEY:
        articles.extend(_fetch_newsapi(config.NEWS_API_KEY))

    # Deduplicate by id
    seen: set[str] = set()
    unique: list[Article] = []
    for a in articles:
        if a.id not in seen:
            seen.add(a.id)
            unique.append(a)

    return unique
