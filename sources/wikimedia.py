"""
sources/wikimedia.py

Client for Wikimedia Commons, with a focus on the Musée d'Orsay and other
Paris / French national museums, plus key European and American landscape
art movements.

No API key required.  Wikimedia policy requires a descriptive User-Agent.

Strategy
--------
1. For each category in the query list, page through file members using the
   MediaWiki action=query&list=categorymembers API.
2. Batch-request imageinfo (url, size, extmetadata) for up to 50 files at
   once.  extmetadata gives artist, date, title, medium, and license.
3. Accept only Public Domain / CC-licensed works.
4. Normalise to the standard record schema used by every other source.

The Wikimedia images have known pixel dimensions from imageinfo, so no
separate resolution probing is needed — pixel_width and pixel_height are
always populated.

Musée d'Orsay note
------------------
The Wikimedia Commons category "Paintings in the Musée d'Orsay" contains
thousands of files organised into subcategories by artist.  We browse the
top-level category AND its first-level subcategories (depth=1) to get good
coverage without over-crawling.
"""

import re
import time
import requests
import sys
import os
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_API_URL = "https://commons.wikimedia.org/w/api.php"

# ---------------------------------------------------------------------------
# Category lists
# ---------------------------------------------------------------------------

# Categories to query when looking for watercolors.
# Category names are verified against the live Wikimedia Commons API.
WATERCOLOR_CATEGORIES = [
    "Watercolor paintings of landscapes",       # verified: 3 direct + 13 subcats
    "Watercolor paintings by Winslow Homer",    # verified: 5 direct + 3 subcats
    "Watercolors in the Musée d'Orsay",         # may exist; falls back to empty gracefully
    "19th-century watercolor paintings of landscapes",
    "Watercolor paintings by artist",           # browse subcategory tree
]

# Categories to query when looking for oil paintings.
# Includes the primary Musée d'Orsay category and major landscape movements.
# All category names verified against the live Wikimedia Commons API.
OIL_CATEGORIES = [
    # Musée d'Orsay (French national, Impressionist/Post-Impressionist focus)
    "Landscape paintings in the Musée d'Orsay",    # verified: 5 direct + 4 subcats
    "Paintings in the Musée d'Orsay by artist",    # verified: 0 direct + 66 artist subcats
    "Paintings in the Musée d'Orsay",              # verified: 10 direct + 15 subcats
    # Musée de l'Orangerie (French national; Monet Water Lilies + others)
    "Paintings in the Musée de l'Orangerie",
    # Louvre (French national; old masters landscape collection)
    "Landscape paintings in the Louvre",
    "Paintings in the Louvre by Corot",
    "Paintings in the Louvre by Poussin",
    # Musée Marmottan Monet (private foundation; deep Monet/Impressionist holdings)
    "Paintings in the Musée Marmottan Monet",
    # Château de Versailles (French national; grand landscape and garden paintings)
    "Paintings in the Palace of Versailles",
    # Impressionist landscape artists
    "Paintings by Claude Monet",                   # verified: 1 direct + 11 subcats
    "Paintings by Alfred Sisley",                  # verified: 5 direct + 9 subcats
    "Paintings by Camille Pissarro",               # verified: 3 direct + 14 subcats
    "Paintings by Gustave Courbet",
    "Paintings by Édouard Manet",
    "Paintings by Berthe Morisot",
    "Paintings by Paul Cézanne",
    "Paintings by Georges Seurat",
    # American landscape
    "Hudson River School paintings",               # verified: 10 direct + 4 subcats
    "Paintings by Winslow Homer",                  # verified: 3 direct + 14 subcats
    "Paintings by Albert Bierstadt",
    "Paintings by Frederic Edwin Church",
    "Paintings by Thomas Cole",
    # Other European landscape masters
    "Paintings by John Constable",
    "Paintings by Johan Jongkind",
    "Paintings by Jacob van Ruisdael",
    "Paintings by Jan van Goyen",
    "Paintings by Jean-Baptiste-Camille Corot",
]

