"""
sources/europeana.py

Client for the Europeana API — aggregates content from hundreds of European
cultural institutions. All parameters come from config.py.

Free API key: https://apis.europeana.eu/api/apikey-form
Docs:         https://pro.europeana.eu/page/search

Set EUROPEANA_API_KEY in your .env file (see config.example.env).
"""

import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

SEARCH_URL = "https://api.europeana.eu/record/v2/search.json"

LANDSCAPE_QUERIES = [
    "landscape watercolor",
    "landscape watercolour",
    "landscape gouache",
    "seascape watercolor",
    "paysage aquarelle",        # French
    "Landschaft Aquarell",      # German
    "landschap aquarel",        # Dutch
    "landscape oil painting",
    "river landscape painting",
    "coastal landscape watercolor",
    "mountain landscape watercolor",
    "pastoral landscape oil",
    "atmospheric landscape",
    "nocturne landscape",
    "harbor watercolor",
    "fjord landscape",          # Scandinavian watercolorists
    "countryside landscape watercolor",
]

DEFAULT_SEARCH_PARAMS = {
    "reusability": "open",    # CC0 or CC BY
    "media": "true",
    "thumbnail": "true",
    "type": "IMAGE",
    "rows": 100,
    "profile": "rich",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


def _extract_lang_aware(field, fallback="") -> str:
    """Extract a string from a Europeana LangAware field (dict or list)."""
    if isinstance(field, dict):
        # Prefer English, then first available language
        for lang in ("en", "fr", "de", "nl", "it", "es"):
            if lang in field and field[lang]:
                return field[lang][0]
        for vals in field.values():
            if vals:
                return vals[0]
        return fallback
    if isinstance(field, list) and field:
        return field[0]
    return fallback


def search(query: str, api_key: str, start: int, session: requests.Session) -> dict:
    """Execute one page of Europeana search."""
    params = {
        **DEFAULT_SEARCH_PARAMS,
        "query": query,
        "wskey": api_key,
        "start": start,
    }
    try:
        resp = session.get(SEARCH_URL, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [Europeana] Search error for {query!r}: {e}")
        return {}


def normalize_record(item: dict) -> dict | None:
    """Convert a Europeana search item to normalized record. Returns None if unusable."""
    if not item:
        return None

    title  = _extract_lang_aware(item.get("dcTitleLangAware") or item.get("title"))
    artist = _extract_lang_aware(item.get("dcCreatorLangAware") or item.get("dcCreator"))
    medium = _extract_lang_aware(item.get("dcFormatLangAware") or item.get("dcFormat"))
    desc   = _extract_lang_aware(item.get("dcDescriptionLangAware") or item.get("dcDescription"))

    edmPreview   = item.get("edmPreview") or []
    edmIsShownBy = item.get("edmIsShownBy") or []
    image_small  = edmPreview[0]   if edmPreview   else ""
    image_full   = edmIsShownBy[0] if edmIsShownBy else image_small

    if not image_full and not image_small:
        return None

    guid          = item.get("guid", "")
    edmIsShownAt  = item.get("edmIsShownAt") or []
    public_url    = edmIsShownAt[0] if edmIsShownAt else guid

    years         = item.get("year") or []
    date          = str(years[0]) if years else ""

    data_provider = item.get("dataProvider") or []
    institution   = data_provider[0] if data_provider else ""

    rights_list   = item.get("rights") or []
    rights        = rights_list[0] if rights_list else ""

    return {
        "source": "europeana",
        "source_id": item.get("id", ""),
        "title": title or "Untitled",
        "artist": artist or "Unknown",
        "date": date,
        "medium": medium,
        "dimensions_raw": "",
        "width_cm": None,
        "height_cm": None,
        "pixel_width": None,
        "pixel_height": None,
        "image_url_full": image_full,
        "image_url_small": image_small,
        "detail_url": public_url,
        "public_url": public_url,
        "department": institution,
        "tags": item.get("edmConceptPrefLabelLangAware", {}).get("en", []),
        "country": (item.get("country") or [""])[0],
        "period": "",
        "credit_line": institution,
        "rights": rights,
        "description": desc,
        "_image_id": None,
    }


def fetch_all_candidates(api_key: str = None, limit: int = None) -> list:
    """
    Run all landscape queries and return normalized records.

    Args:
        api_key: Europeana API key. Defaults to config.EUROPEANA_API_KEY.
        limit:   Max records. Defaults to config.MAX_CANDIDATES_PER_SOURCE.
    """
    if api_key is None:
        api_key = config.EUROPEANA_API_KEY
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    if not api_key:
        print("[Europeana] No API key — skipping. Set EUROPEANA_API_KEY in .env")
        return []

    print("[Europeana] Starting candidate fetch...")
    session = _session()
    seen_ids = set()
    records = []

    for query in LANDSCAPE_QUERIES:
        if len(records) >= limit:
            break
        print(f"  [Europeana] Searching: {query!r}")

        start = 1
        for _ in range(config.EUROPEANA_MAX_PAGES_PER_QUERY):
            data = search(query, api_key, start, session)
            items = data.get("items") or []
            if not items:
                break

            for item in items:
                item_id = item.get("id")
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                rec = normalize_record(item)
                if rec:
                    records.append(rec)

            total = data.get("totalResults", 0)
            next_start = start + 100
            if next_start >= min(total, config.EUROPEANA_MAX_RESULTS_PER_QUERY):
                break
            start = next_start
            time.sleep(config.EUROPEANA_REQUEST_DELAY)

        time.sleep(config.EUROPEANA_REQUEST_DELAY)

    print(f"[Europeana] Fetched {len(records)} candidate records.")
    return records
