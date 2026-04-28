"""
sources/loc.py

Client for the Library of Congress using the loc.gov JSON search API.
No API key required. Public domain content.

Docs:  https://www.loc.gov/apis/json-and-yaml/
API:   https://www.loc.gov/search/?fo=json&...

Strategy:
  1. Search using the main loc.gov JSON API with image-format facet.
  2. Each search result includes an image_url list; the last entry is the
     largest available web JPEG (capped at 1024px wide by the service layer).
  3. Derive the high-resolution TIFF master URL from the image_url path by
     swapping the 'service' segment for 'master' and the JPEG suffix for
     'u.tif'. This eliminates all per-item resource fetches and avoids
     rate limiting.
  4. pixel_width / pixel_height are left at 0 so apply_filters probes the
     TIFF header (first 64 KB via Range request) for actual dimensions.

Resolution note:
  Most LoC photographs are below 8000 px wide. The Carol M. Highsmith
  Archive (modern digital photography) reliably provides 8000–14 000 px.
  The filter rejects everything below the threshold, so low yield is expected
  from general searches — focus the query terms on Highsmith or similar
  high-quality digitisation programmes.

Medium classification:
  "photograph" maps to OIL_MEDIUM_TERMS (flat, suitable for canvas printing).
  Actual watercolors in the P&P collection classify normally via "watercolor".
"""

import re
import time
import requests
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_SEARCH_URL = "https://www.loc.gov/search/"

# ── Query sets ────────────────────────────────────────────────────────────────
# Each entry is a dict with:
#   q   – full-text search query
#   fa  – pipe-separated facet filters (appended as &fa= params)

WATERCOLOR_QUERIES = [
    {"q": "watercolor landscape",  "fa": "online-format:image"},
    {"q": "watercolour landscape", "fa": "online-format:image"},
]

# The Highsmith Archive is the primary source of 8000px+ images in LoC
OIL_QUERIES = [
    {"q": "landscape highsmith",        "fa": "online-format:image"},
    {"q": "coastal highsmith",          "fa": "online-format:image"},
    {"q": "national park highsmith",    "fa": "online-format:image"},
    {"q": "river valley highsmith",     "fa": "online-format:image"},
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.HTTP_USER_AGENT,
        "Accept":     "application/json",
    })
    return s


def _search_page(q: str, fa: str, page: int, session: requests.Session) -> dict:
    params = {"q": q, "fo": "json", "c": 50, "sp": page}
    if fa:
        params["fa"] = fa
    for attempt in range(3):
        try:
            resp = session.get(_SEARCH_URL, params=params, timeout=config.HTTP_TIMEOUT)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  [LoC] Rate-limited; waiting {wait}s…")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt == 2:
                print(f"  [LoC] Search error q={q!r} page={page}: {e}")
            time.sleep(2)
    return {}


def _derive_tiff_url(image_urls: list) -> tuple:
    """
    Derive (tiff_url, large_jpeg_url) from a search result's image_url list.

    The image_url list is sorted smallest → largest; the last entry is the
    1024 px service JPEG. The TIFF master lives at the same path under
    '/storage-services/master/' with suffix 'u.tif'.

    Returns ('', '') when no usable URL is found.
    """
    for raw_url in reversed(image_urls):
        url = raw_url.split("#")[0]  # strip the #h=…&w=… hint fragment

        if "/storage-services/service/" not in url:
            continue

        # Swap service/master paths and replace JPEG suffix with TIFF
        tiff = url.replace("/storage-services/service/", "/storage-services/master/")
        # Strip known web-service suffixes: v.jpg, r.jpg, _150px.jpg, t.gif
        tiff = re.sub(r"(v|r|_150px)\.(jpe?g)$", "u.tif", tiff)
        tiff = re.sub(r"t\.gif$", "u.tif", tiff)

        if tiff.endswith("u.tif"):
            return tiff, url

    # No TIFF derivable — return the largest available JPEG
    if image_urls:
        return "", image_urls[-1].split("#")[0]
    return "", ""


