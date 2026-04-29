#!/usr/bin/env python3
"""
merge_candidates.py

Merges per-source candidate JSON files (from separate fetch_candidates.py runs)
into a single final selection of N watercolors + M smooth oils.

Deduplicates by image URL. Mixes sources so the final list isn't all-Met or
all-AIC. Prioritises records with known artists and higher pixel resolution.

Usage:
    python merge_candidates.py \\
        --inputs candidates_met.json candidates_aic.json candidates_europeana.json \\
        --watercolor-target 240 \\
        --oil-target 60 \\
        --output candidates_final.json

Options:
    --inputs               One or more candidates JSON files (in priority order)
    --watercolor-target    Target watercolor count  (default: config.WATERCOLOR_TARGET)
    --oil-target           Target smooth oil count  (default: config.OIL_TARGET)
    --output               Output JSON file         (default: config.DEFAULT_CANDIDATES_FILE)
    --require-artist       Exclude records where artist is "Unknown"
    --shuffle              Shuffle within each source before merging (adds variety)
    --sort-by              Resolution or source (default: resolution)
    --max-near-duplicates  Max images per (source, title) near-dup group
                           (default: config.MAX_NEAR_DUPLICATES)
    --no-brightness-filter Skip the per-thumbnail brightness filter
    --brightness-threshold Fraction of median brightness below which to exclude
                           (default: config.BRIGHTNESS_FILTER_THRESHOLD)
    --verbose              Print each accepted/rejected record
"""

import argparse
import io
import json
import random
import re
import statistics
import warnings
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import config


# ---------------------------------------------------------------------------
# Deduplication key
# ---------------------------------------------------------------------------

def dedup_key(rec: dict) -> str:
    """
    Stable identity for a record across sources.
    Prefer source_id, fall back to image URL.
    """
    source    = rec.get("source", "")
    source_id = rec.get("source_id", "")
    if source and source_id:
        return f"{source}:{source_id}"
    return rec.get("image_url_full", "") or rec.get("image_url_small", "") or str(rec)


# ---------------------------------------------------------------------------
# Record scoring (for ranking within each category)
# ---------------------------------------------------------------------------

def record_score(rec: dict) -> tuple:
    """
    Returns a sort key (higher = better).
    Priority:
      1. Known artist (not "Unknown") — strongly preferred
      2. Pixel width (higher = more print-ready)
      3. Has physical dimensions (aspect ratio confirmed)
      4. Source priority: aic > met > europeana
         (AIC tends to have the most reliable metadata)
    """
    artist          = rec.get("artist", "Unknown")
    has_artist      = 0 if artist.strip().lower() in ("unknown", "", "unknown artist") else 1
    px_w            = rec.get("pixel_width") or 0
    has_dims        = 1 if (rec.get("width_cm") or rec.get("height_cm")) else 0
    source_priority = {"aic": 2, "met": 1, "europeana": 0}.get(rec.get("source", ""), 0)

    return (has_artist, px_w, has_dims, source_priority)


# ---------------------------------------------------------------------------
# Near-duplicate cap
# ---------------------------------------------------------------------------

def _norm_title(title: str) -> str:
    """Normalise title for near-duplicate grouping."""
    t = title.lower()
    t = re.sub(r"[^\w\s-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def apply_near_dup_cap(records: list, max_per_group: int) -> list:
    """
    Keep at most max_per_group records per (source, normalised-title) group.
    Records must already be sorted in preference order — the first N are kept.
    """
    counts: dict[str, int] = defaultdict(int)
    out     = []
    dropped = 0
    for rec in records:
        key = f"{rec.get('source','?')}||{_norm_title(rec.get('title',''))}"
        if counts[key] < max_per_group:
            counts[key] += 1
            out.append(rec)
        else:
            dropped += 1
    if dropped:
        print(f"Near-dup cap ({max_per_group}/group): removed {dropped} records")
    return out


# ---------------------------------------------------------------------------
# Brightness filter
# ---------------------------------------------------------------------------

def _fetch_brightness(rec: dict, session: requests.Session) -> float | None:
    """
    Download the small thumbnail and return mean grayscale brightness (0–1).
    Returns None on any failure; the caller keeps the record in that case.
    """
    url = rec.get("image_url_small") or rec.get("image_url_full", "")
    if not url:
        return None
    try:
        from PIL import Image
        resp = session.get(
            url, timeout=15,
            headers={"User-Agent": config.HTTP_USER_AGENT},
        )
        resp.raise_for_status()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            img = Image.open(io.BytesIO(resp.content)).convert("L")
        pixels = list(img.getdata())
        return sum(pixels) / (len(pixels) * 255.0)
    except Exception:
        return None


def apply_brightness_filter(
    records: list,
    threshold_ratio: float,
    workers: int = 8,
    verbose: bool = False,
) -> list:
    """
    Remove records whose thumbnail brightness is below threshold_ratio × median.
    Uses parallel downloads. Records with unmeasurable thumbnails are kept.
    """
    print(
        f"Brightness filter: fetching {len(records)} thumbnails "
        f"(drop if < {threshold_ratio:.0%} of median)…"
    )

    session = requests.Session()
    session.headers["User-Agent"] = config.HTTP_USER_AGENT

    brightnesses: dict[int, float | None] = {}

    def _work(i: int, rec: dict):
        return i, _fetch_brightness(rec, session)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_work, i, rec): i for i, rec in enumerate(records)}
        done = 0
        for fut in as_completed(futures):
            i, b = fut.result()
            brightnesses[i] = b
            done += 1
            if done % 100 == 0 or done == len(records):
                print(f"  … {done}/{len(records)} thumbnails fetched")

    valid = [b for b in brightnesses.values() if b is not None]
    if not valid:
        print("  WARNING: no brightness values obtained — skipping brightness filter")
        return records

    median_b = statistics.median(valid)
    cutoff   = threshold_ratio * median_b
    print(f"  Median brightness: {median_b:.3f}  |  cutoff: {cutoff:.4f}")

    out     = []
    dropped = 0
    for i, rec in enumerate(records):
        b = brightnesses.get(i)
        if b is None or b >= cutoff:
            out.append(rec)
        else:
            dropped += 1
            if verbose:
                print(f"  [DIM] {rec.get('artist','?')} — {rec.get('title','?')}  "
                      f"brightness={b:.3f}")

    print(f"  Brightness filter: removed {dropped} dim records, kept {len(out)}")
    return out


