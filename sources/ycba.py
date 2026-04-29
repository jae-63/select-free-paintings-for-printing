"""
sources/ycba.py

Client for the Yale Center for British Art (YCBA) collection.
No API key required. All works are public domain.

Approach:
  1. Use OAI-PMH ListIdentifiers to page through object IDs for the
     requested set (paintings or drawings).
     OAI-PMH base: https://harvester-bl.britishart.yale.edu/oaicatmuseum/OAIHandler
  2. For each TMS object ID, fetch the IIIF v3 manifest from
     https://manifests.collections.yale.edu/ycba/obj/{tms_id}
  3. Parse the manifest JSON for title, artist, medium, date, physical
     dimensions, pixel dimensions, and full-resolution image URL.

Sets:
  ycba:ps — Paintings and Sculpture
  ycba:pd — Prints and Drawings  (watercolors live here)

Resolution note:
  YCBA scan resolution varies with painting size and digitisation era.
  Large oils (≥24" wide) tend to clear the 8000px threshold; smaller
  cabinet paintings and most watercolors typically do not. Expect moderate
  yield from oils and low yield from drawings.

Dimension convention:
  YCBA physical-description strings use H × W (height first).
"""

import re
import time
import xml.etree.ElementTree as ET
import requests
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_OAI_BASE      = "https://harvester-bl.britishart.yale.edu/oaicatmuseum/OAIHandler"
_MANIFEST_BASE = "https://manifests.collections.yale.edu/ycba/obj/"
_OAI_NS        = "http://www.openarchives.org/OAI/2.0/"

WATERCOLOR_QUERIES = ["ycba:pd"]  # Prints and Drawings
OIL_QUERIES        = ["ycba:ps"]  # Paintings and Sculpture


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.HTTP_USER_AGENT,
        "Accept":     "application/json",
    })
    return s


