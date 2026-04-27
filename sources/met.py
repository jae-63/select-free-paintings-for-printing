"""
sources/met.py

Client for The Metropolitan Museum of Art Open Access API.
No API key required. All parameters come from config.py.

Docs: https://metmuseum.github.io/
"""

import random
import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

# Max IDs to sample from a single query result set.
# Queries like "oil canvas landscape" can return 4000+ IDs; sampling keeps
# us polite and ensures coverage across all queries rather than blowing the
# entire limit on one query's results.
MET_MAX_IDS_PER_QUERY = 80   # most targeted queries return <80 anyway

BASE_URL = "https://collectionapi.metmuseum.org/public/collection/v1"

# Search queries for the Met API.
# Without a medium filter, queries need to be specific enough to surface
# paintings and works on paper rather than sculptures, textiles, etc.
# The Met's full-text search covers title, artist, medium, and tags.
# Pairing a landscape subject with a medium term (watercolor, oil) works
# well because the medium word appears in the Met's own `medium` metadata
# field, which is indexed for full-text search even though the `medium`
# filter parameter doesn't work reliably.
# Met full-text search indexes title, artist, medium, tags, and provenance.
# Queries must be specific enough to avoid matching unrelated fields.
# "oil canvas landscape" matches 4000+ records because "canvas" and "landscape"
# appear in provenance text for unrelated works — avoid multi-word oil queries.
#
# Strategy: use medium-specific queries for watercolors (small, precise result
# sets), and use department+tag filtering for oils via departmentId.
# Met department IDs:
#   11 = European Paintings
#   21 = American Paintings and Sculpture  (note: also covers drawings)
#    9 = Drawings and Prints
LANDSCAPE_QUERIES = [
    # Watercolor queries — "watercolor" in medium field keeps sets small & precise
    "watercolor landscape",
    "watercolor seascape",
    "watercolor river landscape",
    "watercolor coastal",
    "watercolor mountain landscape",
    "watercolor harbor",
    "watercolor valley landscape",
    "watercolor sunset landscape",
    "watercolor lake landscape",
    "watercolor forest landscape",
    "watercolor pastoral landscape",
    "gouache landscape",
    "aquarelle landscape",
    # Oil — use distinctive style/school terms that appear in Met tags & dept fields
    # These return smaller, more relevant sets than generic "oil painting landscape"
    "luminist landscape oil",
    "hudson river school landscape",
    "barbizon landscape oil",
    "plein air landscape oil",
    "impressionist landscape oil",
    "tonalist landscape",
    "dutch golden age landscape",
    "flemish landscape oil",
    "corot landscape",
    "inness landscape",
    "homer landscape oil",
    "sargent landscape oil",
]

# The Met API's `medium` search parameter requires exact matches against their
# internal controlled vocabulary, which is undocumented and silently returns 0
# results for unrecognised strings. We therefore do NOT filter by medium at
# search time. Instead we fetch all public-domain results for each landscape
# query and let our own classify_medium() handle medium filtering post-fetch.
# This is the same approach used for Europeana.
#
# To narrow results at search time you can use `hasImages=true` (already
# applied) and `departmentId` — Met department IDs for relevant depts:
#   11 = European Paintings, 21 = Drawings and Prints, 13 = Greek/Roman,
#    9 = Drawings & Prints, 3 = Ancient Near Eastern Art
# We leave departmentId open to cast the widest net.


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


# Met department IDs for Western paintings and works on paper.
# Filtering to these departments excludes Islamic Art, Asian Art, Ancient
# Near Eastern Art etc. which match watercolor queries but are manuscript
# illuminations, not landscape paintings suitable for canvas printing.
#   11 = European Paintings
#   21 = American Paintings and Sculpture
#    9 = Drawings and Prints  (includes watercolors on paper)
MET_DEPARTMENT_IDS = [11, 21, 9]


def search(query: str, session: requests.Session) -> list:
    """
    Return object IDs matching query, restricted to Western painting departments.
    Runs one search per department ID and merges results to stay focused on
    paintings and works on paper rather than Islamic/Asian manuscripts.
    """
    all_ids = []
    seen = set()
    for dept_id in MET_DEPARTMENT_IDS:
        params = {
            "q": query,
            "isPublicDomain": "true",
            "hasImages": "true",
            "departmentId": dept_id,
        }
        url = f"{BASE_URL}/search"
        try:
            resp = session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
            resp.raise_for_status()
            ids = resp.json().get("objectIDs") or []
            for oid in ids:
                if oid not in seen:
                    seen.add(oid)
                    all_ids.append(oid)
        except Exception as e:
            print(f"  [Met] Search error for {query!r} dept {dept_id}: {e}")
    return all_ids


