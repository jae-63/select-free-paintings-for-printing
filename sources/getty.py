"""
sources/getty.py

Client for the J. Paul Getty Museum collection via their SPARQL endpoint.
No API key required. All public domain (CC0).

Endpoint:   https://data.getty.edu/museum/collection/sparql  (POST, JSON)
IIIF images: https://media.getty.edu/iiif/image/{uuid}/full/full/0/default.jpg

The SPARQL endpoint is separate from the REST collection API (data.getty.edu/museum/api)
which is currently unreliable. SPARQL returns Linked Art / CIDOC-CRM triples.

Strategy:
  1. Batch SPARQL queries to retrieve all paintings / drawings with IIIF manifests,
     including title, artist, medium, and physical dimensions (H×W convention).
  2. Pre-filter by medium text in Python before any network I/O.
  3. Fetch each qualifying IIIF manifest to obtain pixel dimensions and image URL.
  4. Return normalized records — pixel dims are already populated, no probing needed.
"""

import re
import time
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

SPARQL_ENDPOINT = "https://data.getty.edu/museum/collection/sparql"
IIIF_IMAGE_BASE = "https://media.getty.edu/iiif/image"

# AAT type URIs used in Getty's Linked Art graph
_PAINTINGS_TYPE = "http://vocab.getty.edu/aat/300033618"  # paintings (visual works)
_DRAWINGS_TYPE  = "http://vocab.getty.edu/aat/300033936"  # drawings (includes watercolors)

# Media terms that clearly disqualify a record before fetching its IIIF manifest.
# These are ancient/non-painting works the Getty classifies under "paintings" or "drawings".
_SKIP_MEDIUM_TERMS = {
    "fresco", "mosaic", "illuminat", "gold leaf", "gold paint",
    "parchment", "vellum", "papyrus", "stucco",
}

# These lists are the "queries" the fetch loop iterates over
WATERCOLOR_QUERIES = [_DRAWINGS_TYPE]
OIL_QUERIES        = [_PAINTINGS_TYPE]

_SPARQL_BATCH = 200   # results per SPARQL page (keep below 500 for reliability)
_SPARQL_HDRS  = {
    "Accept":     "application/sparql-results+json",
    "User-Agent": "CanvasPrintFinder/1.0",
    "Content-Type": "application/x-www-form-urlencoded",
}


# ---------------------------------------------------------------------------
# SPARQL helpers
# ---------------------------------------------------------------------------

def _sparql(query: str, session: requests.Session) -> list:
    """POST a SPARQL query and return the bindings list."""
    try:
        resp = session.post(
            SPARQL_ENDPOINT,
            data={"query": query},
            headers=_SPARQL_HDRS,
            timeout=config.HTTP_TIMEOUT * 4,
        )
        resp.raise_for_status()
        return resp.json()["results"]["bindings"]
    except Exception as e:
        print(f"  [Getty] SPARQL error: {e}")
        return []


def _sparql_batch(type_uri: str, offset: int, session: requests.Session) -> list:
    """
    Fetch one paginated batch of objects of the given AAT type that have
    IIIF manifests. Returns SPARQL binding rows.
    """
    q = f"""
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX crm:  <http://www.cidoc-crm.org/cidoc-crm/>

SELECT DISTINCT ?obj ?title ?manifest ?public_url ?medium ?dims ?artist WHERE {{
  ?obj rdf:type crm:E22_Human-Made_Object .
  ?obj rdfs:label ?title .
  ?obj crm:P2_has_type <{type_uri}> .
  ?obj crm:P129i_is_subject_of ?manifest .
  ?obj crm:P129i_is_subject_of ?public_url .
  FILTER(CONTAINS(STR(?manifest), "media.getty.edu/iiif/manifest"))
  FILTER(!CONTAINS(STR(?manifest), "/manifest/3/"))
  FILTER(CONTAINS(STR(?public_url), "www.getty.edu/art/collection"))

  OPTIONAL {{
    ?obj crm:P67i_is_referred_to_by ?mat_node .
    ?mat_node rdfs:label "Materials Description" .
    ?mat_node crm:P190_has_symbolic_content ?medium .
  }}
  OPTIONAL {{
    ?obj crm:P67i_is_referred_to_by ?dim_node .
    ?dim_node rdfs:label "Dimensions Statement" .
    ?dim_node crm:P190_has_symbolic_content ?dims .
  }}
  OPTIONAL {{
    ?obj crm:P108i_was_produced_by ?prod .
    ?prod crm:P14_carried_out_by ?person .
    ?person rdfs:label ?artist .
  }}
}} LIMIT {_SPARQL_BATCH} OFFSET {offset}
"""
    return _sparql(q, session)


