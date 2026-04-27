"""
sources/rijksmuseum.py

Client for the Rijksmuseum (Amsterdam) new Search API (2024+).
No API key required. All parameters come from config.py.

New API docs: https://data.rijksmuseum.nl/docs/search
IIIF images:  https://iiif.micr.io/{image_id}/info.json

The old collection API (rijksmuseum.nl/api/en/collection) returned 410 Gone
in 2024/2025. This rewrite uses the new Linked Art Search API.

Architecture:
  1. Search returns a list of Linked Art object identifiers (URLs)
  2. Each identifier is resolved via content negotiation to get metadata
  3. Image IDs are extracted from the Linked Art representation
  4. IIIF endpoint at iiif.micr.io provides pixel dimensions and images
"""

import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

SEARCH_URL  = "https://data.rijksmuseum.nl/search/collection"
IIIF_BASE   = "https://iiif.micr.io"

# Dutch medium terms for our classifier
DUTCH_WATERCOLOR_TERMS = {"aquarel", "gouache", "waterverf"}
DUTCH_OIL_TERMS        = {"olieverf", "olieverfschilderij"}
DUTCH_EXCLUDE_TERMS    = {"ets", "gravure", "houtsnede", "litho",
                          "fotografie", "foto", "zeefdruk"}

# Search query sets — use structured params not free text
# Each entry is a dict of API params
WATERCOLOR_SEARCHES = [
    {"type": "drawing", "material": "watercolor",   "imageAvailable": "true"},
    {"type": "drawing", "material": "watercolour",  "imageAvailable": "true"},
    {"type": "drawing", "material": "aquarel",      "imageAvailable": "true"},  # Dutch
    {"type": "drawing", "material": "gouache",      "imageAvailable": "true"},
    {"type": "drawing", "technique": "watercolor",  "imageAvailable": "true"},
    {"type": "drawing", "technique": "aquarelle",   "imageAvailable": "true"},
]

OIL_SEARCHES = [
    {"type": "painting", "material": "oil paint",  "imageAvailable": "true"},
    {"type": "painting", "material": "olieverf",   "imageAvailable": "true"},  # Dutch
    {"type": "painting", "technique": "oil on canvas", "imageAvailable": "true"},
    {"type": "painting", "title": "landscape",     "imageAvailable": "true"},
    {"type": "painting", "title": "landschap",     "imageAvailable": "true"},  # Dutch
    {"type": "painting", "description": "landscape", "imageAvailable": "true"},
]

WATERCOLOR_QUERIES = WATERCOLOR_SEARCHES  # alias for fetch_candidates.py import
OIL_QUERIES        = OIL_SEARCHES
LANDSCAPE_QUERIES  = WATERCOLOR_SEARCHES + OIL_SEARCHES


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.HTTP_USER_AGENT,
        "Accept":     "application/json",
    })
    return s


