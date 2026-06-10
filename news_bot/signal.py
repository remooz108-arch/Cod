"""
Keyword signal detection.

An article fires a signal when ALL required keywords appear
in its combined title + body text (case-insensitive).
"""

import re
from news_scanner import Article
import config


def _full_text(article: Article) -> str:
    return f"{article.title} {article.body}".lower()


def matches_all_keywords(article: Article) -> bool:
    text = _full_text(article)
    return all(
        bool(re.search(r'\b' + re.escape(kw) + r'\b', text))
        for kw in config.REQUIRED_KEYWORDS
    )


def find_signals(articles: list[Article]) -> list[Article]:
    return [a for a in articles if matches_all_keywords(a)]


def highlight(article: Article) -> str:
    """Return a coloured-terminal summary of a matched article."""
    kws = ", ".join(f'"{k}"' for k in config.REQUIRED_KEYWORDS)
    return (
        f"  SOURCE : {article.source}\n"
        f"  TITLE  : {article.title}\n"
        f"  URL    : {article.url}\n"
        f"  POSTED : {article.published}\n"
        f"  SIGNAL : all keywords matched ({kws})\n"
    )
