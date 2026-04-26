"""
sources/europeana.py

Client for the Europeana API — aggregates content from hundreds of European
cultural institutions. All parameters come from config.py.

Free API key: https://apis.europeana.eu/api/apikey-form
Docs:         https://pro.europeana.eu/page/search

Set EUROPEANA_API_KEY in your .env file (see config.example.env).

Medium-detection note
---------------------
Europeana records rarely populate dcFormat (the standard medium field).
Instead, medium information appears in three non-standard places:
  1. edmConceptPrefLabelLangAware — structured multilingual concept tags,
     e.g. {"de": ["Aquarellieren"], "fi": ["Vesivärimaalaus"], "ru": ["Акварель"]}
  2. The title itself — many institutions prefix the medium, e.g.
     "Watercolor, Landscape with Cows" or "Akvarel, landskab"
  3. dcDescription — free-text, e.g. "Watercolor of a fjord landscape..."

We check all three in order and also clean the medium prefix from titles
so "Watercolor, Landscape" becomes just "Landscape" in the output.
"""

import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

SEARCH_URL = "https://api.europeana.eu/record/v2/search.json"

WATERCOLOR_QUERIES = [
    "landscape watercolor",
    "landscape watercolour",
    "landscape gouache",
    "seascape watercolor",
    "paysage aquarelle",            # French
    "Landschaft Aquarell",          # German
    "landschap aquarel",            # Dutch
    "akvarel landskab",             # Danish (confirmed in diagnostics)
    "akvarell landskap",            # Swedish/Norwegian
    "akwarela krajobraz",           # Polish
    "coastal landscape watercolor",
    "mountain landscape watercolor",
    "harbor watercolor",
    "fjord landscape watercolor",
    "countryside landscape watercolor",
    "river landscape watercolor",
]

OIL_QUERIES = [
    "landscape oil painting",
    "landscape huile sur toile",    # French
    "landscape Ölgemälde",          # German
    "landscape olieverf",           # Dutch
    "river landscape oil",
    "coastal landscape oil",
    "pastoral landscape oil",
    "atmospheric landscape oil",
    "nocturne landscape oil",
    "mountain landscape oil painting",
    "seascape oil painting",
    "forest landscape oil painting",
]

# Combined list used when fetching both media in one run
LANDSCAPE_QUERIES = WATERCOLOR_QUERIES + OIL_QUERIES

DEFAULT_SEARCH_PARAMS = {
    "reusability": "open",    # CC0 or CC BY
    "media": "true",
    "thumbnail": "true",
    "type": "IMAGE",
    "rows": 100,
    "profile": "rich",
}

# ---------------------------------------------------------------------------
# Multilingual watercolor / oil signals
# Checked against concept labels, title words, and description text.
# All lowercase; we do substring matching.
# ---------------------------------------------------------------------------
_WATERCOLOR_SIGNALS = {
    "watercolor", "watercolour", "aquarelle", "aquarell", "akvarel",
    "akvarell", "akwarela", "aquarela", "акварель", "акварел",
    "vesiväri", "aguarela", "gouache", "guache", "gwasz", "akvarelmaleri",
}

_OIL_SIGNALS = {
    "oil on canvas", "oil on panel", "oil on board", "oil on paper",
    "huile sur toile", "huile sur", "öl auf leinwand", "olaj",
    "olio su tela", "óleo sobre", "olej na", "масло на холсте", "öljy",
}

# Medium prefixes that institutions embed in titles; stripped for clean display.
_TITLE_MEDIUM_PREFIXES = [
    "watercolor", "watercolour", "aquarelle", "gouache", "akvarel",
    "akvarell", "akvarelmaleri", "oil painting", "oil on canvas",
    "drawing", "print", "photograph", "signage",
]


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _extract_lang_aware(field, fallback="") -> str:
    """Extract a single string from a Europeana LangAware field (dict or list)."""
    if isinstance(field, dict):
        for lang in ("en", "fr", "de", "nl", "it", "es", "da", "sv", "no", "pl"):
            if lang in field and field[lang]:
                return field[lang][0]
        for vals in field.values():
            if vals:
                return vals[0]
        return fallback
    if isinstance(field, list) and field:
        return field[0]
    return fallback


def _all_strings_from_field(field) -> list:
    """Return ALL string values from a LangAware dict or plain list."""
    results = []
    if isinstance(field, dict):
        for vals in field.values():
            if isinstance(vals, list):
                results.extend(str(v) for v in vals)
            else:
                results.append(str(vals))
    elif isinstance(field, list):
        results.extend(str(v) for v in field)
    return results


# ---------------------------------------------------------------------------
# Medium inference
# ---------------------------------------------------------------------------