def _get_iiif_dimensions(image_id: str, session: requests.Session) -> tuple:
    """Query iiif.micr.io info.json for native pixel dimensions."""
    url = f"{IIIF_BASE}/{image_id}/info.json"
    try:
        resp = session.get(url, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("width", 0), data.get("height", 0)
    except Exception:
        return 0, 0


def search_page(params: dict, page_url: str | None,
                session: requests.Session) -> dict:
    """
    Fetch one page of search results.
    If page_url is given, fetch that URL directly (pagination).
    Otherwise build from params.
    """
    try:
        if page_url:
            resp = session.get(page_url, timeout=config.HTTP_TIMEOUT)
        else:
            resp = session.get(SEARCH_URL, params=params,
                               timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [Rijksmuseum] Search error: {e}")
        return {}


def resolve_object(identifier: str, session: requests.Session) -> dict:
    """
    Resolve a Linked Art object identifier to its full metadata.
    The identifier is a URL like https://id.rijksmuseum.nl/200108293
    We request JSON-LD via content negotiation.
    """
    try:
        resp = session.get(
            identifier,
            headers={**session.headers, "Accept": "application/ld+json"},
            timeout=config.HTTP_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {}


def _extract_text(node) -> str:
    """Extract a plain string from a Linked Art label/content node."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        for item in node:
            result = _extract_text(item)
            if result:
                return result
        return ""
    if isinstance(node, dict):
        for key in ("content", "_label", "value", "@value"):
            if key in node:
                return _extract_text(node[key])
    return ""


def _extract_classified_labels(items: list) -> list:
    """Extract all _label strings from a list of classified_as or similar."""
    labels = []
    for item in (items or []):
        label = _extract_text(item.get("_label") or item.get("label") or "")
        if label:
            labels.append(label.lower())
    return labels


def _extract_medium(obj: dict) -> str:
    """
    Infer medium from Linked Art object.
    Checks made_of (materials), technique classified_as, and title text.
    """
    # Materials
    materials = []
    for m in (obj.get("made_of") or []):
        label = _extract_text(m.get("_label") or "")
        if label:
            materials.append(label.lower())
        # Also recurse into classified_as
        for cls in (m.get("classified_as") or []):
            lbl = _extract_text(cls.get("_label") or "")
            if lbl:
                materials.append(lbl.lower())

    # Production technique
    for prod in (obj.get("produced_by") or [{}]) if isinstance(obj.get("produced_by"), list) else [obj.get("produced_by") or {}]:
        for tech in (prod.get("technique") or []):
            lbl = _extract_text(tech.get("_label") or "")
            if lbl:
                materials.append(lbl.lower())

    combined = " ".join(materials)

    if not combined:
        return ""

    # Exclusions
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


def _extract_dimensions(obj: dict) -> tuple:
    """Extract (width_cm, height_cm) from Linked Art dimension records."""
    w_cm = h_cm = None
    for dim in (obj.get("dimension") or []):
        try:
            value = float(dim.get("value", 0))
        except (TypeError, ValueError):
            continue

        unit_label = _extract_text(
            (dim.get("unit") or {}).get("_label") or ""
        ).lower()
        type_labels = _extract_classified_labels(dim.get("classified_as") or [])
        type_str = " ".join(type_labels)

        mult = 1.0
        if "inch" in unit_label or "in." in unit_label:
            mult = 2.54
        elif "mm" in unit_label:
            mult = 0.1
        elif "cm" not in unit_label and unit_label:
            continue

        if "width" in type_str or "breedte" in type_str:
            w_cm = value * mult
        elif "height" in type_str or "hoogte" in type_str:
            h_cm = value * mult

    return w_cm, h_cm


def _extract_image_id(obj: dict) -> str:
    """
    Extract the Micrio IIIF image ID from a Linked Art object.
    Image services are referenced via the representation/service chain.
    """
    for rep in (obj.get("representation") or []):
        for svc in (rep.get("digitally_shown_by") or []):
            for access in (svc.get("access_point") or []):
                url = access.get("id") or access.get("@id") or ""
                # iiif.micr.io/{image_id}/...
                if "micr.io" in url:
                    parts = url.replace("https://iiif.micr.io/", "").split("/")
                    if parts[0]:
                        return parts[0]
        # Direct access_point on representation
        for access in (rep.get("access_point") or []):
            url = access.get("id") or access.get("@id") or ""
            if "micr.io" in url:
                parts = url.replace("https://iiif.micr.io/", "").split("/")
                if parts[0]:
                    return parts[0]
    return ""


def normalize_record(obj: dict) -> dict | None:
    """Convert a Linked Art object to a normalised record."""
    if not obj:
        return None

    # Identifier → source_id
    identifier = obj.get("id") or obj.get("@id") or ""
    source_id  = identifier.split("/")[-1] if identifier else ""
    if not source_id:
        return None

    # Title
    title = "Untitled"
    for id_node in (obj.get("identified_by") or []):
        types = _extract_classified_labels(id_node.get("classified_as") or [])
        if any("title" in t or "naam" in t for t in types) or not types:
            t = _extract_text(id_node.get("content") or id_node.get("value") or "")
            if t:
                title = t
                break

    # Artist
    artist = "Unknown"
    prod   = obj.get("produced_by") or {}
    if isinstance(prod, list):
        prod = prod[0] if prod else {}
    for carried in (prod.get("carried_out_by") or []):
        name = _extract_text(carried.get("_label") or "")
        if name:
            artist = name
            break

    # Date
    date = ""
    timespan = prod.get("timespan") or {}
    if isinstance(timespan, list):
        timespan = timespan[0] if timespan else {}
    for id_node in (timespan.get("identified_by") or []):
        t = _extract_text(id_node.get("content") or id_node.get("value") or "")
        if t:
            date = t
            break
    if not date:
        date = _extract_text(timespan.get("_label") or "")

    # Medium
    medium = _extract_medium(obj)
    if not medium or medium == "other":
        return None

    # Dimensions
    w_cm, h_cm = _extract_dimensions(obj)

    # Image
    image_id = _extract_image_id(obj)
    if not image_id:
        return None

    image_url_full  = f"{IIIF_BASE}/{image_id}/full/max/0/default.jpg"
    image_url_small = f"{IIIF_BASE}/{image_id}/full/700,/0/default.jpg"
    public_url = f"https://www.rijksmuseum.nl/en/collection/{source_id}"

    return {
        "source":         "rijksmuseum",
        "source_id":      source_id,
        "title":          title,
        "artist":         artist,
        "date":           date,
        "medium":         medium,
        "dimensions_raw": "",
        "width_cm":       w_cm,
        "height_cm":      h_cm,
        "pixel_width":    0,
        "pixel_height":   0,
        "image_url_full":   image_url_full,
        "image_url_small":  image_url_small,
        "detail_url":     public_url,
        "public_url":     public_url,
        "department":     "",
        "tags":           [],
        "country":        "Netherlands",
        "period":         "",
        "credit_line":    "",
        "rights":         "CC0 Public Domain",
        "description":    "",
        "_image_id":      image_id,
    }


def fetch_all_candidates(
    queries: list = None,
    limit:   int  = None,
) -> list:
    """
    Run searches against the new Rijksmuseum Search API and return
    normalised records.

    Args:
        queries: List of param dicts. Defaults to LANDSCAPE_QUERIES.
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

    for params in queries:
        if len(records) >= limit:
            break

        param_str = " ".join(f"{k}={v}" for k, v in params.items()
                             if k != "imageAvailable")
        print(f"  [Rijksmuseum] Searching: {param_str}")

        page_url = None
        pages    = 0

        while len(records) < limit and pages < 10:
            data  = search_page(params, page_url, session)
            items = data.get("orderedItems") or []
            if not items:
                break

            total = (data.get("partOf") or {}).get("totalItems", 0)
            if pages == 0:
                print(f"           → {total} results")

            for item in items:
                if len(records) >= limit:
                    break
                identifier = item.get("id") or item.get("@id") or ""
                if not identifier:
                    continue
                source_id = identifier.split("/")[-1]
                if source_id in seen_ids:
                    continue
                seen_ids.add(source_id)

                obj = resolve_object(identifier, session)
                if not obj:
                    continue

                rec = normalize_record(obj)
                if rec:
                    records.append(rec)

                time.sleep(config.AIC_REQUEST_DELAY)

            # Pagination
            next_node = data.get("next") or {}
            page_url  = next_node.get("id") if next_node else None
            if not page_url:
                break
            pages += 1
            time.sleep(config.AIC_REQUEST_DELAY)

    print(f"[Rijksmuseum] Fetched {len(records)} candidate records.")
    return records
