"""Vancouver News & Events Feed Router."""

import os
import urllib.request
import xml.etree.ElementTree as ET
from typing import List

from fastapi import APIRouter
from app.models import NewsItemResponse

router = APIRouter(prefix="/api/news", tags=["news"])

SEED_NEWS: List[dict] = [
    {
        "title": "Granville Island Summer Night Market & Artisan Fair Returns",
        "summary": "Enjoy local food trucks, live outdoor jazz performances, and handcrafted local arts by False Creek waterfront every weekend.",
        "source": "Daily Hive Vancouver",
        "url": "https://dailyhive.com/vancouver",
        "category": "#Festival",
        "published_at": "Today",
    },
    {
        "title": "TransLink SeaBus Increases Weekend Service Frequency for Summer Crowds",
        "summary": "SeaBus sailings between Waterfront Station and Lonsdale Quay will run every 10 minutes during peak afternoon hours.",
        "source": "TransLink News",
        "url": "https://www.translink.ca",
        "category": "#Transit",
        "published_at": "Today",
    },
    {
        "title": "Kitsilano Beach Outdoor Sunset Movie Nights Announced for August",
        "summary": "Free outdoor family screenings kick off at Kitsilano Beach Park with big screen films right by the Pacific ocean.",
        "source": "CBC Vancouver",
        "url": "https://www.cbc.ca/news/canada/british-columbia",
        "category": "#Event",
        "published_at": "Yesterday",
    },
    {
        "title": "Capilano Suspension Bridge Launches Canyon Starlight Summer Evening Walk",
        "summary": "Immersive light installations and rainforest canopy walks open for visitors exploring North Vancouver.",
        "source": "Vancouver Is Awesome",
        "url": "https://www.vancouverisawesome.com",
        "category": "#Outdoor",
        "published_at": "2 days ago",
    },
    {
        "title": "Metro Vancouver Coastal Air Quality & Microclimate Advisory Update",
        "summary": "Favorable coastal ocean breezes bring clean Pacific air and clear sunny skies across Downtown and the North Shore mountains.",
        "source": "Weather BC",
        "url": "https://open-meteo.com",
        "category": "#Weather",
        "published_at": "Today",
    },
]


import time

NEWS_CACHE: dict = {"timestamp": 0.0, "data": []}
CACHE_TTL_SECONDS = 600.0  # 10 minutes cache TTL


@router.get("", response_model=List[NewsItemResponse])
def get_vancouver_news():
    """Returns Vancouver live news, events, and transit updates with RSS fallback and 10-min cache."""
    now = time.time()
    if NEWS_CACHE["data"] and (now - NEWS_CACHE["timestamp"] < CACHE_TTL_SECONDS):
        return NEWS_CACHE["data"]

    if os.environ.get("WEATHER_OFFLINE", "").strip().lower() in {"1", "true", "yes"}:
        res = [NewsItemResponse(**item) for item in SEED_NEWS]
        NEWS_CACHE["timestamp"] = now
        NEWS_CACHE["data"] = res
        return res

    try:
        req = urllib.request.Request(
            "https://rss.cbc.ca/lineup/canada-britishcolumbia.xml",
            headers={"User-Agent": "Mozilla/5.0 (VancouverExplorer/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=3.0) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            channel = root.find("channel")
            items = []
            if channel is not None:
                for item in channel.findall("item")[:5]:
                    title = item.findtext("title", "Vancouver Update")
                    link = item.findtext("link", "https://www.cbc.ca/news/canada/british-columbia")
                    pub = item.findtext("pubDate", "Today")
                    desc = item.findtext("description", "Latest Vancouver local news update.")
                    clean_desc = desc.split("<")[0].strip() if "<" in desc else desc[:120]
                    items.append(
                        {
                            "title": title,
                            "summary": clean_desc or "Latest Vancouver local updates and events.",
                            "source": "CBC Vancouver",
                            "url": link,
                            "category": "#LocalNews",
                            "published_at": pub[:16] if len(pub) > 16 else pub,
                        }
                    )
            if items:
                res = [NewsItemResponse(**i) for i in items]
                NEWS_CACHE["timestamp"] = now
                NEWS_CACHE["data"] = res
                return res
    except Exception:
        pass

    fallback_res = [NewsItemResponse(**item) for item in SEED_NEWS]
    NEWS_CACHE["timestamp"] = now
    NEWS_CACHE["data"] = fallback_res
    return fallback_res

