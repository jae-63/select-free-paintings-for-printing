"""
sources/getty.py

Client for the J. Paul Getty Museum Open Content API.
No API key required. All parameters come from config.py.

Docs:       https://data.getty.edu/museum/api/
IIIF:       https://data.getty.edu/museum/api/iiif/{object_id}/manifest
Open Access: https://www.getty.edu/about/opencontent/

The Getty's Open Content program provides high-resolution TIFF and JPEG
downloads of all public-domain works — often 20,000px+ for large paintings.
Strong holdings in European paintings, drawings, illuminated manuscripts
(we filter those), and photography (also filtered).

The Getty Museum collection API is IIIF-compliant and returns image dimensions
via the manifest, similar to AIC.
"""

import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

BASE_URL     = "https://data.getty.edu/museum/api/collection/v1/objects"
IIIF_BASE    = "https://data.getty.edu/museum/api/iiif"
SEARCH_URL   = "https://data.getty.edu/museum/api/collection/v1/objects"

# Getty uses SPARQL-style filters on their API — we use simpler keyword search
# via their /objects endpoint with `q` and `type` params

WATERCOLOR_QUERIES = [
    "watercolor landscape",
    "watercolour landscape",
    "gouache landscape",
    "watercolor seascape",
    "watercolor coastal",
    "watercolor river",
    "watercolor mountains",
    "watercolor valley",
]

OIL_QUERIES = [
    "oil painting landscape",
    "oil on canvas landscape",
    "oil on panel landscape",
    "landscape painting oil",
    "pastoral landscape oil",
    "coastal landscape oil",
    "seascape oil painting",
    "river landscape oil",
]

LANDSCAPE_QUERIES = WATERCOLOR_QUERIES + OIL_QUERIES


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.HTTP_USER_AGENT,
        "Accept":     "application/json",
    })
    return s


