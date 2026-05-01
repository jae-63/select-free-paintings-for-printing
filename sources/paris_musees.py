"""
sources/paris_musees.py

Client for Paris Musées Collections API (apicollections.parismusees.paris.fr).
Covers the 14 municipal museums of the City of Paris, including:
  - Petit Palais (Musée des Beaux-Arts de la Ville de Paris) — strongest
    collection of 19th-century French landscape painting
  - Musée Carnavalet — Paris history and topographic views
  - Musée de la Vie Romantique — Romantic-era paintings
  - Musée Cognacq-Jay — 18th-century decorative arts
  - Musée Cernuschi — Asian art
  - Musée d'Art Moderne de Paris — modern works

Note: the Musée d'Orsay is a NATIONAL museum (not municipal) and is
covered by the Wikimedia Commons categories in sources/wikimedia.py.

All images are CC0 / public domain, minimum 3 000 × 3 000 px at 300 DPI.

Authentication
--------------
Register at https://apicollections.parismusees.paris.fr/user/register,
generate a token under My Account → Auth Tokens, and add:

    PARIS_MUSEES_API_TOKEN=<your-token>

to .env.  Without a token this source is skipped with a warning.
Daily quota: 1 000 requests per token.

API notes
---------
- GraphQL endpoint: https://apicollections.parismusees.paris.fr/graphql
- POST with JSON body {"query": ..., "variables": ...}
- Auth header: auth-token: <token>
- Field names follow Drupal 8 GraphQL module v3 conventions (camelCase,
  entity-reference fields expose { entity { name } }).
- fieldImage may be a direct File entity (url/width/height) or a Media
  entity (entity → MediaImage → fieldMediaImage → url/width/height);
  _extract_image() tries both structures.
"""

import os
import re
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_GRAPHQL_URL = "https://apicollections.parismusees.paris.fr/graphql"

# ---------------------------------------------------------------------------
# Local pre-filter vocabulary (French museum metadata)
# ---------------------------------------------------------------------------

# Theme values that indicate landscape-suitable subjects.
# Matched as substrings of lowercased fieldOeuvreThemeRepresente names.
_LANDSCAPE_THEME_FRAGMENTS = (
    "paysage", "marine", "nature", "campagne", "forêt", "rivière",
    "montagne", "mer ", "côte", "jardin", "fleur", "vue ", "panorama",
    "architecture", "topograph",
)

# Medium/material substrings that indicate a painted work.
# Checked against lowercased fieldMateriau + fieldTechnique concatenated.
_PAINTING_MEDIA_FRAGMENTS = (
    "huile", "aquarelle", "gouache", "tempera", "détrempe",
    "peinture", "encre", "pastel", "oil", "watercolou", "watercolor",
)

# ---------------------------------------------------------------------------
# GraphQL query
# ---------------------------------------------------------------------------