# ---------------------------------------------------------------------------
# IIIF manifest
# ---------------------------------------------------------------------------

def _fetch_manifest(manifest_url: str, session: requests.Session) -> dict:
    """
    Fetch a IIIF Presentation v2 manifest and return a dict with:
      iiif_service  – IIIF image service base URL
      pixel_width   – canvas width in pixels
      pixel_height  – canvas height in pixels
    Returns empty dict on failure.
    """
    try:
        resp = session.get(manifest_url, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        m = resp.json()
        seqs = m.get("sequences") or []
        if not seqs:
            return {}
        canvases = seqs[0].get("canvases") or []
        if not canvases:
            return {}
        c = canvases[0]
        imgs = c.get("images") or []
        svc = ""
        if imgs:
            svc = (imgs[0].get("resource") or {}).get("service", {}).get("@id", "")
        return {
            "iiif_service": svc,
            "pixel_width":  int(c.get("width", 0) or 0),
            "pixel_height": int(c.get("height", 0) or 0),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Dimension parsing
# ---------------------------------------------------------------------------

def _parse_dims(dims_text: str) -> tuple:
    """
    Parse Getty "Dimensions Statement" text.
    Getty records dimensions as Height × Width × Depth (European H-first convention).
    Framed entries include a depth value: "62.2 × 98.7 × 6 cm" (H × W × depth).
    We extract the first two numbers (H, W) and swap to (w_cm, h_cm).

    Examples:
      "Unframed: 83.2 × 122.9 cm"              → w=122.9, h=83.2
      "Framed: 62.2 × 98.7 × 6 cm"             → w=98.7,  h=62.2  (depth 6 ignored)
    Returns (w_cm, h_cm) or (None, None).
    """
    # Consume optional third number (frame depth) before "cm" to avoid
    # the regex anchoring on the last pair instead of the first two.
    m = re.search(
        r"(\d+\.?\d*)\s*[×x]\s*(\d+\.?\d*)(?:\s*[×x]\s*\d+\.?\d*)?\s*cm",
        dims_text,
    )
    if m:
        h_cm = float(m.group(1))   # Getty H first
        w_cm = float(m.group(2))   # then W
        return w_cm, h_cm
    m2 = re.search(
        r"(\d+\.?\d*)\s*[×x]\s*(\d+\.?\d*)(?:\s*[×x]\s*\d+\.?\d*)?\s*in",
        dims_text,
    )
    if m2:
        return float(m2.group(2)) * 2.54, float(m2.group(1)) * 2.54
    return None, None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _clean_artist(name: str) -> str:
    """Strip parenthetical aliases Getty sometimes appends: 'Canaletto (Giovanni...'."""
    # Keep as-is — the alias is informative and our exclusion list uses substrings
    return name.strip()


def _val(binding: dict, key: str) -> str:
    return binding.get(key, {}).get("value", "")


def normalize_record(row: dict, manifest_data: dict) -> dict | None:
    """
    Combine a SPARQL binding row with fetched IIIF manifest data into our
    standard normalized record. Returns None if essential data is missing.
    """
    if not manifest_data or not manifest_data.get("iiif_service"):
        return None

    svc      = manifest_data["iiif_service"]
    px_w     = manifest_data["pixel_width"]
    px_h     = manifest_data["pixel_height"]
    obj_uri  = _val(row, "obj")
    title    = _val(row, "title")
    artist   = _clean_artist(_val(row, "artist") or "Unknown")
    medium   = (_val(row, "medium") or "").lower()
    dims_raw = _val(row, "dims")
    manifest = _val(row, "manifest")
    pub_url  = _val(row, "public_url")

    if not title or not obj_uri:
        return None

    # Strip accession number from title: "The Death of Dido (55.PA.1)" → "The Death of Dido"
    title = re.sub(r"\s*\(\d+[\w\.]+\)\s*$", "", title).strip()

    w_cm, h_cm = _parse_dims(dims_raw)

    # IIIF URLs
    image_url_full  = f"{svc}/full/full/0/default.jpg"
    image_url_small = f"{svc}/full/700,/0/default.jpg"

    # Date: Getty embeds accession/catalogue number in title; extract from SPARQL
    # date is not in our current query — we'll leave it blank rather than add another join
    date = ""

    return {
        "source":          "getty",
        "source_id":       obj_uri.split("/")[-1],
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
        "detail_url":      pub_url,
        "public_url":      pub_url,
        "department":      "",
        "tags":            [],
        "country":         "",
        "period":          "",
        "credit_line":     "",
        "rights":          "CC0 Public Domain",
        "description":     "",
        "_image_id":       "",   # pixel dims populated from manifest; no probing needed
    }


# ---------------------------------------------------------------------------
# Main fetch
# ---------------------------------------------------------------------------

def fetch_all_candidates(queries: list = None, limit: int = None) -> list:
    """
    Fetch Getty Museum paintings/drawings via SPARQL + IIIF manifests.

    Args:
        queries: List of AAT type URIs to query.
                 Defaults to OIL_QUERIES + WATERCOLOR_QUERIES.
        limit:   Max records to return. Defaults to config.MAX_CANDIDATES_PER_SOURCE.
    """
    if queries is None:
        queries = OIL_QUERIES + WATERCOLOR_QUERIES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[Getty] Starting candidate fetch via SPARQL...")

    session = requests.Session()
    session.headers.update({"User-Agent": config.HTTP_USER_AGENT})

    seen_ids = set()
    records  = []

    for type_uri in queries:
        if len(records) >= limit:
            break
        print(f"  [Getty] Querying type: {type_uri.split('/')[-1]}")

        offset = 0
        while len(records) < limit:
            rows = _sparql_batch(type_uri, offset, session)
            if not rows:
                break

            # Deduplicate by object URI (multiple artists → multiple rows)
            deduped: dict[str, dict] = {}
            for row in rows:
                obj_uri = _val(row, "obj")
                if not obj_uri:
                    continue
                if obj_uri not in deduped:
                    deduped[obj_uri] = dict(row)
                elif "artist" not in deduped[obj_uri] and "artist" in row:
                    deduped[obj_uri]["artist"] = row["artist"]

            for obj_uri, row in deduped.items():
                if len(records) >= limit:
                    break
                if obj_uri in seen_ids:
                    continue
                seen_ids.add(obj_uri)

                manifest_url = _val(row, "manifest")
                if not manifest_url:
                    continue

                # Pre-filter by medium to avoid wasting manifest fetches on
                # frescoes, illuminated manuscripts, mosaics, etc.
                medium_raw = _val(row, "medium").lower()
                if medium_raw and any(t in medium_raw for t in _SKIP_MEDIUM_TERMS):
                    continue

                # Fetch IIIF manifest for pixel dims + image URL
                manifest_data = _fetch_manifest(manifest_url, session)
                if not manifest_data:
                    continue

                rec = normalize_record(row, manifest_data)
                if rec:
                    records.append(rec)

                time.sleep(config.AIC_REQUEST_DELAY)

            offset += len(rows)
            if len(rows) < _SPARQL_BATCH:
                break   # last page

            time.sleep(config.AIC_REQUEST_DELAY)

    print(f"[Getty] Fetched {len(records)} candidate records.")
    return records