def _extract_creator(result: dict) -> str:
    """Extract creator name from a loc.gov search result."""
    contributors = result.get("contributor") or []
    if contributors:
        name = contributors[0] if isinstance(contributors[0], str) else ""
        name = re.sub(r",\s*(born|died|active)\b.*$", "", name, flags=re.IGNORECASE)
        name = re.sub(r",?\s*\d{4}-?\d*\s*$", "", name)
        return name.strip()
    return "Unknown"


def _extract_date(result: dict) -> str:
    dates = result.get("dates") or result.get("date") or []
    if isinstance(dates, list) and dates:
        d = dates[0]
        return d.get("full", "") if isinstance(d, dict) else str(d)
    if isinstance(dates, str):
        return dates
    return ""


def _is_usable_image(url: str) -> bool:
    """Reject placeholder GIFs, group-record thumbnails, and non-tiff masters."""
    if not url:
        return False
    bad = ("notdig", "grouprecord", ".gif", "500x500", "placeholder")
    return not any(b in url.lower() for b in bad)


def normalize_record(result: dict, tiff_url: str, large_url: str) -> dict | None:
    """Build a normalised record from a loc.gov search result."""
    if not _is_usable_image(tiff_url) and not _is_usable_image(large_url):
        return None

    title = result.get("title") or ""
    if isinstance(title, list):
        title = " / ".join(t for t in title if t)
    title = str(title).strip()
    if not title:
        return None

    # Derive medium: check online_format and any description for watercolor hints
    fmt = " ".join(result.get("online_format") or []).lower()
    desc = " ".join(
        (result.get("description") or [])
        + (result.get("subject") or [])
    ).lower()

    if any(t in desc for t in ("watercolor", "watercolour", "aquarelle", "gouache")):
        medium = "watercolor on paper"
    else:
        medium = "photograph"

    artist = _extract_creator(result)
    date   = _extract_date(result)
    detail = result.get("url") or ""

    small_url = large_url or tiff_url
    full_url  = tiff_url if _is_usable_image(tiff_url) else large_url

    return {
        "source":          "loc",
        "source_id":       result.get("id", "").split("/")[-2] or result.get("id", ""),
        "title":           title,
        "artist":          artist,
        "date":            date,
        "medium":          medium,
        "dimensions_raw":  "",
        "width_cm":        None,
        "height_cm":       None,
        "pixel_width":     0,
        "pixel_height":    0,
        "image_url_full":  full_url,
        "image_url_small": small_url,
        "detail_url":      detail,
        "public_url":      detail,
        "department":      "Prints & Photographs",
        "tags":            result.get("subject") or [],
        "country":         "United States",
        "period":          "",
        "credit_line":     "",
        "rights":          "Public Domain",
        "description":     "",
        "_image_id":       "",
    }


def fetch_all_candidates(queries: list = None, limit: int = None) -> list:
    """
    Fetch LoC photographs and watercolors via the loc.gov JSON search API.

    Args:
        queries: List of query dicts with 'q' and optional 'fa' (facet filter).
        limit:   Max records to return.
    """
    if queries is None:
        queries = OIL_QUERIES + WATERCOLOR_QUERIES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[LoC] Starting candidate fetch via loc.gov JSON API…")
    session  = _session()
    seen_ids = set()
    records  = []

    for query in queries:
        if len(records) >= limit:
            break
        q  = query.get("q", "")
        fa = query.get("fa", "")
        print(f"  [LoC] Searching: {q!r}")

        page = 1
        while len(records) < limit:
            data    = _search_page(q, fa, page, session)
            results = data.get("results") or []
            pag     = data.get("pagination") or {}
            total_p = int(pag.get("total_pages") or pag.get("pages", {}).get("total", 0) or 0)

            if not results:
                break

            for r in results:
                if len(records) >= limit:
                    break

                item_id = r.get("id", "") or r.get("url", "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                image_urls = r.get("image_url") or []
                tiff_url, large_url = _derive_tiff_url(image_urls)

                if not tiff_url and not large_url:
                    continue

                rec = normalize_record(r, tiff_url, large_url)
                if rec:
                    records.append(rec)

            page += 1
            if page > max(total_p, 1) or page > 10:
                break
            time.sleep(getattr(config, "LOC_REQUEST_DELAY", 0.5))

    print(f"[LoC] Fetched {len(records)} candidate records.")
    return records
