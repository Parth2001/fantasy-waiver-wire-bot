"""
Thin wrapper around ESPN's public (unofficial, no API key needed) NFL news
feed. Sleeper's own API only exposes a `news_updated` *timestamp* per player
-- no headline or article text -- so it can't tell "suspension rumor" apart
from "minor depth chart note." This feed gives real headlines/descriptions,
plus ESPN already tags each article with the athletes it's about, which is a
much more reliable signal than trying to string-match player names ourselves.
"""
import requests

NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"


def get_recent_news(limit=50):
    """Returns a list of recent NFL articles: each has id, headline,
    description, published, and categories (some of type 'athlete' with the
    player's real name in 'description')."""
    resp = requests.get(NEWS_URL, params={"limit": limit}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("articles", [])


def article_athlete_names(article):
    """Names of players ESPN explicitly tagged this article with."""
    names = []
    for cat in article.get("categories", []):
        if cat.get("type") == "athlete" and cat.get("description"):
            names.append(cat["description"])
    return names
