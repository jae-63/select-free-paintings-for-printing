"""
sources/rijksmuseum.py

Client for the Rijksmuseum (Amsterdam) Open Data API.
No API key required for read-only access at modest rate.
All parameters come from config.py.

Docs:    https://data.rijksmuseum.nl/object-metadata/api/
IIIF:    https://www.rijksmuseum.nl/api/iiif/{object_number}/manifest

The Rijksmuseum has the world's strongest collection of Dutch Golden Age
landscape paintings — Ruisdael, Hobbema, van Goyen, Cuyp, Koninck — as well
as significant holdings of 17th-century Flemish landscapes. These are exactly
the smooth-technique oils we want.

Medium-detection note:
The Rijksmuseum uses Dutch medium terms. Key ones:
  "olieverf op doek"  = oil on canvas
  "olieverf op paneel" = oil on panel
  "aquarel"           = watercolor
  "gouache"           = gouache
  "pen en inkt"       = pen and ink (excluded)
These are handled by adding Dutch terms to our classifier.
"""

import re
import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

BASE_URL  = "https://www.rijksmuseum.nl/api/en/collection"
IIIF_BASE = "https://www.rijksmuseum.nl/api/iiif"

# Rijksmuseum image URL pattern — serves very high resolution
# https://lh3.googleusercontent.com/{id}=s0 gives original resolution
# The API also returns webImage.url directly

# Queries — Rijksmuseum search supports Dutch and English terms
# 'type' filter accepts: painting, drawing, print, photograph, etc.
WATERCOLOR_QUERIES = [
    "watercolor landscape",
    "watercolour landscape",
    "aquarel landschap",        # Dutch: watercolor landscape
    "aquarel zeezicht",         # Dutch: watercolor seascape
    "gouache landscape",
    "watercolor seascape",
    "watercolor river",
    "watercolor coastal",
]

OIL_QUERIES = [
    "oil painting landscape",
    "olieverf landschap",       # Dutch: oil landscape
    "river landscape oil",
    "coastal landscape oil",
    "pastoral landscape",
    "winter landscape",
    "forest landscape oil",
    "seascape oil",
    "polder landscape",         # classic Dutch subject
    "dunes landscape",
    "river estuary",
]

LANDSCAPE_QUERIES = WATERCOLOR_QUERIES + OIL_QUERIES

# Dutch medium terms that map to our classifier
# These supplement config.WATERCOLOR_MEDIUM_TERMS and config.OIL_MEDIUM_TERMS
DUTCH_WATERCOLOR_TERMS = {"aquarel", "gouache"}
DUTCH_OIL_TERMS = {"olieverf op doek", "olieverf op paneel", "olieverf op koper"}
DUTCH_EXCLUDE_TERMS = {"ets", "gravure", "houtsnede", "litho", "fotografie"}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


def _clean_artist(raw: str) -> str:
    """Normalise Rijksmuseum artist strings."""
    if not raw:
        return "Unknown"
    # Rijksmuseum sometimes gives "Lastname, Firstname" — reorder
    if "," in raw and raw.index(",") < 30:
        parts = raw.split(",", 1)
        raw = f"{parts[1].strip()} {parts[0].strip()}"
    return raw.strip()


def _infer_medium(obj: dict) -> str:
    """
    Extract medium from Rijksmuseum object record.
    Checks 'materials' list and 'physicalMedium' string field.
    """
    materials = [m.lower() for m in (obj.get("materials") or [])]
    phys = (obj.get("physicalMedium") or "").lower()
    sub_title = (obj.get("subTitle") or "").lower()
    combined = " ".join(materials) + " " + phys + " " + sub_title

    # Exclusions first
    for term in DUTCH_EXCLUDE_TERMS:
        if term in combined:
            return "other"
    for term in config.EXCLUDE_MEDIUM_TERMS:
        if term in combined:
            return "other"

    # Watercolor
    for term in DUTCH_WATERCOLOR_TERMS:
        if term in combined:
            return "watercolor"
    for term in config.WATERCOLOR_MEDIUM_TERMS:
        if term in combined:
            return "watercolor"

    # Oil
    for term in DUTCH_OIL_TERMS:
        if term in combined:
            return "oil on canvas"
    for term in config.OIL_MEDIUM_TERMS:
        if term in combined:
            return "oil on canvas"
    if "oil" in combined:
        return "oil on canvas"

    return ""


def _get_image_info(obj: dict) -> tuple:
    """
    Extract image URL and pixel dimensions from a Rijksmuseum object record.
    The API returns webImage with w/h dimensions — no separate IIIF probe needed.
    Returns (image_url_full, image_url_small, pixel_width, pixel_height).
    """
    web_image = obj.get("webImage") or {}
    full_url  = web_image.get("url", "")
    px_w      = web_image.get("width", 0)
    px_h      = web_image.get("height", 0)

    # Rijksmuseum serves via Google's image CDN — append =s0 for full resolution
    if full_url and not full_url.endswith("=s0"):
        full_url_hires = full_url + "=s0"
    else:
        full_url_hires = full_url

    # Small thumbnail: restrict to ~700px wide
    small_url = full_url + "=w700" if full_url else ""

    return full_url_hires, small_url, px_w, px_h