def _get_iiif_dimensions(object_id: str, session: requests.Session) -> tuple:
    """
    Query the Getty IIIF info.json for native pixel dimensions.
    Returns (width, height) or (0, 0) on failure.
    """
    url = f"{IIIF_BASE}/{object_id}/info.json"
    try:
        resp = session.get(url, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("width", 0), data.get("height", 0)
    except Exception:
        return 0, 0


def search_objects(query: str, page: int, session: requests.Session) -> dict:
    """Search the Getty collection."""
    params = {
        "q":         query,
        "limit":     100,
        "offset":    (page - 1) * 100,
    }
    try:
        resp = session.get(SEARCH_URL, params=params,
                           timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [Getty] Search error for {query!r}: {e}")
        return {}


def get_object_detail(object_id: str, session: requests.Session) -> dict:
    """Fetch full object detail from the Getty API."""
    url = f"{BASE_URL}/{object_id}"
    for attempt in range(config.HTTP_RETRIES):
        try:
            resp = session.get(url, timeout=config.HTTP_TIMEOUT)
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < config.HTTP_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [Getty] Detail fetch error for {object_id}: {e}")
                return {}
    return {}


def _extract_label(obj_or_list, lang: str = "en") -> str:
    """Extract a string from Getty's Linked Art label structure."""
    if isinstance(obj_or_list, list):
        for item in obj_or_list:
            result = _extract_label(item, lang)
            if result:
                return result
        return ""
    if isinstance(obj_or_list, dict):
        # Try content field directly
        if "content" in obj_or_list:
            return obj_or_list["content"]
        # Try _label
        if "_label" in obj_or_list:
            return obj_or_list["_label"]
        # Try value
        if "value" in obj_or_list:
            return obj_or_list["value"]
    return str(obj_or_list) if obj_or_list else ""


def _extract_medium(obj: dict) -> str:
    """
    Extract medium from Getty Linked Art object structure.
    Getty uses the 'made_of' field for materials.
    """
    made_of = obj.get("made_of") or []
    materials = []
    for m in made_of:
        label = _extract_label(m.get("_label") or m.get("label") or "")
        if label:
            materials.append(label.lower())

    combined = " ".join(materials)

    # Also check classified_as for technique
    for cls in (obj.get("classified_as") or []):
        label = _extract_label(cls.get("_label") or cls.get("label") or "")
        if label:
            combined += " " + label.lower()

    if not combined:
        return ""

    for term in config.EXCLUDE_MEDIUM_TERMS:
        if term in combined:
            return "other"
    for term in config.IMPASTO_DISQUALIFY_TERMS:
        if term in combined:
            return "impasto_oil"
    for term in config.WATERCOLOR_MEDIUM_TERMS:
        if term in combined:
            return "watercolor"
    for term in config.OIL_MEDIUM_TERMS:
        if term in combined:
            return "oil on canvas"
    if "oil" in combined:
        return "oil on canvas"

    return ""


def _extract_dimensions(obj: dict) -> tuple:
    """
    Extract (width_cm, height_cm) from Getty dimension records.
    Getty uses the 'dimension' field with Linked Art structure.
    """
    w_cm, h_cm = None, None
    for dim in (obj.get("dimension") or []):
        value = dim.get("value")
        unit_label = _extract_label(
            (dim.get("unit") or {}).get("_label") or ""
        ).lower()
        type_label = _extract_label(
            (dim.get("classified_as") or [{}])[0].get("_label") or ""
        ).lower() if dim.get("classified_as") else ""

        try:
            value = float(value)
        except (TypeError, ValueError):
            continue

        multiplier = 1.0
        if "inch" in unit_label or unit_label == "in":
            multiplier = 2.54
        elif "mm" in unit_label:
            multiplier = 0.1
        elif "cm" not in unit_label and unit_label:
            continue  # unknown unit

        if "width" in type_label:
            w_cm = value * multiplier
        elif "height" in type_label:
            h_cm = value * multiplier

    return w_cm, h_cm


def normalize_record(obj: dict) -> dict | None:
    """Convert a Getty API object to a normalised record."""
    if not obj:
        return None

    object_id = str(obj.get("id", "")).split("/")[-1]
    if not object_id:
        return None

    # Title
    title = _extract_label(obj.get("identified_by") or obj.get("_label") or "Untitled")
    if not title or title == "Untitled":
        title = obj.get("_label", "Untitled")

    # Artist
    artist = "Unknown"
    for prod in (obj.get("produced_by", {}).get("carried_out_by") or []):
        name = _extract_label(prod.get("_label") or prod.get("label") or "")
        if name:
            artist = name
            break

    # Date
    date = ""
    timespan = obj.get("produced_by", {}).get("timespan") or {}
    date = _extract_label(timespan.get("identified_by") or
                          timespan.get("_label") or "")

    # Medium
    medium = _extract_medium(obj)
    if not medium or medium == "other":
        return None

    # Dimensions
    w_cm, h_cm = _extract_dimensions(obj)

    # Image — Getty provides IIIF
    image_url_full  = f"{IIIF_BASE}/{object_id}/full/full/0/default.jpg"
    image_url_small = f"{IIIF_BASE}/{object_id}/full/700,/0/default.jpg"

    # Check IIIF dimensions — done during filtering in fetch_candidates
    # to avoid N+1 calls here
    px_w, px_h = 0, 0

    public_url = f"https://www.getty.edu/art/collection/object/{object_id}"

    return {
        "source":        "getty",
        "source_id":     object_id,
        "title":         title,
        "artist":        artist,
        "date":          date,
        "medium":        medium,
        "dimensions_raw": "",
        "width_cm":      w_cm,
        "height_cm":     h_cm,
        "pixel_width":   px_w,
        "pixel_height":  px_h,
        "image_url_full":  image_url_full,
        "image_url_small": image_url_small,
        "detail_url":    public_url,
        "public_url":    public_url,
        "department":    "",
        "tags":          [],
        "country":       "",
        "period":        "",
        "credit_line":   "",
        "rights":        "CC0 Public Domain",
        "description":   "",
        "_image_id":     object_id,  # used for IIIF dimension lookup
    }


def fetch_all_candidates(
    queries: list = None,
    limit:   int  = None,
) -> list:
    """
    Run landscape queries against the Getty API and return normalised records.

    Args:
        queries: Query list. Defaults to LANDSCAPE_QUERIES.
        limit:   Max records. Defaults to config.MAX_CANDIDATES_PER_SOURCE.
    """
    if queries is None:
        queries = LANDSCAPE_QUERIES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[Getty] Starting candidate fetch...")
    session  = _session()
    seen_ids = set()
    records  = []

    for query in queries:
        if len(records) >= limit:
            break
        print(f"  [Getty] Searching: {query!r}")

        for page in range(1, 11):
            if len(records) >= limit:
                break

            data  = search_objects(query, page, session)
            items = data.get("items") or data.get("objects") or []
            if not items:
                break

            for item in items:
                if len(records) >= limit:
                    break

                obj_id = str(item.get("id", "")).split("/")[-1]
                if not obj_id or obj_id in seen_ids:
                    continue
                seen_ids.add(obj_id)

                detail = get_object_detail(obj_id, session)
                if not detail:
                    continue

                rec = normalize_record(detail)
                if rec:
                    records.append(rec)

                time.sleep(config.AIC_REQUEST_DELAY)

            total = data.get("total") or data.get("totalCount") or 0
            if page * 100 >= min(total, 1000):
                break
            time.sleep(config.AIC_REQUEST_DELAY)

    print(f"[Getty] Fetched {len(records)} candidate records.")
    return records
