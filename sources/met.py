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

# Search queries for the Met API.
# Without a medium filter, queries need to be specific enough to surface
# paintings and works on paper rather than sculptures, textiles, etc.
# The Met's full-text search covers title, artist, medium, and tags.
# Pairing a landscape subject with a medium term (watercolor, oil) works
# well because the medium word appears in the Met's own `medium` metadata
# field, which is indexed for full-text search even though the `medium`
# filter parameter doesn't work reliably.
LANDSCAPE_QUERIES = [
    # Watercolor / gouache — medium word in query pulls works-on-paper
    "watercolor landscape",
    "watercolor seascape",
    "watercolor river",
    "watercolor coastal",
    "watercolor mountain",
    "watercolor harbor",
    "watercolor valley",
    "watercolor sunset",
    "watercolor lake",
    "gouache landscape",
    "aquarelle landscape",
    # Oil landscape — paired with subject to reduce portrait noise
    "oil canvas landscape",
    "oil painting landscape",
    "oil painting seascape",
    "oil painting river",
    "oil painting coastal",
    "oil painting pastoral",
    "oil painting mountain",
    # Landscape by style / school — Met tags these reliably
    "impressionist landscape",
    "luminist landscape",
    "hudson river landscape",
    "barbizon landscape",
    "plein air landscape",
]

# The Met API's `medium` search parameter requires exact matches against their
# internal controlled vocabulary, which is undocumented and silently returns 0
# results for unrecognised strings. We therefore do NOT filter by medium at
# search time. Instead we fetch all public-domain results for each landscape
# query and let our own classify_medium() handle medium filtering post-fetch.
# This is the same approach used for Europeana.
#
# To narrow results at search time you can use `hasImages=true` (already
# applied) and `departmentId` — Met department IDs for relevant depts:
#   11 = European Paintings, 21 = Drawings and Prints, 13 = Greek/Roman,
#    9 = Drawings & Prints, 3 = Ancient Near Eastern Art
# We leave departmentId open to cast the widest net.


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


def search(query: str, session: requests.Session) -> list:
    """Return object IDs matching query. Public domain only, must have image."""
    params = {
        "q": query,
        "isPublicDomain": "true",
        "hasImages": "true",
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
