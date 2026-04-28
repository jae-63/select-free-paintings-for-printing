"""
sources/smithsonian.py

Client for the Smithsonian Institution Open Access API.
API key required — free at https://api.data.gov/signup/
Docs: https://edan.si.edu/openaccess/apidocs/

Primary unit: Smithsonian American Art Museum (SAAM)
Focused on the art_design category endpoint which reliably returns paintings.

Pixel dimensions are embedded in each API record's media resources list, so
no separate image probing is needed for most records.
"""

import re
import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

SEARCH_URL = "https://api.si.edu/openaccess/api/v1.0/category/art_design/search"

UNIT_CODE = "SAAM"

WATERCOLOR_SEARCHES = [
    "watercolor landscape",
    "watercolour landscape",
    "gouache landscape",
    "watercolor seascape",
    "watercolor river",
    "watercolor coastal",
    "watercolor mountains",
]

OIL_SEARCHES = [
    "oil painting landscape",
    "oil on canvas landscape",
    "oil landscape seascape",
    "oil coastal landscape",
    "oil pastoral landscape",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.HTTP_USER_AGENT,
        "Accept":     "application/json",
    })
    return s


def _get_freetext_first(freetext: dict, key: str) -> str:
    for entry in (freetext.get(key) or []):
        val = entry.get("content", "")
        if val:
            return val
    return ""


def _extract_artist(freetext: dict) -> str:
    names = freetext.get("name") or []
    for entry in names:
        if entry.get("label") in ("Artist", "Creator", "Maker", "Painter"):
            name = entry.get("content", "")
            # Strip ", born ..." / ", died ..." / ", active ..." biographical suffixes
            name = re.sub(r",\s*(born|died|active)\b.*$", "", name, flags=re.IGNORECASE)
            # Strip ", American" / ", French" etc. nationality suffixes SAAM appends
            name = re.sub(r",\s*[A-Z][a-z]+\s*$", "", name)
            # Strip trailing bare year ranges like "1850-1920" or "(1875–1950)"
            name = re.sub(r"\s*[\(]?\d{4}\s*[-–]\s*\d{4}[\)]?\s*$", "", name)
            name = re.sub(r"\s*,\s*\d{4}\s*$", "", name)
            return name.strip().rstrip(",").strip()
    return "Unknown"


def _extract_medium(freetext: dict) -> str:
    for entry in (freetext.get("physicalDescription") or []):
        if entry.get("label") == "Medium":
            return entry.get("content", "").lower()
    return ""


def _extract_dimensions(freetext: dict) -> tuple:
    """
    Parse width/height from Dimensions entry.
    Format examples:
      '20 x 14 in. (50.8 x 35.6 cm)'   — prefer cm value
      '12 5/8 x 9 1/4 in.'              — inches only, convert to cm
    Returns (width_cm, height_cm) or (None, None).
    """
    for entry in (freetext.get("physicalDescription") or []):
        if entry.get("label") != "Dimensions":
            continue
        text = entry.get("content", "")

        # Prefer cm values in parentheses
        cm = re.search(r'\((\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*cm\)', text)
        if cm:
            return float(cm.group(1)), float(cm.group(2))

        # Fall back to inches
        inches = re.search(r'(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*in', text)
        if inches:
            return float(inches.group(1)) * 2.54, float(inches.group(2)) * 2.54

    return None, None


def _extract_image(dnr: dict) -> tuple:
    """
    Extract (image_url_full, image_url_small, pixel_width, pixel_height, image_id)
    from descriptiveNonRepeating. Returns empty strings/zeros on failure.

    The API embeds pixel dimensions in the resources list, so no IIIF probing needed.
    """
    media_block = dnr.get("online_media", {})
    media_list  = media_block.get("media") or []
    if not media_list:
        return "", "", 0, 0, ""

    media      = media_list[0]
    image_id   = media.get("idsId", "") or media.get("id", "").replace("media:", "")
    thumbnail  = media.get("thumbnail", "")
    full_url   = ""
    px_w, px_h = 0, 0

    for resource in (media.get("resources") or []):
        if resource.get("label") == "High-resolution JPEG":
            full_url = resource.get("url", "")
            px_w     = int(resource.get("width",  0) or 0)
            px_h     = int(resource.get("height", 0) or 0)
            break

    # Fallback to delivery service URL (still usable for probing if needed)
    if not full_url:
        full_url = media.get("content", "")

    return full_url, thumbnail, px_w, px_h, image_id