def search(query: str, page: int, session: requests.Session) -> dict:
    """Search the Rijksmuseum collection."""
    params = {
        "q":           query,
        "type":        "painting|drawing",   # exclude prints, photos, sculptures
        "imgonly":     "True",               # must have image
        "toppieces":   "False",
        "ps":          100,                  # page size (max 100)
        "p":           page,
        "s":           "relevance",
        "culture":     "en",
    }
    try:
        resp = session.get(BASE_URL, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [Rijksmuseum] Search error for {query!r} page {page}: {e}")
        return {}


def get_object_detail(obj_number: str, session: requests.Session) -> dict:
    """
    Fetch full object detail to get materials, dimensions, and high-res image info.
    The collection search endpoint returns limited fields; detail fills in the rest.
    """
    url = f"{BASE_URL}/{obj_number}"
    params = {"culture": "en"}
    for attempt in range(config.HTTP_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            return resp.json().get("artObject") or {}
        except Exception as e:
            if attempt < config.HTTP_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [Rijksmuseum] Detail fetch error for {obj_number}: {e}")
                return {}
    return {}


def normalize_record(obj: dict) -> dict | None:
    """
    Convert a Rijksmuseum art object to a normalised record.
    obj should be the full artObject detail dict.
    """
    if not obj:
        return None

    obj_number = obj.get("objectNumber", "")
    title      = obj.get("title") or obj.get("longTitle") or "Untitled"
    artist     = _clean_artist(
        (obj.get("principalMaker") or
         (obj.get("principalMakers") or [{}])[0].get("name", "")) or "Unknown"
    )
    date       = obj.get("dating", {}).get("presentingDate", "") or ""
    medium     = _infer_medium(obj)

    if not medium:
        return None  # skip if we can't determine medium

    # Dimensions
    w_cm, h_cm = None, None
    for dim in (obj.get("dimensions") or []):
        unit  = dim.get("unit", "")
        typ   = dim.get("type", "").lower()
        value = dim.get("value")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if unit == "cm":
            if "width" in typ or typ == "b":
                w_cm = value
            elif "height" in typ or typ == "h":
                h_cm = value
        elif unit == "in":
            if "width" in typ or typ == "b":
                w_cm = value * 2.54
            elif "height" in typ or typ == "h":
                h_cm = value * 2.54

    image_full, image_small, px_w, px_h = _get_image_info(obj)
    if not image_full:
        return None

    public_url = f"https://www.rijksmuseum.nl/en/collection/{obj_number}"

    # Description from label text
    desc = ""
    for label in (obj.get("labelText") or []):
        if label:
            desc = label[:500]
            break

    return {
        "source":        "rijksmuseum",
        "source_id":     obj_number,
        "title":         title,
        "artist":        artist,
        "date":          str(date),
        "medium":        medium,
        "dimensions_raw": obj.get("subTitle", ""),
        "width_cm":      w_cm,
        "height_cm":     h_cm,
        "pixel_width":   px_w,
        "pixel_height":  px_h,
        "image_url_full":  image_full,
        "image_url_small": image_small,
        "detail_url":    public_url,
        "public_url":    public_url,
        "department":    obj.get("subCollection", {}).get("name", ""),
        "tags":          [c.get("label", "") for c in (obj.get("classifications") or [])],
        "country":       obj.get("countryCode", ""),
        "period":        obj.get("dating", {}).get("period", ""),
        "credit_line":   obj.get("acquisition", {}).get("creditLine", ""),
        "rights":        "CC0 Public Domain",
        "description":   desc,
        "_image_id":     None,
    }


def fetch_all_candidates(
    queries: list = None,
    limit:   int  = None,
) -> list:
    """
    Run landscape queries against the Rijksmuseum API and return normalised records.

    Args:
        queries: Query list. Defaults to LANDSCAPE_QUERIES.
        limit:   Max records. Defaults to config.MAX_CANDIDATES_PER_SOURCE.
    """
    if queries is None:
        queries = LANDSCAPE_QUERIES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[Rijksmuseum] Starting candidate fetch...")
    session  = _session()
    seen_ids = set()
    records  = []

    for query in queries:
        if len(records) >= limit:
            break
        print(f"  [Rijksmuseum] Searching: {query!r}")

        for page in range(1, 11):  # max 10 pages = 1000 results per query
            if len(records) >= limit:
                break

            data  = search(query, page, session)
            items = data.get("artObjects") or []
            if not items:
                break

            for item in items:
                if len(records) >= limit:
                    break
                obj_number = item.get("objectNumber")
                if not obj_number or obj_number in seen_ids:
                    continue
                seen_ids.add(obj_number)

                # Fetch full detail for medium/dimension/image info
                detail = get_object_detail(obj_number, session)
                if not detail:
                    continue

                rec = normalize_record(detail)
                if rec:
                    records.append(rec)

                time.sleep(config.MET_REQUEST_DELAY)  # reuse Met's polite delay

            total = data.get("count", 0)
            if page * 100 >= min(total, 1000):
                break

            time.sleep(config.AIC_REQUEST_DELAY)

    print(f"[Rijksmuseum] Fetched {len(records)} candidate records.")
    return records
