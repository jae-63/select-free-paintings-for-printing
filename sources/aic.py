"""
sources/aic.py

Client for the Art Institute of Chicago (AIC) Open Access API.
No API key needed for read-only access.
All parameters come from config.py.

Docs: https://api.artic.edu/docs/
IIIF: https://www.artic.edu/iiif/2/{image_id}/full/full/0/default.jpg
"""

import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

BASE_URL  = "https://api.artic.edu/api/v1"
IIIF_BASE = "https://www.artic.edu/iiif/2"

# Fields to request from the AIC API
FIELDS = [
    "id", "title", "artist_display", "date_display",
    "medium_display", "dimensions", "image_id",
    "is_public_domain", "artwork_type_title",
    "style_title", "classification_title",
    "department_title", "place_of_origin",
    "description", "thumbnail", "api_link",
]

# Queries to run against the AIC full-text search
LANDSCAPE_QUERIES = [
    "watercolor landscape",
    "gouache landscape",
    "watercolour landscape",
    "oil on canvas landscape",
    "oil on panel landscape",
    "seascape watercolor",
    "landscape watercolor paper",
    "river landscape painting",
    "coastal landscape",
    "mountain landscape watercolor",
    "pastoral landscape oil",
    "atmospheric landscape",
    "nocturne landscape oil",
    "harbor watercolor",
    "valley landscape",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


def make_image_url(image_id: str, size: str = "full") -> str:
    """
    Build a IIIF image URL.
      size='full'  → original full resolution
      size='843,'  → 843px wide (AIC resizes server-side)
    """
    if not image_id:
        return ""
    return f"{IIIF_BASE}/{image_id}/full/{size}/0/default.jpg"


def get_iiif_dimensions(image_id: str, session: requests.Session) -> tuple:
    """
    Query the IIIF info.json endpoint to get native pixel dimensions.
    Much faster than downloading the full image.
    Returns (width, height) or (0, 0) on failure.
    """
    if not image_id:
        return 0, 0
    url = f"{IIIF_BASE}/{image_id}/info.json"
    try:
        resp = session.get(url, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("width", 0), data.get("height", 0)
    except Exception:
        return 0, 0


def search_artworks(query: str, page: int, session: requests.Session) -> dict:
    """Full-text search for public-domain artworks."""
    url = f"{BASE_URL}/artworks/search"
    params = {
        "q": query,
        "query[term][is_public_domain]": "true",
        "fields": ",".join(FIELDS),
        "limit": 100,
        "page": page,
    }
    try:
        resp = session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [AIC] Search error for {query!r} page {page}: {e}")
        return {}


def normalize_record(raw: dict) -> dict | None:
    """Convert AIC API response to normalized record. Returns None if unusable."""
    if not raw or not raw.get("is_public_domain"):
        return None

    image_id = raw.get("image_id")
    if not image_id:
        return None

    thumbnail = raw.get("thumbnail") or {}
    artist_raw = raw.get("artist_display", "Unknown")
    artist = artist_raw.split("\n")[0].strip()  # first line only

    return {
        "source": "aic",
        "source_id": str(raw.get("id", "")),
        "title": raw.get("title", "Untitled"),
        "artist": artist,
        "date": raw.get("date_display", ""),
        "medium": raw.get("medium_display", ""),
        "dimensions_raw": raw.get("dimensions", ""),
        "width_cm": None,
        "height_cm": None,
        "pixel_width": thumbnail.get("width"),
        "pixel_height": thumbnail.get("height"),
        "image_url_full": make_image_url(image_id, "full"),
        "image_url_small": make_image_url(image_id, f"{config.AIC_PREVIEW_WIDTH_PX},"),
        "detail_url": raw.get("api_link", ""),
        "public_url": f"https://www.artic.edu/artworks/{raw.get('id')}",
        "department": raw.get("department_title", ""),
        "tags": [],
        "country": raw.get("place_of_origin", ""),
        "period": raw.get("style_title", ""),
        "credit_line": "",
        "rights": "CC0 Public Domain",
        "description": raw.get("description", "") or "",
        "_image_id": image_id,
    }


def fetch_all_candidates(limit: int = None) -> list:
    """
    Run all landscape queries against the AIC API and return normalized records.

    Args:
        limit: Max records to return. Defaults to config.MAX_CANDIDATES_PER_SOURCE.
    """
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[AIC] Starting candidate fetch...")
    session = _session()
    seen_ids = set()
    records = []

    for query in LANDSCAPE_QUERIES:
        if len(records) >= limit:
            break
        print(f"  [AIC] Searching: {query!r}")

        for page in range(1, config.AIC_MAX_PAGES_PER_QUERY + 1):
            data = search_artworks(query, page, session)
            artworks = data.get("data", [])
            if not artworks:
                break

            for raw in artworks:
                art_id = raw.get("id")
                if art_id in seen_ids:
                    continue
                seen_ids.add(art_id)
                rec = normalize_record(raw)
                if rec:
                    records.append(rec)

            pagination = data.get("pagination", {})
            if page >= pagination.get("total_pages", 1):
                break

            time.sleep(config.AIC_REQUEST_DELAY)

        time.sleep(config.AIC_REQUEST_DELAY)

    print(f"[AIC] Fetched {len(records)} candidate records.")
    return records
