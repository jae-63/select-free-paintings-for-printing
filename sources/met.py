"""
sources/met.py

Client for The Metropolitan Museum of Art Open Access API.
No API key required. All parameters come from config.py.

Docs: https://metmuseum.github.io/
"""

import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

BASE_URL = "https://collectionapi.metmuseum.org/public/collection/v1"

# Search queries targeting landscapes in various media.
# Extend this list in config.py if you want to add more search terms
# (or just add them here for Met-specific terms).
LANDSCAPE_QUERIES = [
    "landscape watercolor",
    "landscape gouache",
    "landscape oil painting",
    "seascape watercolor",
    "seascape oil",
    "river landscape",
    "coastal landscape watercolor",
    "valley landscape",
    "mountain landscape watercolor",
    "pastoral landscape",
    "countryside landscape",
    "forest landscape watercolor",
    "lake landscape",
    "harbor watercolor",
    "sunset landscape",
    "dawn landscape watercolor",
    "landscape aquarelle",
    "paysage watercolor",
    "view landscape painting",
]

# Met medium filter for the search endpoint
MET_MEDIUM_FILTER = "Watercolors|Oil on canvas|Paintings|Gouache|Drawings"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


def search(query: str, session: requests.Session) -> list:
    """Return object IDs matching query, filtered to public domain works."""
    params = {
        "q": query,
        "isPublicDomain": "true",
        "medium": MET_MEDIUM_FILTER,
    }
    url = f"{BASE_URL}/search"
    try:
        resp = session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("objectIDs") or []
    except Exception as e:
        print(f"  [Met] Search error for {query!r}: {e}")
        return []


def get_object(object_id: int, session: requests.Session) -> dict | None:
    """Fetch a single object's metadata with retries."""
    url = f"{BASE_URL}/objects/{object_id}"
    for attempt in range(config.HTTP_RETRIES):
        try:
            resp = session.get(url, timeout=config.HTTP_TIMEOUT)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < config.HTTP_RETRIES - 1:
                time.sleep(1)
            else:
                print(f"  [Met] Object fetch error for {object_id}: {e}")
                return None


def normalize_record(raw: dict) -> dict | None:
    """Convert raw Met API response to normalized record. Returns None if unusable."""
    if not raw:
        return None
    if not raw.get("isPublicDomain"):
        return None
    if not raw.get("primaryImage"):
        return None

    return {
        "source": "met",
        "source_id": str(raw.get("objectID", "")),
        "title": raw.get("title", "Untitled"),
        "artist": raw.get("artistDisplayName", "Unknown"),
        "date": raw.get("objectDate", ""),
        "medium": raw.get("medium", ""),
        "dimensions_raw": raw.get("dimensions", ""),
        "width_cm": None,
        "height_cm": None,
        "pixel_width": None,
        "pixel_height": None,
        "image_url_full": raw.get("primaryImage", ""),
        "image_url_small": raw.get("primaryImageSmall", ""),
        "detail_url": raw.get("objectURL", ""),
        "public_url": raw.get("objectURL", ""),
        "department": raw.get("department", ""),
        "tags": [t.get("term", "") for t in (raw.get("tags") or [])],
        "country": raw.get("country", ""),
        "period": raw.get("period", ""),
        "credit_line": raw.get("creditLine", ""),
        "rights": "CC0 Public Domain",
        "description": "",
        "_image_id": None,  # Met doesn't use IIIF image IDs
    }


def fetch_all_candidates(limit: int = None) -> list:
    """
    Run all landscape queries and return normalized records.
    Deduplicates by objectID.

    Args:
        limit: Max records to return. Defaults to config.MAX_CANDIDATES_PER_SOURCE.
    """
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[Met] Starting candidate fetch...")
    session = _session()
    seen_ids = set()
    records = []

    for query in LANDSCAPE_QUERIES:
        if len(records) >= limit:
            break
        print(f"  [Met] Searching: {query!r}")
        ids = search(query, session)
        print(f"         → {len(ids)} results")

        for obj_id in ids:
            if len(records) >= limit:
                break
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)

            raw = get_object(obj_id, session)
            if raw is None:
                continue
            rec = normalize_record(raw)
            if rec:
                records.append(rec)

            time.sleep(config.MET_REQUEST_DELAY)

    print(f"[Met] Fetched {len(records)} candidate records.")
    return records