def normalize_record(item: dict) -> dict | None:
    """Convert a Smithsonian API record to our standard normalized format."""
    if not item:
        return None

    content  = item.get("content", {})
    freetext = content.get("freetext", {})
    dnr      = content.get("descriptiveNonRepeating", {})
    indexed  = content.get("indexedStructured", {})

    # Only paintings / works on paper (not books, exhibition catalogues, etc.)
    obj_types = [
        e.get("content", "").lower()
        for e in (freetext.get("objectType") or [])
    ]
    if not any(t in ("painting", "work on paper", "drawing") for t in obj_types):
        return None

    # Only CC0 / public domain
    rights_text = " ".join(
        e.get("content", "")
        for e in (freetext.get("objectRights") or [])
    ).upper()
    if "CC0" not in rights_text and "PUBLIC DOMAIN" not in rights_text:
        return None

    title = dnr.get("title", {}).get("content", "") or item.get("title", "")
    if not title:
        return None

    full_url, thumb_url, px_w, px_h, image_id = _extract_image(dnr)
    if not full_url:
        return None

    artist      = _extract_artist(freetext)
    date        = _get_freetext_first(freetext, "date")
    medium      = _extract_medium(freetext)
    w_cm, h_cm  = _extract_dimensions(freetext)
    record_link = dnr.get("record_link", "")

    return {
        "source":          "smithsonian",
        "source_id":       dnr.get("record_ID", item.get("id", "")),
        "title":           title,
        "artist":          artist,
        "date":            date,
        "medium":          medium,
        "dimensions_raw":  "",
        "width_cm":        w_cm,
        "height_cm":       h_cm,
        "pixel_width":     px_w,
        "pixel_height":    px_h,
        "image_url_full":  full_url,
        "image_url_small": thumb_url,
        "detail_url":      record_link,
        "public_url":      record_link,
        "department":      item.get("unitCode", ""),
        "tags":            indexed.get("topic", []),
        "country":         "",
        "period":          "",
        "credit_line":     _get_freetext_first(freetext, "creditLine"),
        "rights":          "CC0 Public Domain",
        "description":     "",
        "_image_id":       "",   # pixel dims come from the API response; no probing needed
    }


def _search_page(query: str, start: int, session: requests.Session) -> dict:
    params = {
        "q":       query,
        "rows":    100,
        "start":   start,
        "api_key": config.SMITHSONIAN_API_KEY,
        "fq":      f"unit_code:{UNIT_CODE}",
    }
    try:
        resp = session.get(SEARCH_URL, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [Smithsonian] Search error for {query!r} start={start}: {e}")
        return {}


def fetch_all_candidates(queries: list = None, limit: int = None) -> list:
    """
    Run search queries against the Smithsonian SAAM collection and return
    normalized records. Watercolor and oil queries should be run as separate
    passes (same pattern as Europeana) from fetch_candidates.py.
    """
    if queries is None:
        queries = WATERCOLOR_SEARCHES + OIL_SEARCHES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    if not config.SMITHSONIAN_API_KEY:
        print("[Smithsonian] No API key set (SMITHSONIAN_API_KEY in .env) — skipping.")
        return []

    print("[Smithsonian] Starting candidate fetch...")
    session  = _session()
    seen_ids = set()
    records  = []

    for query in queries:
        if len(records) >= limit:
            break
        print(f"  [Smithsonian] Searching: {query!r}")

        start = 0
        while len(records) < limit:
            data      = _search_page(query, start, session)
            response  = data.get("response", {})
            rows      = response.get("rows") or []
            row_count = response.get("rowCount") or 0

            if not rows:
                break

            for item in rows:
                if len(records) >= limit:
                    break

                obj_id = item.get("id", "") or item.get("url", "")
                if not obj_id or obj_id in seen_ids:
                    continue
                seen_ids.add(obj_id)

                rec = normalize_record(item)
                if rec:
                    records.append(rec)

            start += len(rows)
            if start >= min(row_count, 1000):
                break
            time.sleep(config.SMITHSONIAN_REQUEST_DELAY)

    print(f"[Smithsonian] Fetched {len(records)} candidate records.")
    return records