# Categories for landscape photographs.
# All sources here are unambiguously public domain in the US:
#   - Carol M. Highsmith: donated copyright to the Library of Congress
#   - FSA/OWI: US federal government works (1930s–40s)
#   - Detroit Publishing Co.: early 20th-century scenic views, copyright expired
#   - USGS: US federal government works
# Ansel Adams (d. 1984) is excluded — US copyright until ~2054.
# NASA images are excluded — technically PD but mostly orbital/atmospheric,
# not traditional landscape.
PHOTO_CATEGORIES = [
    "Photographs by Carol M. Highsmith",
    "Farm Security Administration photographs",
    "Detroit Publishing Company photographs",
    "United States Geological Survey photographs",
]

# All painting categories (watercolors + oils combined) — used when fetching
# without a specific medium split.
ALL_PAINTING_CATEGORIES = OIL_CATEGORIES + WATERCOLOR_CATEGORIES

# ---------------------------------------------------------------------------
# Accepted license prefixes (case-insensitive substring match)
# ---------------------------------------------------------------------------

_ACCEPTED_LICENSE_FRAGMENTS = (
    "public domain",
    "pd-",
    "cc0",
    "cc-zero",
    "cc by",        # CC BY, CC BY-SA, CC BY 4.0, etc.
    "cc-by",
)


