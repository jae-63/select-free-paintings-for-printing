#!/usr/bin/env python3
"""
fetch_candidates.py

Fetches public-domain landscape paintings from museum APIs, applies filters,
and writes a JSON file of qualifying candidates for canvas printing.

All default values come from config.py — edit that file rather than this one.

Usage:
    python fetch_candidates.py [options]

Examples:
    # Quick test run (no slow resolution probing):
    python fetch_candidates.py --no-resolution-check

    # Full run with default sources (Met + AIC):
    python fetch_candidates.py

    # Add Europeana if you have a key:
    python fetch_candidates.py --sources met aic europeana

    # Custom targets and output:
    python fetch_candidates.py --watercolor-target 40 --oil-target 10 --output test.json

    # Wider prints at higher DPI:
    python fetch_candidates.py --print-width 48 --print-dpi 300

Options:
    --sources           met aic europeana  (default: met aic)
    --watercolor-target INT   target watercolor count (default: config.WATERCOLOR_TARGET)
    --oil-target        INT   target smooth-oil count (default: config.OIL_TARGET)
    --print-width       FLOAT print width in inches   (default: config.PRINT_WIDTH_INCHES)
    --print-dpi         INT   required DPI            (default: config.PRINT_DPI)
    --min-ratio         FLOAT minimum width/height    (default: config.MIN_ASPECT_RATIO)
    --limit             INT   max candidates per src  (default: config.MAX_CANDIDATES_PER_SOURCE)
    --output            PATH  output JSON file        (default: config.DEFAULT_CANDIDATES_FILE)
    --no-resolution-check     skip pixel-width probing (faster, for testing)
    --no-vision               disable Claude vision even if key is set
    --verbose                 extra logging
"""

import argparse
import json
import sys
import time
import io
import requests
from pathlib import Path

import config
from filters import (
    classify_medium,
    check_aspect_ratio,
    check_pixel_resolution,
    parse_dimensions_from_string,
    dimensions_are_landscape,
)
from exclusions import is_excluded
from oil_classifier import is_smooth_oil, vision_status


# ---------------------------------------------------------------------------
# Resolution probing
# ---------------------------------------------------------------------------

def probe_image_resolution_url(url: str) -> tuple:
    """
    Download the first chunk of an image to read its pixel dimensions via PIL.
    Returns (width, height) or (0, 0) on failure.
    """
    try:
        from PIL import Image
        resp = requests.get(
            url, stream=True,
            timeout=config.HTTP_TIMEOUT_IMAGE,
            headers={"User-Agent": config.HTTP_USER_AGENT},
        )
        resp.raise_for_status()
        chunk = b""
        for block in resp.iter_content(config.IMAGE_PROBE_CHUNK_BYTES):
            chunk += block
            break
        resp.close()
        img = Image.open(io.BytesIO(chunk))
        return img.size  # (width, height)
    except Exception:
        return (0, 0)


