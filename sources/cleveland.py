"""
sources/cleveland.py

Client for the Cleveland Museum of Art Open Access API.
No API key required. All CC0 public domain.

Docs: https://openaccess-api.clevelandart.org/
API:  https://openaccess-api.clevelandart.org/api/artworks/

Pixel dimensions are available directly in each API record's images object,
so no separate probing is needed.

Dimension convention: Cleveland uses H × W (height first, European).
Image tiers:
  full   — variable TIFF (highest resolution, use for canvas printing)
  print  — 3400px longest side, JPEG
  web    — 900px longest side, JPEG (used for preview/tarball)
"""

import re
import time
import requests
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_BASE_URL = "https://openaccess-api.clevelandart.org/api/artworks/"

WATERCOLOR_QUERIES = ["Drawing"]   # CMA has no "Watercolor" type; watercolors live in Drawing
OIL_QUERIES        = ["Painting"]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.HTTP_USER_AGENT,
        "Accept":     "application/json",
    })
    return s


def _search_page(artwork_type: str, skip: int, session: requests.Session) -> dict:
    params = {
        "type":      artwork_type,
        "cc0":       1,
        "has_image": 1,
        "limit":     100,
        "skip":      skip,
    }
    try:
        resp = session.get(_BASE_URL, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [Cleveland] API error for type={artwork_type!r} skip={skip}: {e}")
        return {}


def _extract_artist(creators: list) -> str:
    if not creators:
        return "Unknown"
    for c in creators:
        if c.get("role") in ("artist", "painter", "maker", "creator", ""):
            name = c.get("name", "").strip()
            if name:
                return name
    return creators[0].get("name", "Unknown").strip() or "Unknown"


def _parse_dims(measurements: str) -> tuple:
    """
    Parse CMA measurements string (H × W convention, height first).
    Prefer the 'Unframed:' measurement when present.
    Returns (w_cm, h_cm) or (None, None).
    """
    if not measurements:
        return None, None

    # Look for "Unframed: H × W cm" first
    m = re.search(
        r"[Uu]nframed\s*:\s*(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*cm",
        measurements,
    )
    if not m:
        # Fall back to first H × W cm match
        m = re.search(
            r"(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*cm",
            measurements,
        )
    if m:
        h_cm = float(m.group(1))
        w_cm = float(m.group(2))
        return w_cm, h_cm

    # Inches fallback
    m2 = re.search(r"(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*in", measurements)
    if m2:
        return float(m2.group(2)) * 2.54, float(m2.group(1)) * 2.54

    return None, None


def normalize_record(item: dict) -> dict | None:
    """Convert a CMA API record into our standard normalised format."""
    if not item:
        return None

    title = (item.get("title") or "").strip()
    if not title:
        return None

    images = item.get("images") or {}
    full_img   = images.get("full") or {}
    print_img  = images.get("print") or {}
    web_img    = images.get("web") or {}

    full_url  = full_img.get("url", "")
    small_url = web_img.get("url", "") or print_img.get("url", "")

    if not full_url and not small_url:
        return None

    # Pixel dimensions: use full (TIFF) when available, fall back to print
    px_w = int(full_img.get("width") or print_img.get("width") or 0)
    px_h = int(full_img.get("height") or print_img.get("height") or 0)

    artist = _extract_artist(item.get("creators") or [])
    date   = (item.get("creation_date") or "").strip()
    medium = (item.get("technique") or "").strip().lower()

    measurements = item.get("measurements") or ""
    w_cm, h_cm = _parse_dims(measurements)

    source_id = str(item.get("id", "") or item.get("accession_number", ""))
    detail_url = item.get("url", "")

    return {
        "source":          "cleveland",
        "source_id":       source_id,
        "title":           title,
        "artist":          artist,
        "date":            date,
        "medium":          medium,
        "dimensions_raw":  measurements,
        "width_cm":        w_cm,
        "height_cm":       h_cm,
        "pixel_width":     px_w,
        "pixel_height":    px_h,
        "image_url_full":  full_url,
        "image_url_small": small_url,
        "detail_url":      detail_url,
        "public_url":      detail_url,
        "department":      item.get("department", ""),
        "tags":            item.get("classification", []) or [],
        "country":         "",
        "period":          "",
        "credit_line":     item.get("creditline", ""),
        "rights":          "CC0 Public Domain",
        "description":     item.get("description", ""),
        "_image_id":       "",
    }


def fetch_all_candidates(queries: list = None, limit: int = None) -> list:
    """
    Fetch Cleveland Museum of Art artworks via the Open Access API.

    Args:
        queries: List of CMA artwork type strings to query.
                 Defaults to OIL_QUERIES + WATERCOLOR_QUERIES.
        limit:   Max records to return.
    """
    if queries is None:
        queries = OIL_QUERIES + WATERCOLOR_QUERIES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[Cleveland] Starting candidate fetch…")
    session  = _session()
    seen_ids = set()
    records  = []

    for artwork_type in queries:
        if len(records) >= limit:
            break
        print(f"  [Cleveland] Querying type: {artwork_type!r}")

        skip = 0
        while len(records) < limit:
            data = _search_page(artwork_type, skip, session)
            items = (data.get("data") or [])
            info  = data.get("info") or {}
            total = int(info.get("total") or 0)

            if not items:
                break

            for item in items:
                if len(records) >= limit:
                    break
                item_id = str(item.get("id", "") or item.get("accession_number", ""))
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                rec = normalize_record(item)
                if rec:
                    records.append(rec)

            skip += len(items)
            if skip >= min(total, 10000):
                break
            time.sleep(getattr(config, "CLEVELAND_REQUEST_DELAY", 0.2))

    print(f"[Cleveland] Fetched {len(records)} candidate records.")
    return records