def _list_identifiers_page(
    oai_set: str,
    resumption_token: str | None,
    session: requests.Session,
) -> tuple[list[str], str | None]:
    """
    Fetch one OAI-PMH ListIdentifiers page.
    Returns (list_of_tms_id_strings, next_resumption_token_or_None).
    """
    if resumption_token:
        params = {"verb": "ListIdentifiers", "resumptionToken": resumption_token}
    else:
        params = {"verb": "ListIdentifiers", "metadataPrefix": "oai_dc", "set": oai_set}

    try:
        oai_timeout = getattr(config, "YCBA_OAI_TIMEOUT", 60)
        resp = session.get(
            _OAI_BASE, params=params, timeout=oai_timeout,
            headers={"Accept": "application/xml"},
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  [YCBA] OAI-PMH error (set={oai_set!r}): {e}")
        return [], None

    root = ET.fromstring(resp.text)
    ns   = {"oai": _OAI_NS}

    ids = []
    for el in root.findall(".//oai:identifier", ns):
        raw    = (el.text or "").strip()
        parts  = raw.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            ids.append(parts[1])

    rt_el      = root.find(".//oai:resumptionToken", ns)
    next_token = ((rt_el.text or "").strip() if rt_el is not None else None) or None
    return ids, next_token


def _fetch_manifest(tms_id: str, session: requests.Session) -> dict:
    url = f"{_MANIFEST_BASE}{tms_id}"
    try:
        resp = session.get(url, timeout=config.HTTP_TIMEOUT,
                           headers={"Accept": "application/json"})
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [YCBA] Manifest error for tms_id={tms_id}: {e}")
        return {}


def _manifest_label(manifest: dict) -> str:
    """Extract plain-text title from IIIF v3 label dict."""
    label = manifest.get("label", {})
    for vals in label.values():
        if vals:
            return vals[0]
    return ""


def _parse_metadata(manifest: dict) -> dict:
    """Flatten IIIF v3 metadata list into a key→value dict."""
    result = {}
    for item in manifest.get("metadata", []):
        label_dict = item.get("label", {})
        value_dict = item.get("value", {})
        l_vals = list(label_dict.values())
        v_vals = list(value_dict.values())
        if l_vals and l_vals[0] and v_vals and v_vals[0]:
            result[l_vals[0][0]] = v_vals[0][0]
    return result


def _parse_dims(desc: str) -> tuple:
    """
    Parse H × W from YCBA physical description.
    Prefers cm (parenthesised); falls back to inches.
    Returns (w_cm, h_cm) or (None, None).
    """
    # Parenthesised cm: (H × W cm)
    m = re.search(r"\((\d+\.?\d*)\s*[×x]\s*(\d+\.?\d*)\s*cm\)", desc, re.IGNORECASE)
    if m:
        return float(m.group(2)), float(m.group(1))

    # Inches: mixed fractions OK, H × W inches
    m = re.search(
        r"([\d/\s]+)\s*[×x]\s*([\d/\s]+)\s*inch", desc, re.IGNORECASE
    )
    if m:
        def _mixed(s: str) -> float:
            total = 0.0
            for p in s.strip().split():
                if "/" in p:
                    n, d = p.split("/")
                    total += float(n) / float(d)
                else:
                    total += float(p)
            return total
        h_in = _mixed(m.group(1))
        w_in = _mixed(m.group(2))
        return w_in * 2.54, h_in * 2.54

    return None, None


def normalize_record(manifest: dict, tms_id: str) -> dict | None:
    """Build a normalised record from a YCBA IIIF v3 manifest."""
    if not manifest or not manifest.get("items"):
        return None

    meta   = _parse_metadata(manifest)
    rights = meta.get("Copyright Statement", "")
    if "public domain" not in rights.lower():
        return None

    # Prefer the clean "Title" metadata field over the full manifest label,
    # which encodes the entire attribution string (artist, dates, title, date).
    title = meta.get("Title", "").strip() or _manifest_label(manifest).strip()
    if not title:
        return None

    # Strip biographical suffixes: ", born in …", ", 1769–1847", ", active 1809"
    raw_creator = meta.get("Creator", "Unknown")
    artist = re.sub(r";.*$", "", raw_creator)
    artist = re.sub(
        r",\s*(born|died|active|ca\.|circa|\d{4})\b.*$", "", artist,
        flags=re.IGNORECASE,
    ).strip() or "Unknown"

    medium = meta.get("Medium", "").strip().lower()

    # Date: try metadata first; fall back to the trailing year(s) in the label
    date = meta.get("Date", "") or meta.get("Creation Date", "")
    if not date:
        label = _manifest_label(manifest)
        dm = re.search(
            r",\s*((?:ca\.\s*|between\s+)?\d{4}(?:\s*[-–]\s*\d{4})?(?:\s+and\s+\d{4})?)\s*$",
            label,
        )
        date = dm.group(1).strip() if dm else ""

    desc_raw      = meta.get("Physical Description", "")
    w_cm, h_cm    = _parse_dims(desc_raw)

    canvas = manifest["items"][0]
    px_w   = int(canvas.get("width")  or 0)
    px_h   = int(canvas.get("height") or 0)

    full_url  = ""
    small_url = ""
    try:
        body    = canvas["items"][0]["items"][0]["body"]
        full_url = body.get("id", "")
        svc      = body.get("service", [])
        svc_id   = ""
        if isinstance(svc, list) and svc:
            svc_id = svc[0].get("id") or svc[0].get("@id", "")
        elif isinstance(svc, dict):
            svc_id = svc.get("id") or svc.get("@id", "")
        if svc_id:
            small_url = f"{svc_id}/full/500,/0/default.jpg"
        elif full_url:
            small_url = re.sub(r"/full/full/", "/full/500,/", full_url)
    except (KeyError, IndexError):
        pass

    if not full_url:
        return None

    detail_url = f"https://collections.britishart.yale.edu/objects/{tms_id}"

    return {
        "source":          "ycba",
        "source_id":       tms_id,
        "title":           title,
        "artist":          artist,
        "date":            date,
        "medium":          medium,
        "dimensions_raw":  desc_raw,
        "width_cm":        w_cm,
        "height_cm":       h_cm,
        "pixel_width":     px_w,
        "pixel_height":    px_h,
        "image_url_full":  full_url,
        "image_url_small": small_url,
        "detail_url":      detail_url,
        "public_url":      detail_url,
        "department":      meta.get("Collection", ""),
        "tags":            [],
        "country":         "United Kingdom",
        "period":          "",
        "credit_line":     meta.get("Credit Line", ""),
        "rights":          rights,
        "description":     "",
        "_image_id":       "",
    }


def fetch_all_candidates(queries: list = None, limit: int = None) -> list:
    """
    Fetch YCBA paintings/drawings via OAI-PMH identifiers + IIIF manifests.

    Args:
        queries: List of OAI-PMH set specs.
                 Defaults to OIL_QUERIES + WATERCOLOR_QUERIES.
        limit:   Max records to return.
    """
    if queries is None:
        queries = OIL_QUERIES + WATERCOLOR_QUERIES
    if limit is None:
        limit = config.MAX_CANDIDATES_PER_SOURCE

    print("[YCBA] Starting candidate fetch via OAI-PMH + IIIF manifests…")
    session  = _session()
    seen_ids = set()
    records  = []

    for oai_set in queries:
        if len(records) >= limit:
            break
        print(f"  [YCBA] Harvesting set: {oai_set!r}")

        resumption_token = None

        while len(records) < limit:
            ids, resumption_token = _list_identifiers_page(
                oai_set, resumption_token, session
            )

            if not ids:
                break

            for tms_id in ids:
                if len(records) >= limit:
                    break
                if tms_id in seen_ids:
                    continue
                seen_ids.add(tms_id)

                manifest = _fetch_manifest(tms_id, session)
                rec      = normalize_record(manifest, tms_id)
                if rec:
                    records.append(rec)

                time.sleep(getattr(config, "YCBA_REQUEST_DELAY", 0.25))

            if not resumption_token:
                break
            time.sleep(0.5)

    print(f"[YCBA] Fetched {len(records)} candidate records.")
    return records