# ---------------------------------------------------------------------------
# Main merge logic
# ---------------------------------------------------------------------------

def load_file(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"  WARNING: {path} not found — skipping.")
        return {"watercolors": [], "smooth_oils": [], "meta": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    wc  = len(data.get("watercolors", []))
    oil = len(data.get("smooth_oils", []))
    print(f"  Loaded {path}: {wc} watercolors, {oil} smooth oils")
    return data


def merge(
    input_files: list,
    watercolor_target: int,
    oil_target: int,
    require_artist: bool = False,
    shuffle: bool = False,
    max_near_duplicates: int = 3,
    brightness_filter: bool = True,
    brightness_threshold: float = 0.30,
    verbose: bool = False,
) -> dict:
    all_wc  = []
    all_oil = []

    for path in input_files:
        data = load_file(path)
        all_wc.extend(data.get("watercolors", []))
        all_oil.extend(data.get("smooth_oils", []))

    print(f"\nTotal before dedup: {len(all_wc)} watercolors, {len(all_oil)} smooth oils")

    # --- Deduplicate ---
    def dedup(records: list) -> list:
        seen = set()
        out  = []
        for rec in records:
            k = dedup_key(rec)
            if k in seen:
                continue
            seen.add(k)
            out.append(rec)
        return out

    all_wc  = dedup(all_wc)
    all_oil = dedup(all_oil)
    print(f"After dedup:        {len(all_wc)} watercolors, {len(all_oil)} smooth oils")

    # --- Optional artist filter ---
    if require_artist:
        before_wc  = len(all_wc)
        before_oil = len(all_oil)
        all_wc  = [r for r in all_wc  if r.get("artist","").strip().lower() not in ("unknown","","unknown artist")]
        all_oil = [r for r in all_oil if r.get("artist","").strip().lower() not in ("unknown","","unknown artist")]
        print(f"After artist filter:{len(all_wc)} watercolors (-{before_wc-len(all_wc)}), "
              f"{len(all_oil)} smooth oils (-{before_oil-len(all_oil)})")

    # --- Sort by quality score ---
    if shuffle:
        random.shuffle(all_wc)
        random.shuffle(all_oil)
    else:
        all_wc.sort(key=record_score, reverse=True)
        all_oil.sort(key=record_score, reverse=True)

    # --- Near-duplicate cap (applied after sorting so best copies are kept) ---
    if max_near_duplicates > 0:
        all_wc  = apply_near_dup_cap(all_wc,  max_near_duplicates)
        all_oil = apply_near_dup_cap(all_oil, max_near_duplicates)
        print(f"After near-dup cap: {len(all_wc)} watercolors, {len(all_oil)} smooth oils")

    # --- Brightness filter ---
    if brightness_filter:
        workers = getattr(config, "BRIGHTNESS_DOWNLOAD_WORKERS", 8)
        all_wc  = apply_brightness_filter(all_wc,  brightness_threshold, workers, verbose)
        all_oil = apply_brightness_filter(all_oil, brightness_threshold, workers, verbose)
        print(f"After brightness:   {len(all_wc)} watercolors, {len(all_oil)} smooth oils")

    # --- Trim to targets ---
    final_wc  = all_wc[:watercolor_target]
    final_oil = all_oil[:oil_target]

    if verbose:
        print("\nWatercolors selected:")
        for r in final_wc:
            print(f"  [{r.get('source','?').upper()}] {r.get('artist','?')} — {r.get('title','?')}")
        print("\nSmooth oils selected:")
        for r in final_oil:
            print(f"  [{r.get('source','?').upper()}] {r.get('artist','?')} — {r.get('title','?')}")

    # --- Source breakdown ---
    def source_counts(records):
        counts: dict[str, int] = {}
        for r in records:
            s = r.get("source", "?")
            counts[s] = counts.get(s, 0) + 1
        return counts

    wc_sources  = source_counts(final_wc)
    oil_sources = source_counts(final_oil)

    print(f"\nFinal watercolors:  {len(final_wc)} / {watercolor_target} target")
    print(f"  By source: {wc_sources}")
    print(f"Final smooth oils:  {len(final_oil)} / {oil_target} target")
    print(f"  By source: {oil_sources}")

    if len(final_wc) < watercolor_target:
        print(f"\n  Only {len(final_wc)} watercolors available (target {watercolor_target}).")
        print(f"   Try: --limit 5000 in fetch_candidates.py, or add more sources.")
    if len(final_oil) < oil_target:
        print(f"\n  Only {len(final_oil)} smooth oils available (target {oil_target}).")

    return {
        "meta": {
            "sources":                      list({r.get("source") for r in final_wc + final_oil}),
            "input_files":                  input_files,
            "watercolor_target":            watercolor_target,
            "oil_target":                   oil_target,
            "min_ratio":                    config.MIN_ASPECT_RATIO,
            "print_width_inches":           config.PRINT_WIDTH_INCHES,
            "print_dpi":                    config.PRINT_DPI,
            "min_width_px":                 config.MIN_PIXEL_WIDTH,
            "require_artist":               require_artist,
            "max_near_duplicates":          max_near_duplicates,
            "brightness_filter":            brightness_filter,
            "brightness_threshold":         brightness_threshold,
            "total_watercolors_available":  len(all_wc),
            "total_oils_available":         len(all_oil),
        },
        "watercolors": final_wc,
        "smooth_oils": final_oil,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Merge per-source candidate files into a final selection.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--inputs", nargs="+", required=True,
                   metavar="FILE",
                   help="Input candidates JSON files (in preference order)")
    p.add_argument("--watercolor-target", type=int,
                   default=config.WATERCOLOR_TARGET,
                   metavar="N")
    p.add_argument("--oil-target", type=int,
                   default=config.OIL_TARGET,
                   metavar="N")
    p.add_argument("--output", default=config.DEFAULT_CANDIDATES_FILE,
                   metavar="PATH")
    p.add_argument("--require-artist", action="store_true",
                   help="Exclude records where artist is Unknown")
    p.add_argument("--shuffle", action="store_true",
                   help="Shuffle within sources before trimming (adds variety)")
    p.add_argument("--max-near-duplicates", type=int,
                   default=getattr(config, "MAX_NEAR_DUPLICATES", 3),
                   metavar="N",
                   help="Max images per (source, title) near-duplicate group; 0 = disabled")
    p.add_argument("--no-brightness-filter", action="store_true",
                   help="Skip the per-thumbnail brightness filter")
    p.add_argument("--brightness-threshold", type=float,
                   default=getattr(config, "BRIGHTNESS_FILTER_THRESHOLD", 0.30),
                   metavar="RATIO",
                   help="Exclude records with brightness < RATIO * median (e.g. 0.30)")
    p.add_argument("--verbose", action="store_true",
                   help="Print each selected/rejected record")
    args = p.parse_args()

    print("=" * 60)
    print("Canvas Print Finder — Merge")
    print("=" * 60)
    print(f"Inputs:  {', '.join(args.inputs)}")
    print(f"Targets: {args.watercolor_target} watercolors, {args.oil_target} smooth oils")
    print(f"Require known artist: {args.require_artist}")
    print(f"Near-dup cap: {args.max_near_duplicates} per group")
    print(f"Brightness filter: {'off' if args.no_brightness_filter else f'on (threshold {args.brightness_threshold:.0%} of median)'}")
    print()

    result = merge(
        input_files          = args.inputs,
        watercolor_target    = args.watercolor_target,
        oil_target           = args.oil_target,
        require_artist       = args.require_artist,
        shuffle              = args.shuffle,
        max_near_duplicates  = args.max_near_duplicates,
        brightness_filter    = not args.no_brightness_filter,
        brightness_threshold = args.brightness_threshold,
        verbose              = args.verbose,
    )

    out_path = Path(args.output)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    total = len(result["watercolors"]) + len(result["smooth_oils"])
    print(f"\nSaved {total} candidates to: {out_path}")


if __name__ == "__main__":
    main()