def probe_iiif_dimensions(image_id: str) -> tuple:
    """
    For AIC images: query IIIF info.json for native pixel dimensions.
    Fast — no image download needed.
    Returns (width, height) or (0, 0) on failure.
    """
    url = f"https://www.artic.edu/iiif/2/{image_id}/info.json"
    try:
        resp = requests.get(
            url,
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": config.HTTP_USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("width", 0), data.get("height", 0)
    except Exception:
        return (0, 0)


# ---------------------------------------------------------------------------
# Main filtering pipeline
# ---------------------------------------------------------------------------

def apply_filters(
    records: list,
    min_ratio: float,
    min_width_px: int,
    watercolor_target: int,
    oil_target: int,
    check_resolution: bool = True,
    verbose: bool = False,
) -> dict:
    """
    Walk through all fetched records and apply:
      1. Famous-painting exclusion
      2. Medium classification (watercolor vs smooth oil vs reject)
      3. Aspect ratio check (physical dimensions first, pixel fallback)
      4. Resolution check (pixel width of downloadable image)

    Returns dict with keys 'watercolors', 'smooth_oils', 'rejected_counts'.
    """
    watercolors = []
    smooth_oils = []
    rejected = {
        "no_image":        0,
        "excluded_famous": 0,
        "wrong_medium":    0,
        "wrong_aspect":    0,
        "low_resolution":  0,
    }

    for rec in records:
        title     = rec.get("title", "")
        artist    = rec.get("artist", "")
        medium    = rec.get("medium", "")
        image_url = rec.get("image_url_full", "")
        img_small = rec.get("image_url_small", "")

        if not image_url and not img_small:
            rejected["no_image"] += 1
            continue

        # ── Famous exclusion
        if is_excluded(artist, title):
            rejected["excluded_famous"] += 1
            if verbose:
                print(f"  [famous] {artist} — {title}")
            continue

        # ── Medium classification
        med_class = classify_medium(medium)
        is_wc     = (med_class == "watercolor")
        is_oil    = (med_class == "oil")

        # Determine what we still need
        need_wc  = len(watercolors) < watercolor_target
        need_oil = len(smooth_oils) < oil_target

        if not need_wc and not need_oil:
            break   # targets met — stop early

        if not is_wc and not is_oil:
            rejected["wrong_medium"] += 1
            continue

        # Skip if we don't need this category
        if is_wc and not need_wc:
            continue
        if is_oil and not need_oil:
            continue

        # ── For oils: check smoothness (Claude vision or heuristic)
        if is_oil:
            desc = rec.get("description", "")
            thumb = img_small or image_url
            if not is_smooth_oil(artist, title, medium, image_url=thumb, description=desc):
                rejected["wrong_medium"] += 1
                if verbose:
                    print(f"  [textured oil] {artist} — {title}")
                continue

        # ── Aspect ratio (physical dimensions preferred)
        w_cm = rec.get("width_cm")
        h_cm = rec.get("height_cm")
        if not w_cm or not h_cm:
            w_cm, h_cm = parse_dimensions_from_string(rec.get("dimensions_raw", ""))
            rec["width_cm"] = w_cm
            rec["height_cm"] = h_cm

        has_physical_dims = bool(w_cm and h_cm)
        if has_physical_dims:
            if not dimensions_are_landscape(w_cm, h_cm, min_ratio):
                rejected["wrong_aspect"] += 1
                if verbose:
                    print(f"  [portrait {w_cm:.0f}×{h_cm:.0f}cm] {artist} — {title}")
                continue

        # ── Resolution check (and pixel-based aspect ratio fallback)
        px_w = rec.get("pixel_width") or 0
        px_h = rec.get("pixel_height") or 0

        if check_resolution and (px_w == 0 or px_h == 0):
            image_id = rec.get("_image_id")
            if image_id:
                px_w, px_h = probe_iiif_dimensions(image_id)
                rec["pixel_width"]  = px_w
                rec["pixel_height"] = px_h
                time.sleep(0.05)
            elif image_url:
                px_w, px_h = probe_image_resolution_url(image_url)
                rec["pixel_width"]  = px_w
                rec["pixel_height"] = px_h

        # Pixel-based aspect ratio fallback (when no physical dims)
        if not has_physical_dims and px_w and px_h:
            if not dimensions_are_landscape(px_w, px_h, min_ratio):
                rejected["wrong_aspect"] += 1
                continue

        if check_resolution and px_w > 0:
            if not check_pixel_resolution(px_w, min_width_px):
                rejected["low_resolution"] += 1
                if verbose:
                    print(f"  [low-res {px_w}px < {min_width_px}px] {artist} — {title}")
                continue

        # ── Passed all filters
        rec["_medium_class"] = "watercolor" if is_wc else "smooth_oil"

        if is_wc and len(watercolors) < watercolor_target:
            watercolors.append(rec)
            print(f"  ✓ watercolor #{len(watercolors):3d} | {artist} — {title}")
        elif is_oil and len(smooth_oils) < oil_target:
            smooth_oils.append(rec)
            print(f"  ✓ smooth oil #{len(smooth_oils):3d} | {artist} — {title}")

    return {
        "watercolors":    watercolors,
        "smooth_oils":    smooth_oils,
        "rejected_counts": rejected,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Fetch public-domain landscape paintings for canvas printing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--sources", nargs="+",
                   default=config.DEFAULT_SOURCES,
                   choices=["met", "aic", "europeana"],
                   help="Which museum APIs to query")
    p.add_argument("--watercolor-target", type=int,
                   default=config.WATERCOLOR_TARGET,
                   metavar="N",
                   help="Target number of watercolors")
    p.add_argument("--oil-target", type=int,
                   default=config.OIL_TARGET,
                   metavar="N",
                   help="Target number of smooth oil paintings")
    p.add_argument("--print-width", type=float,
                   default=config.PRINT_WIDTH_INCHES,
                   metavar="INCHES",
                   help="Print width in inches (used to compute required pixel width)")
    p.add_argument("--print-dpi", type=int,
                   default=config.PRINT_DPI,
                   metavar="DPI",
                   help="Required DPI at print width")
    p.add_argument("--min-ratio", type=float,
                   default=config.MIN_ASPECT_RATIO,
                   metavar="RATIO",
                   help="Minimum width/height aspect ratio")
    p.add_argument("--limit", type=int,
                   default=config.MAX_CANDIDATES_PER_SOURCE,
                   metavar="N",
                   help="Max candidates to fetch per source")
    p.add_argument("--output", type=str,
                   default=config.DEFAULT_CANDIDATES_FILE,
                   metavar="PATH",
                   help="Output JSON file path")
    p.add_argument("--no-resolution-check", action="store_true",
                   help="Skip pixel-width probing (faster, for testing)")
    p.add_argument("--no-vision", action="store_true",
                   help="Disable Claude vision; use heuristics for oil smoothness")
    p.add_argument("--verbose", action="store_true",
                   help="Log each rejection reason")
    return p.parse_args()


def main():
    args = parse_args()

    # Compute required pixel width from CLI args (may differ from config defaults)
    min_width_px = int(args.print_width * args.print_dpi)

    # Override vision if requested
    if args.no_vision:
        config.USE_CLAUDE_VISION = False

    print("=" * 60)
    print("Canvas Print Finder")
    print("=" * 60)
    print(f"  Sources:          {', '.join(args.sources).upper()}")
    print(f"  Watercolor target:{args.watercolor_target}")
    print(f"  Smooth oil target:{args.oil_target}")
    print(f"  Print spec:       {args.print_width}\" × {args.print_dpi} DPI")
    print(f"  Min pixel width:  {min_width_px}px")
    print(f"  Min aspect ratio: {args.min_ratio}")
    print(f"  Resolution check: {'yes' if not args.no_resolution_check else 'no (--no-resolution-check)'}")
    print(f"  Claude vision:    {vision_status()}")
    print()

    # ── Fetch
    all_records = []

    if "met" in args.sources:
        from sources.met import fetch_all_candidates
        all_records += fetch_all_candidates(limit=args.limit)

    if "aic" in args.sources:
        from sources.aic import fetch_all_candidates
        all_records += fetch_all_candidates(limit=args.limit)

    if "europeana" in args.sources:
        from sources.europeana import fetch_all_candidates, WATERCOLOR_QUERIES, OIL_QUERIES, LANDSCAPE_QUERIES
        # Use medium-targeted queries when one target is zero, to avoid
        # wasting the fetch budget on the wrong medium type.
        if args.watercolor_target == 0 and args.oil_target > 0:
            euro_queries = OIL_QUERIES
        elif args.oil_target == 0 and args.watercolor_target > 0:
            euro_queries = WATERCOLOR_QUERIES
        else:
            euro_queries = LANDSCAPE_QUERIES
        all_records += fetch_all_candidates(limit=args.limit, queries=euro_queries)

    print(f"\nTotal raw records fetched: {len(all_records)}")

    # ── Filter
    print("\nApplying filters...\n")
    results = apply_filters(
        all_records,
        min_ratio=args.min_ratio,
        min_width_px=min_width_px,
        watercolor_target=args.watercolor_target,
        oil_target=args.oil_target,
        check_resolution=not args.no_resolution_check,
        verbose=args.verbose,
    )

    watercolors = results["watercolors"]
    smooth_oils = results["smooth_oils"]
    rejected    = results["rejected_counts"]

    # ── Summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS")
    print(f"  Watercolors: {len(watercolors):3d} / {args.watercolor_target} target")
    print(f"  Smooth oils: {len(smooth_oils):3d} / {args.oil_target} target")
    print(f"\nRejection breakdown:")
    for reason, count in rejected.items():
        print(f"  {reason:25s}: {count}")

    # ── Save
    output = {
        "meta": {
            "sources":            args.sources,
            "watercolor_target":  args.watercolor_target,
            "oil_target":         args.oil_target,
            "min_ratio":          args.min_ratio,
            "print_width_inches": args.print_width,
            "print_dpi":          args.print_dpi,
            "min_width_px":       min_width_px,
            "total_fetched":      len(all_records),
            "rejected":           rejected,
            "vision_status":      vision_status(),
        },
        "watercolors": watercolors,
        "smooth_oils": smooth_oils,
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n✓ Saved {len(watercolors) + len(smooth_oils)} candidates to: {out_path}")

    # ── Helpful hints if targets not met
    if len(watercolors) < args.watercolor_target:
        shortage = args.watercolor_target - len(watercolors)
        print(f"\n⚠  {shortage} watercolor(s) short of target. Try:")
        print(f"   --limit {args.limit * 2}   (fetch more candidates per source)")
        if "europeana" not in args.sources:
            print(f"   --sources met aic europeana   (adds European collections)")

    if len(smooth_oils) < args.oil_target:
        shortage = args.oil_target - len(smooth_oils)
        print(f"\n⚠  {shortage} smooth oil(s) short of target. Try:")
        print(f"   --limit {args.limit * 2}")
        if "europeana" not in args.sources:
            print(f"   --sources met aic europeana")
        if args.no_vision and config.ANTHROPIC_API_KEY:
            print(f"   Remove --no-vision to use Claude for better oil detection")


if __name__ == "__main__":
    main()