def get_object(object_id: int, session: requests.Session) -> dict | None:
    """
    Fetch a single object's metadata.

    403 handling:
      - First 403: wait 5s and retry (transient rate limit)
      - Second 403: wait 15s and retry
      - Third 403: give up and skip — object is likely permanently restricted
        despite appearing in public-domain search results (a known Met API quirk)
    404: skip silently.
    Other errors: retry with backoff up to HTTP_RETRIES times.
    """
    url = f"{BASE_URL}/objects/{object_id}"
    forbidden_count = 0
    for attempt in range(config.HTTP_RETRIES + 2):  # extra attempts for 403 recovery
        try:
            resp = session.get(url, timeout=config.HTTP_TIMEOUT)
            if resp.status_code == 404:
                return None
            if resp.status_code == 403:
                forbidden_count += 1
                if forbidden_count >= 3:
                    # Permanently restricted — skip silently
                    return None
                wait = 5 * forbidden_count
                print(f"  [Met] 403 on {object_id} (attempt {forbidden_count}), waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < config.HTTP_RETRIES - 1:
                time.sleep(2 ** min(attempt, 4))
            else:
                print(f"  [Met] Fetch error for {object_id}: {e}")
                return None
    return None


def normalize_record(raw: dict) -> dict | None:
    """Convert raw Met API response to normalized record. Returns None if unusable."""
    if not raw:
        return None
    if not raw.get("isPublicDomain"):
        return None
    if not raw.get("primaryImage"):
        return None

    return {
        "source": "met",
        "source_id": str(raw.get("objectID", "")),
        "title": raw.get("title", "Untitled"),
        "artist": raw.get("artistDisplayName", "Unknown"),
        "date": raw.get("objectDate", ""),
        "medium": raw.get("medium", ""),
        "dimensions_raw": raw.get("dimensions", ""),
        "width_cm": None,
        "height_cm": None,
        "pixel_width": None,
        "pixel_height": None,
        "image_url_full": raw.get("primaryImage", ""),
        "image_url_small": raw.get("primaryImageSmall", ""),
        "detail_url": raw.get("objectURL", ""),
        "public_url": raw.get("objectURL", ""),
        "department": raw.get("department", ""),
        "tags": [t.get("term", "") for t in (raw.get("tags") or [])],
        "country": raw.get("country", ""),
        "period": raw.get("period", ""),
        "credit_line": raw.get("creditLine", ""),
        "rights": "CC0 Public Domain",
        "description": "",
        "_image_id": None,  # Met doesn't use IIIF image IDs
    }


# Checkpoint: save partial results every N records so long runs
# aren't lost to a network error or rate-limit shutdown.
MET_CHECKPOINT_INTERVAL = 50
MET_CHECKPOINT_FILE = "/tmp/met_checkpoint.json"


def fetch_all_candidates(limit: int = None) -> list:
    """
    Run all landscape queries and return normalized records.
    Deduplicates by objectID. Writes a checkpoint file every
    MET_CHECKPOINT_INTERVAL records so partial progress is not lost.

    Args:
        limit: Max records to return. Defaults to config.MAX_CANDIDATES_PER_SOURCE.
    """
    import json
    from pathlib import Path

    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    # Resume from checkpoint if present
    checkpoint = Path(MET_CHECKPOINT_FILE)
    if checkpoint.exists():
        try:
            saved = json.loads(checkpoint.read_text())
            records  = saved.get("records", [])
            seen_ids = set(saved.get("seen_ids", []))
            print(f"[Met] Resuming from checkpoint: {len(records)} records already fetched.")
        except Exception:
            records, seen_ids = [], set()
    else:
        records, seen_ids = [], set()

    print("[Met] Starting candidate fetch...")
    session = _session()

    for query in LANDSCAPE_QUERIES:
        if len(records) >= limit:
            break
        print(f"  [Met] Searching: {query!r}")
        ids = search(query, session)
        print(f"         → {len(ids)} results")

        # Sample randomly from large result sets so we get variety across
        # all queries rather than exhausting the limit on one query.
        if len(ids) > MET_MAX_IDS_PER_QUERY:
            ids = random.sample(ids, MET_MAX_IDS_PER_QUERY)

        for obj_id in ids:
            if len(records) >= limit:
                break
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)

            raw = get_object(obj_id, session)
            if raw is None:
                continue
            rec = normalize_record(raw)
            if rec:
                records.append(rec)
                # Checkpoint periodically
                if len(records) % MET_CHECKPOINT_INTERVAL == 0:
                    checkpoint.write_text(json.dumps(
                        {"records": records, "seen_ids": list(seen_ids)},
                        ensure_ascii=False,
                    ))
                    print(f"  [Met] Checkpoint saved ({len(records)} records)")

            time.sleep(config.MET_REQUEST_DELAY)

    # Clear checkpoint on successful completion
    if checkpoint.exists():
        checkpoint.unlink()

    print(f"[Met] Fetched {len(records)} candidate records.")
    return records
