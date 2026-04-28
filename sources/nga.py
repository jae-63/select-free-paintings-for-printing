"""
sources/nga.py

Client for the National Gallery of Art (Washington DC) open data programme.
No API key required. All public-domain works are CC0.

Data source:
  The NGA publishes CSV data files on GitHub (updated daily):
    https://github.com/NationalGalleryOfArt/opendata

Strategy:
  1. Stream objects.csv → collect qualifying objectIDs (classification = Painting
     or Drawing, already-CC0-accessible).
  2. Stream published_images.csv → for each row whose depictstmsobjectid is in
     the qualifying set, join metadata and build a normalised record.
  3. Pixel dimensions are embedded in published_images.csv; no IIIF probing needed.

IIIF image server:  https://api.nga.gov/iiif/{uuid}
Convention:         dimensions in objects.csv follow H × W (height first).
"""

import csv
import io
import re
import time
import requests
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_OBJECTS_CSV_URL = (
    "https://raw.githubusercontent.com/NationalGalleryOfArt/opendata/main/data/objects.csv"
)
_IMAGES_CSV_URL = (
    "https://raw.githubusercontent.com/NationalGalleryOfArt/opendata/main/data/published_images.csv"
)

_QUALIFYING_CLASSIFICATIONS = {"Painting", "Drawing"}

# Medium terms that clearly indicate non-paintings in the Drawing category
_SKIP_MEDIUM_TERMS = {
    "graphite", "charcoal", "chalk", "pencil", "ink ", " ink", "engraving",
    "etching", "lithograph", "woodcut", "screenprint", "mezzotint",
}

WATERCOLOR_QUERIES = ["Drawing"]
OIL_QUERIES = ["Painting"]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


def _load_csv(url: str, session: requests.Session) -> list[dict]:
    """Download a CSV and return all rows as a list of dicts."""
    print(f"  [NGA] Downloading {url.split('/')[-1]} …")
    resp = session.get(url, timeout=120)
    resp.raise_for_status()
    text = resp.content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _parse_dims(dims_text: str) -> tuple:
    """
    Parse NGA dimensions string (H × W convention, height listed first).
    Returns (w_cm, h_cm) or (None, None).
    """
    if not dims_text:
        return None, None
    m = re.search(
        r"(\d+\.?\d*)\s*[×x]\s*(\d+\.?\d*)(?:\s*[×x]\s*\d+\.?\d*)?\s*cm",
        dims_text,
    )
    if m:
        h_cm = float(m.group(1))
        w_cm = float(m.group(2))
        return w_cm, h_cm
    m2 = re.search(
        r"(\d+\.?\d*)\s*[×x]\s*(\d+\.?\d*)(?:\s*[×x]\s*\d+\.?\d*)?\s*in",
        dims_text,
    )
    if m2:
        return float(m2.group(2)) * 2.54, float(m2.group(1)) * 2.54
    return None, None


def normalize_record(obj_row: dict, img_row: dict) -> dict | None:
    """Combine an objects.csv row with a published_images.csv row."""
    iiif_url = img_row.get("iiifurl", "").strip()
    if not iiif_url:
        return None

    px_w = int(img_row.get("width", 0) or 0)
    px_h = int(img_row.get("height", 0) or 0)
    if not px_w or not px_h:
        return None

    title = obj_row.get("title", "").strip()
    if not title:
        return None

    artist = obj_row.get("attribution", "").strip() or "Unknown"
    medium = obj_row.get("medium", "").strip().lower()
    dims_raw = obj_row.get("dimensions", "").strip()
    date = obj_row.get("displaydate", "").strip()
    obj_id = obj_row.get("objectid", "").strip()
    accession = obj_row.get("accessionnum", "").strip()

    w_cm, h_cm = _parse_dims(dims_raw)

    image_url_full = f"{iiif_url}/full/full/0/default.jpg"
    image_url_small = f"{iiif_url}/full/!700,700/0/default.jpg"

    detail_url = (
        f"https://www.nga.gov/collection/art-object-page.{obj_id}.html"
        if obj_id else ""
    )

    return {
        "source":          "nga",
        "source_id":       accession or obj_id,
        "title":           title,
        "artist":          artist,
        "date":            date,
        "medium":          medium,
        "dimensions_raw":  dims_raw,
        "width_cm":        w_cm,
        "height_cm":       h_cm,
        "pixel_width":     px_w,
        "pixel_height":    px_h,
        "image_url_full":  image_url_full,
        "image_url_small": image_url_small,
        "detail_url":      detail_url,
        "public_url":      detail_url,
        "department":      obj_row.get("departmentabbr", ""),
        "tags":            [],
        "country":         "United States",
        "period":          obj_row.get("visualbrowsertimespan", ""),
        "credit_line":     obj_row.get("creditline", ""),
        "rights":          "CC0 Public Domain",
        "description":     "",
        "_image_id":       "",
    }


def fetch_all_candidates(queries: list = None, limit: int = None) -> list:
    """
    Fetch NGA paintings/drawings by streaming the GitHub CSV files.

    Args:
        queries: List of classification strings to include
                 (e.g. ["Painting"] or ["Drawing"]).
                 Defaults to OIL_QUERIES + WATERCOLOR_QUERIES.
        limit:   Max records to return.
    """
    if queries is None:
        queries = OIL_QUERIES + WATERCOLOR_QUERIES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    target_classifications = set(queries)

    print("[NGA] Starting candidate fetch via GitHub CSV…")
    session = _session()

    # ── Pass 1: objects.csv → collect qualifying metadata
    print("  [NGA] Loading objects.csv …")
    obj_rows = _load_csv(_OBJECTS_CSV_URL, session)
    print(f"  [NGA] {len(obj_rows):,} total object rows loaded.")

    qualifying: dict[str, dict] = {}
    for row in obj_rows:
        if row.get("classification", "") not in target_classifications:
            continue
        obj_id = row.get("objectid", "").strip()
        if not obj_id:
            continue
        # Pre-filter: skip non-painting drawings by medium keyword
        medium_lc = row.get("medium", "").lower()
        if medium_lc and any(t in medium_lc for t in _SKIP_MEDIUM_TERMS):
            continue
        qualifying[obj_id] = row

    print(f"  [NGA] {len(qualifying):,} qualifying objects (classification filter applied).")

    # ── Pass 2: published_images.csv → join with qualifying objects
    print("  [NGA] Loading published_images.csv …")
    img_rows = _load_csv(_IMAGES_CSV_URL, session)
    print(f"  [NGA] {len(img_rows):,} total image rows loaded.")

    seen_obj_ids: set[str] = set()
    records: list[dict] = []

    for img_row in img_rows:
        if len(records) >= limit:
            break
        if img_row.get("openaccess", "").strip() != "1":
            continue
        if img_row.get("viewtype", "").strip() != "primary":
            continue
        if img_row.get("sequence", "").strip() not in ("0", ""):
            continue

        obj_id = img_row.get("depictstmsobjectid", "").strip()
        if not obj_id or obj_id not in qualifying:
            continue
        if obj_id in seen_obj_ids:
            continue
        seen_obj_ids.add(obj_id)

        rec = normalize_record(qualifying[obj_id], img_row)
        if rec:
            records.append(rec)

    print(f"[NGA] Fetched {len(records)} candidate records.")
    return records