def _license_ok(license_str: str) -> bool:
    low = license_str.lower()
    return any(frag in low for frag in _ACCEPTED_LICENSE_FRAGMENTS)


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities from a string."""
    if not text or "<" not in text:
        return text.strip()
    p = _HTMLStripper()
    try:
        p.feed(text)
        result = p.get_text()
    except Exception:
        result = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    return re.sub(r"\s+", " ", result).strip()


# ---------------------------------------------------------------------------
# API session
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.HTTP_USER_AGENT,
        "Accept": "application/json",
    })
    return s


# ---------------------------------------------------------------------------
# Category member listing
# ---------------------------------------------------------------------------

def _get_category_files(category: str, session: requests.Session,
                        limit: int = 500) -> list:
    """
    Return a list of file titles (e.g. 'File:Corot Landscape.jpg') that are
    direct members of `category` on Wikimedia Commons.

    Paginates using cmcontinue until `limit` files are collected or the
    category is exhausted.
    """
    files = []
    params = {
        "action":    "query",
        "list":      "categorymembers",
        "cmtitle":   f"Category:{category}",
        "cmtype":    "file",
        "cmlimit":   500,
        "cmnamespace": 6,
        "format":    "json",
    }
    cm_continue = None

    while len(files) < limit:
        if cm_continue:
            params["cmcontinue"] = cm_continue
        elif "cmcontinue" in params:
            del params["cmcontinue"]

        try:
            resp = session.get(_API_URL, params=params,
                               timeout=config.HTTP_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [Wikimedia] Category fetch error ({category!r}): {e}")
            break

        members = data.get("query", {}).get("categorymembers", [])
        for m in members:
            if len(files) >= limit:
                break
            title = m.get("title", "")
            if title.startswith("File:"):
                files.append(title)

        cont = data.get("continue", {})
        cm_continue = cont.get("cmcontinue")
        if not cm_continue or not members:
            break

        time.sleep(getattr(config, "WIKIMEDIA_REQUEST_DELAY", 0.25))

    return files


def _get_subcategories(category: str, session: requests.Session) -> list:
    """Return first-level subcategory names (without 'Category:' prefix)."""
    params = {
        "action":  "query",
        "list":    "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmtype":  "subcat",
        "cmlimit": 200,
        "format":  "json",
    }
    try:
        resp = session.get(_API_URL, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    members = data.get("query", {}).get("categorymembers", [])
    return [
        m["title"].removeprefix("Category:")
        for m in members if m.get("title", "").startswith("Category:")
    ]


# ---------------------------------------------------------------------------
# Image info batch fetch
# ---------------------------------------------------------------------------

def _fetch_image_info_batch(titles: list, session: requests.Session) -> dict:
    """
    Batch-fetch imageinfo for up to 50 file titles.

    Returns a dict mapping page title → imageinfo dict (or None on failure).
    Uses POST to avoid 414 URI Too Long errors with long LCCN-style filenames.
    """
    if not titles:
        return {}
    params = {
        "action":     "query",
        "titles":     "|".join(titles),
        "prop":       "imageinfo",
        "iiprop":     "url|size|extmetadata",
        "iiurlwidth": 800,
        "format":     "json",
    }
    try:
        resp = session.post(_API_URL, data=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [Wikimedia] imageinfo error: {e}")
        return {}

    pages = data.get("query", {}).get("pages", {})
    result = {}
    for page in pages.values():
        title = page.get("title", "")
        infos = page.get("imageinfo")
        if infos:
            result[title] = infos[0]
    return result


# ---------------------------------------------------------------------------
# Record normalisation
# ---------------------------------------------------------------------------

def _ext(meta: dict, key: str) -> str:
    """Extract a string value from Wikimedia extmetadata."""
    entry = meta.get(key)
    if isinstance(entry, dict):
        return _strip_html(entry.get("value", ""))
    return ""


def normalize_record(file_title: str, info: dict,
                     medium_hint: str = "") -> dict | None:
    """
    Convert a Wikimedia imageinfo dict to the standard record schema.
    Returns None if the record should be skipped (bad license, no image, etc.).

    medium_hint: fallback used when extmetadata has no Medium/Technique field
                 (e.g. "watercolor on paper", "oil on canvas", "photograph").
    """
    meta = info.get("extmetadata") or {}

    # License check
    license_str = _ext(meta, "LicenseShortName") or _ext(meta, "License")
    if license_str and not _license_ok(license_str):
        return None   # restrictive license (e.g. CC BY-NC)

    full_url  = info.get("url", "")
    thumb_url = info.get("thumburl", "") or full_url
    if not full_url:
        return None

    # Pixel dimensions — always available from imageinfo
    px_w = info.get("width", 0)
    px_h = info.get("height", 0)
    if not px_w or not px_h:
        return None

    # Skip very small images up front
    if px_w < 2000 and px_h < 2000:
        return None

    # Title — prefer ObjectName, fall back to file name
    title = _ext(meta, "ObjectName") or _ext(meta, "Assessments")
    if not title:
        # Derive from file name: "File:Corot_Landscape_1850.jpg" → "Corot Landscape 1850"
        title = file_title.removeprefix("File:")
        title = re.sub(r"\.(jpe?g|png|tiff?|gif|webp)$", "", title, flags=re.IGNORECASE)
        title = title.replace("_", " ").strip()
    if not title:
        return None

    # Artist
    artist = _ext(meta, "Artist") or "Unknown"
    # extmetadata Artist often contains wikilinks: [[Jean-Baptiste-Camille Corot]]
    artist = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", artist)
    # Remove lingering HTML / wiki markup
    artist = _strip_html(artist)
    # Drop parenthetical date ranges that sometimes appear
    artist = re.sub(r"\s*\(\d{4}[–-]\d{0,4}\)$", "", artist).strip()
    if not artist:
        artist = "Unknown"

    # Date
    date = (_ext(meta, "DateTimeOriginal")
            or _ext(meta, "Date")
            or _ext(meta, "DateTime")
            or "")
    # Extract bare year if full timestamp
    m = re.search(r"\b(1[0-9]{3}|20[012][0-9])\b", date)
    date = m.group(1) if m else date[:10]

    # Medium — fall back to caller-supplied hint when extmetadata is empty
    raw_medium = _ext(meta, "Medium") or _ext(meta, "Technique")
    medium = raw_medium or medium_hint
    medium_from_hint = not bool(raw_medium) and bool(medium_hint)

    # Description
    description = _ext(meta, "ImageDescription") or ""

    # Institution (from Credit or Artist field context)
    credit = _ext(meta, "Credit") or ""
    institution = ""
    for keyword in ("Musée d'Orsay", "Louvre", "Orangerie", "Marmottan",
                    "Petit Palais", "Orsay", "Museum", "Gallery"):
        if keyword.lower() in credit.lower() or keyword.lower() in description.lower():
            institution = keyword
            break

    source_id = file_title.removeprefix("File:")

    return {
        "source":          "wikimedia",
        "source_id":       source_id,
        "title":           title,
        "artist":          artist,
        "date":            date,
        "medium":            medium,
        "_medium_from_hint": medium_from_hint,
        "dimensions_raw":  "",
        "width_cm":        None,
        "height_cm":       None,
        "pixel_width":     px_w,
        "pixel_height":    px_h,
        "image_url_full":  full_url,
        "image_url_small": thumb_url,
        "detail_url":      f"https://commons.wikimedia.org/wiki/{file_title.replace(' ', '_')}",
        "public_url":      f"https://commons.wikimedia.org/wiki/{file_title.replace(' ', '_')}",
        "department":      institution,
        "tags":            [],
        "country":         "",
        "period":          "",
        "credit_line":     credit[:200],
        "rights":          license_str,
        "description":     description[:400],
        "_image_id":       None,
    }


# ---------------------------------------------------------------------------
# Main fetch entry point
# ---------------------------------------------------------------------------

def fetch_all_candidates(
    categories: list = None,
    limit: int = None,
    medium_hint: str = "",
) -> list:
    """
    Browse Wikimedia Commons categories and return normalised records.

    Args:
        categories:  List of category names (without 'Category:' prefix).
                     Defaults to ALL_PAINTING_CATEGORIES.
        limit:       Max records to return. Defaults to MAX_CANDIDATES_PER_SOURCE.
        medium_hint: Medium string used as fallback when extmetadata has no
                     Medium/Technique field (e.g. "watercolor on paper",
                     "oil on canvas", "photograph").
    """
    if categories is None:
        categories = ALL_PAINTING_CATEGORIES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[Wikimedia] Starting candidate fetch from Wikimedia Commons…")
    session  = _session()
    seen_ids = set()
    records  = []
    batch_size = getattr(config, "WIKIMEDIA_BATCH_SIZE", 50)
    delay      = getattr(config, "WIKIMEDIA_REQUEST_DELAY", 0.25)

    for category in categories:
        if len(records) >= limit:
            break
        print(f"  [Wikimedia] Category: {category!r}")

        # Collect file titles from this category + its subcategories (depth=1)
        all_titles = _get_category_files(category, session,
                                         limit=max(500, limit * 2))
        time.sleep(delay)

        if not all_titles:
            # Try subcategories if the top-level category has no direct files
            subcats = _get_subcategories(category, session)
            time.sleep(delay)
            for subcat in subcats[:20]:   # cap at 20 subcategories
                if len(all_titles) >= limit * 2:
                    break
                sub_titles = _get_category_files(subcat, session, limit=200)
                all_titles.extend(sub_titles)
                time.sleep(delay)
        else:
            # Also browse subcategories for broader coverage
            subcats = _get_subcategories(category, session)
            time.sleep(delay)
            for subcat in subcats[:15]:
                if len(all_titles) >= limit * 2:
                    break
                sub_titles = _get_category_files(subcat, session, limit=100)
                all_titles.extend(sub_titles)
                time.sleep(delay)

        print(f"    Found {len(all_titles)} file titles in {category!r}")

        # Batch-fetch imageinfo for new titles
        new_titles = [t for t in all_titles if t not in seen_ids]
        for i in range(0, len(new_titles), batch_size):
            if len(records) >= limit:
                break
            batch = new_titles[i : i + batch_size]
            info_map = _fetch_image_info_batch(batch, session)

            for file_title, info in info_map.items():
                if len(records) >= limit:
                    break
                if file_title in seen_ids:
                    continue
                seen_ids.add(file_title)

                rec = normalize_record(file_title, info,
                                      medium_hint=medium_hint)
                if rec:
                    records.append(rec)

            time.sleep(delay)

    print(f"[Wikimedia] Fetched {len(records)} candidate records.")
    return records
