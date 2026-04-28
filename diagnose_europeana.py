#!/usr/bin/env python3
"""
diagnose_europeana.py

Fetches a sample of Europeana records and prints the raw field contents
so we can see what's actually in medium, description, title, etc.

Usage:
    python diagnose_europeana.py
    python diagnose_europeana.py --query "landscape watercolor" --n 20
"""

import argparse
import json
import sys
import requests
import config

SEARCH_URL = "https://api.europeana.eu/record/v2/search.json"


def fetch_raw(query: str, n: int) -> list:
    params = {
        "query":        query,
        "wskey":        config.EUROPEANA_API_KEY,
        "reusability":  "open",
        "media":        "true",
        "thumbnail":    "true",
        "type":         "IMAGE",
        "rows":         min(n, 100),
        "profile":      "rich",
    }
    resp = requests.get(SEARCH_URL, params=params, timeout=20,
                        headers={"User-Agent": config.HTTP_USER_AGENT})
    resp.raise_for_status()
    return resp.json().get("items", [])


def extract(item: dict, key: str) -> str:
    """Pull a value out whether it's a LangAware dict, list, or scalar."""
    val = item.get(key) or item.get(key + "LangAware") or ""
    if isinstance(val, dict):
        for lang in ("en", "fr", "de", "nl", "it", "es"):
            if lang in val and val[lang]:
                return str(val[lang])
        return str(next(iter(val.values()), ""))
    if isinstance(val, list):
        return str(val[:3])   # first 3 entries
    return str(val)


FIELDS_TO_SHOW = [
    # What we use for medium classification
    "dcFormat", "dcFormatLangAware",
    "dcType", "dcTypeLangAware",
    # What we use for title / artist
    "title", "dcTitleLangAware",
    "dcCreator", "dcCreatorLangAware",
    # Description — sometimes medium lives here
    "dcDescription", "dcDescriptionLangAware",
    # Europeana subject / concept tags
    "edmConceptPrefLabelLangAware",
    # What type of cultural object Europeana thinks this is
    "edmConceptLabel",
    "dataProvider",
    "rights",
    # Does it have a usable image?
    "edmPreview", "edmIsShownBy",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--query", default="landscape watercolor")
    p.add_argument("--n", type=int, default=15, help="Number of records to inspect")
    p.add_argument("--json", action="store_true", help="Dump full raw JSON instead")
    args = p.parse_args()

    if not config.EUROPEANA_API_KEY:
        print("ERROR: EUROPEANA_API_KEY not set in .env / environment.")
        sys.exit(1)

    print(f"Fetching {args.n} records for query: {args.query!r}\n")
    items = fetch_raw(args.query, args.n)
    print(f"Got {len(items)} items.\n")

    if args.json:
        print(json.dumps(items[:5], indent=2, ensure_ascii=False))
        return

    # Tally what's in each field across all records
    field_values: dict[str, list] = {f: [] for f in FIELDS_TO_SHOW}
    for item in items:
        for f in FIELDS_TO_SHOW:
            v = item.get(f)
            if v:
                field_values[f].append(v)

    print("=" * 70)
    print(f"FIELD COVERAGE across {len(items)} records")
    print("=" * 70)
    for f in FIELDS_TO_SHOW:
        vals = field_values[f]
        pct = 100 * len(vals) / len(items) if items else 0
        print(f"\n{f}  ({len(vals)}/{len(items)} records, {pct:.0f}% coverage)")
        if vals:
            # Show up to 5 representative values
            shown = set()
            for v in vals[:20]:
                s = str(v)[:120]
                if s not in shown:
                    print(f"    {s}")
                    shown.add(s)
                if len(shown) >= 5:
                    break

    # Now show per-record summary for the first N items
    print("\n" + "=" * 70)
    print("PER-RECORD SUMMARY (first 10)")
    print("=" * 70)
    for i, item in enumerate(items[:10]):
        title   = extract(item, "dcTitle") or extract(item, "title")
        creator = extract(item, "dcCreator")
        fmt     = extract(item, "dcFormat")
        typ     = extract(item, "dcType")
        desc    = extract(item, "dcDescription")[:80] if extract(item, "dcDescription") else ""
        has_img = bool(item.get("edmPreview") or item.get("edmIsShownBy"))
        print(f"\n  [{i+1}] {title}")
        print(f"       creator : {creator}")
        print(f"       dcFormat: {fmt}")
        print(f"       dcType  : {typ}")
        print(f"       desc    : {desc}")
        print(f"       image   : {'yes' if has_img else 'NO IMAGE'}")


if __name__ == "__main__":
    main()