_QUERY = """
query ParisMuseesLandscapes($limit: Int!, $offset: Int!) {
  nodeQuery(
    limit: $limit,
    offset: $offset,
    filter: {
      conditions: [
        { field: "status", value: "1" }
        { field: "type",   value: "oeuvre" }
      ]
    }
  ) {
    count
    entities {
      ... on NodeOeuvre {
        title
        absolutePath
        fieldArtiste                { entity { name } }
        fieldMateriau               { entity { name } }
        fieldTechnique              { entity { name } }
        fieldOeuvreThemeRepresente  { entity { name } }
        fieldMillesime
        fieldMusee                  { entity { name } }
        fieldImage {
          url
          width
          height
          alt
          entity {
            ... on MediaImage {
              fieldMediaImage { url width height }
            }
          }
        }
      }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    token = getattr(config, "PARIS_MUSEES_API_TOKEN", "")
    s = requests.Session()
    s.headers.update({
        "User-Agent":   config.HTTP_USER_AGENT,
        "Content-Type": "application/json",
        "Accept":       "application/json",
    })
    if token:
        s.headers["auth-token"] = token
    return s


def _fetch_page(offset: int, page_size: int, session: requests.Session) -> dict:
    payload = {
        "query":     _QUERY,
        "variables": {"limit": page_size, "offset": offset},
    }
    try:
        resp = session.post(_GRAPHQL_URL, json=payload, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [ParisMus] API error at offset={offset}: {e}")
        return {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity_names(field_list: list) -> list:
    """Extract name strings from [{ entity: { name: ... } }, ...] entries."""
    out = []
    for item in (field_list or []):
        entity = (item or {}).get("entity") or {}
        name = (entity.get("name") or "").strip()
        if name:
            out.append(name)
    return out


def _extract_image(field_image: dict) -> tuple:
    """
    Return (full_url, small_url, width, height) from a fieldImage value.
    Handles both the direct-File schema and the Media entity schema.
    """
    if not field_image:
        return "", "", 0, 0

    # Direct File field (url/width/height at top level)
    url = field_image.get("url", "")
    w   = int(field_image.get("width") or 0)
    h   = int(field_image.get("height") or 0)
    if url and w:
        return url, url, w, h

    # Media entity fallback (entity → MediaImage → fieldMediaImage)
    entity    = (field_image.get("entity") or {})
    media_img = (entity.get("fieldMediaImage") or {})
    url = media_img.get("url", "")
    w   = int(media_img.get("width") or 0)
    h   = int(media_img.get("height") or 0)
    if url and w:
        return url, url, w, h

    return "", "", 0, 0


def _is_landscape_candidate(node: dict) -> bool:
    """
    Return False only when we can positively identify this as a
    non-landscape work (portrait, sculpture, fashion item, etc.).
    When metadata is absent, return True (trust downstream filtering).
    """
    themes = [n.lower() for n in _entity_names(node.get("fieldOeuvreThemeRepresente") or [])]
    if themes:
        if not any(frag in t for frag in _LANDSCAPE_THEME_FRAGMENTS for t in themes):
            return False

    mat_names  = _entity_names(node.get("fieldMateriau")  or [])
    tech_names = _entity_names(node.get("fieldTechnique") or [])
    medium_low = " ".join(mat_names + tech_names).lower()
    if medium_low:
        if not any(frag in medium_low for frag in _PAINTING_MEDIA_FRAGMENTS):
            return False

    return True

# ---------------------------------------------------------------------------
# Record normalisation
# ---------------------------------------------------------------------------

def normalize_record(node: dict) -> dict | None:
    """Convert a Paris Musées GraphQL node into our standard record schema."""
    title = (node.get("title") or "").strip()
    if not title:
        return None

    full_url, small_url, px_w, px_h = _extract_image(node.get("fieldImage") or {})
    if not full_url:
        return None
    if not px_w or not px_h:
        return None
    # Basic sanity check — full resolution check happens in apply_filters
    if px_w < 1000 and px_h < 1000:
        return None

    mat_names  = _entity_names(node.get("fieldMateriau")  or [])
    tech_names = _entity_names(node.get("fieldTechnique") or [])
    medium = " ".join(mat_names + tech_names).strip().lower()

    artist_names = _entity_names(node.get("fieldArtiste") or [])
    artist = artist_names[0] if artist_names else "Unknown"
    # Strip parenthetical date ranges sometimes appended by Drupal
    artist = re.sub(r"\s*\(\d{4}[–-]\d{0,4}\)$", "", artist).strip() or "Unknown"

    date = (node.get("fieldMillesime") or "").strip()
    # Keep only the year portion if a longer string slips through
    m = re.search(r"\b(1[0-9]{3}|20[012][0-9])\b", date)
    date = m.group(1) if m else date[:10]

    museum_names = _entity_names(node.get("fieldMusee") or [])
    department = museum_names[0] if museum_names else ""

    themes = [n.lower() for n in _entity_names(node.get("fieldOeuvreThemeRepresente") or [])]

    path       = (node.get("absolutePath") or "").strip()
    detail_url = f"https://parismuseescollections.paris.fr{path}" if path else ""
    source_id  = path.strip("/")

    return {
        "source":          "paris_musees",
        "source_id":       source_id,
        "title":           title,
        "artist":          artist,
        "date":            date,
        "medium":          medium,
        "dimensions_raw":  "",
        "width_cm":        None,
        "height_cm":       None,
        "pixel_width":     px_w,
        "pixel_height":    px_h,
        "image_url_full":  full_url,
        "image_url_small": small_url,
        "detail_url":      detail_url,
        "public_url":      detail_url,
        "department":      department,
        "tags":            themes,
        "country":         "France",
        "period":          "",
        "credit_line":     "",
        "rights":          "CC0 Public Domain",
        "description":     "",
        "_image_id":       None,
    }

# ---------------------------------------------------------------------------
# Main fetch entry point
# ---------------------------------------------------------------------------

def fetch_all_candidates(limit: int = None) -> list:
    """
    Fetch Paris Musées paintings with landscape themes via the GraphQL API.
    Requires PARIS_MUSEES_API_TOKEN in environment / .env.
    """
    token = getattr(config, "PARIS_MUSEES_API_TOKEN", "")
    if not token:
        print("[ParisMus] PARIS_MUSEES_API_TOKEN not set — skipping this source.")
        print("           Register at https://apicollections.parismusees.paris.fr/user/register")
        return []

    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    page_size = getattr(config, "PARIS_MUSEES_PAGE_SIZE", 100)
    delay     = getattr(config, "PARIS_MUSEES_REQUEST_DELAY", 1.0)

    print("[ParisMus] Starting candidate fetch from Paris Musées API…")
    session  = _session()
    seen_ids = set()
    records  = []
    offset   = 0
    total    = None

    while len(records) < limit:
        data = _fetch_page(offset, page_size, session)
        errors = data.get("errors")
        if errors:
            print(f"  [ParisMus] GraphQL errors: {errors}")
            break

        query_result = (data.get("data") or {}).get("nodeQuery") or {}

        if total is None:
            total = int(query_result.get("count") or 0)
            print(f"  [ParisMus] Total oeuvre nodes reported: {total:,}")

        entities = query_result.get("entities") or []
        if not entities:
            break

        for node in entities:
            if not node:
                continue
            path = (node.get("absolutePath") or "").strip("/")
            if path in seen_ids:
                continue
            seen_ids.add(path)

            if not _is_landscape_candidate(node):
                continue

            rec = normalize_record(node)
            if rec:
                records.append(rec)
                if len(records) >= limit:
                    break

        offset += len(entities)
        if offset % 1000 == 0:
            print(f"  [ParisMus] Scanned {offset:,} / {total:,}, kept {len(records)}")

        if offset >= (total or 0):
            break

        time.sleep(delay)

    print(f"[ParisMus] Fetched {len(records)} candidate records.")
    return records