def _infer_medium(item: dict, title_str: str, desc_str: str) -> str:
    """
    Infer painting medium from non-standard Europeana fields.

    Search order (most to least reliable):
      1. edmConceptPrefLabelLangAware — structured multilingual vocab tags
      2. edmConceptLabel — simpler concept list
      3. Title string — medium often prefixed, e.g. "Watercolor, Landscape"
      4. Description — free-text last resort

    Returns "watercolor", "oil on canvas", or "" (unknown).
    """
    # 1 + 2: concept labels
    concept_strings = _all_strings_from_field(
        item.get("edmConceptPrefLabelLangAware") or {}
    )
    for entry in (item.get("edmConceptLabel") or []):
        if isinstance(entry, dict):
            concept_strings.append(entry.get("def", ""))

    combined_concepts = " ".join(concept_strings).lower()

    for sig in _WATERCOLOR_SIGNALS:
        if sig in combined_concepts:
            return "watercolor"
    for sig in _OIL_SIGNALS:
        if sig in combined_concepts:
            return "oil on canvas"

    # 3: title
    t = title_str.lower()
    for sig in _WATERCOLOR_SIGNALS:
        if sig in t:
            return "watercolor"
    for sig in _OIL_SIGNALS:
        if sig in t:
            return "oil on canvas"

    # 4: description
    d = desc_str.lower()
    for sig in _WATERCOLOR_SIGNALS:
        if sig in d:
            return "watercolor"
    for sig in _OIL_SIGNALS:
        if sig in d:
            return "oil on canvas"

    return ""


def _clean_title(title: str) -> str:
    """
    Strip medium prefix from titles like "Watercolor, Landscape with Cows"
    → "Landscape with Cows".  Only strips if a known medium word leads.
    """
    if not title:
        return title
    t_lower = title.lower().strip()
    for prefix in _TITLE_MEDIUM_PREFIXES:
        if t_lower.startswith(prefix):
            remainder = title[len(prefix):].lstrip(" ,;:-–—")
            if remainder:
                return remainder
    return title.strip()


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


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


# ---------------------------------------------------------------------------
# Record normalisation
# ---------------------------------------------------------------------------

def normalize_record(item: dict) -> dict | None:
    """Convert a Europeana search item to a normalised record. Returns None if unusable."""
    if not item:
        return None

    # Raw title and description (before medium stripping)
    raw_title = _extract_lang_aware(item.get("dcTitleLangAware") or item.get("title"))
    artist    = _extract_lang_aware(item.get("dcCreatorLangAware") or item.get("dcCreator"))
    desc      = _extract_lang_aware(item.get("dcDescriptionLangAware") or item.get("dcDescription"))

    # Infer medium from concept labels / title / description
    medium = _infer_medium(item, raw_title, desc)

    # Clean medium prefix out of the display title
    title = _clean_title(raw_title) or raw_title or "Untitled"

    # Images
    edmPreview   = item.get("edmPreview") or []
    edmIsShownBy = item.get("edmIsShownBy") or []
    image_small  = edmPreview[0]   if edmPreview   else ""
    image_full   = edmIsShownBy[0] if edmIsShownBy else image_small

    if not image_full and not image_small:
        return None

    guid         = item.get("guid", "")
    edmIsShownAt = item.get("edmIsShownAt") or []
    public_url   = edmIsShownAt[0] if edmIsShownAt else guid

    years        = item.get("year") or []
    date         = str(years[0]) if years else ""

    data_provider = item.get("dataProvider") or []
    institution   = data_provider[0] if data_provider else ""

    rights_list  = item.get("rights") or []
    rights       = rights_list[0] if rights_list else ""

    return {
        "source":        "europeana",
        "source_id":     item.get("id", ""),
        "title":         title,
        "artist":        artist or "Unknown",
        "date":          date,
        "medium":        medium,
        "dimensions_raw": "",
        "width_cm":      None,
        "height_cm":     None,
        "pixel_width":   None,
        "pixel_height":  None,
        "image_url_full":  image_full,
        "image_url_small": image_small,
        "detail_url":    public_url,
        "public_url":    public_url,
        "department":    institution,
        "tags":          _all_strings_from_field(
                             item.get("edmConceptPrefLabelLangAware") or {}
                         )[:6],   # keep at most 6 concept tags
        "country":       (item.get("country") or [""])[0],
        "period":        "",
        "credit_line":   institution,
        "rights":        rights,
        "description":   desc,
        "_image_id":     None,
    }


# ---------------------------------------------------------------------------
# Main fetch entry point
# ---------------------------------------------------------------------------

def fetch_all_candidates(
    api_key: str = None,
    limit: int = None,
    queries: list = None,
) -> list:
    """
    Run landscape queries and return normalised records.

    Args:
        api_key: Europeana API key. Defaults to config.EUROPEANA_API_KEY.
        limit:   Max records to return. Defaults to config.MAX_CANDIDATES_PER_SOURCE.
        queries: Which query list to use. Defaults to LANDSCAPE_QUERIES (wc + oil).
                 Pass WATERCOLOR_QUERIES or OIL_QUERIES to target a single medium.
    """
    if api_key is None:
        api_key = config.EUROPEANA_API_KEY
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE
    if queries is None:
        queries = LANDSCAPE_QUERIES

    if not api_key:
        print("[Europeana] No API key — skipping. Set EUROPEANA_API_KEY in .env")
        return []

    print("[Europeana] Starting candidate fetch...")
    session = _session()
    seen_ids = set()
    records = []

    for query in queries:
        if len(records) >= limit:
            break
        print(f"  [Europeana] Searching: {query!r}")

        start = 1
        for _ in range(config.EUROPEANA_MAX_PAGES_PER_QUERY):
            if len(records) >= limit:
                break

            data = search(query, api_key, start, session)
            items = data.get("items") or []
            if not items:
                break

            for item in items:
                if len(records) >= limit:
                    break
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
