#!/usr/bin/env python3
"""
make_tarball.py

Downloads quarter-megapixel preview images for all candidates and packages
them into a .tar.gz suitable for Mac Finder slideshow viewing.

Images are saved as:
  {index:03d}_{medium_class}_{artist_slug}_{title_slug}.jpg

All size and concurrency settings come from config.py.

Usage:
    python make_tarball.py [--input candidates.json] [--output canvas_picks.tar.gz]
    tar xzf canvas_picks.tar.gz && open canvas_picks/
"""

import argparse
import io
import json
import re
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image

import config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(s: str, max_len: int = 40) -> str:
    """Convert a string to a safe filename fragment."""
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s.strip("_")[:max_len]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


def choose_download_url(rec: dict) -> str:
    """
    Select the best URL for downloading a preview-sized image.
    For IIIF sources (AIC, Getty), request a sized URL to avoid downloading
    the full high-resolution image.
    """
    source   = rec.get("source")
    image_id = rec.get("_image_id")
    w        = config.AIC_PREVIEW_WIDTH_PX

    if source == "aic" and image_id:
        return f"https://www.artic.edu/iiif/2/{image_id}/full/{w},/0/default.jpg"

    if source == "rijksmuseum" and image_id:
        return f"https://iiif.micr.io/{image_id}/full/{w},/0/default.jpg"

    if source == "getty" and image_id:
        return f"https://data.getty.edu/museum/api/iiif/{image_id}/full/{w},/0/default.jpg"

    return rec.get("image_url_small") or rec.get("image_url_full") or ""


def get_resized_jpeg(url: str, session: requests.Session) -> bytes | None:
    """
    Download image from url, resize to config.PREVIEW_TARGET_PIXELS total pixels
    (preserving aspect ratio), return as JPEG bytes.
    """
    try:
        resp = session.get(url, timeout=config.HTTP_TIMEOUT_IMAGE)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")

        w, h = img.size
        total = w * h
        if total > config.PREVIEW_TARGET_PIXELS:
            scale = (config.PREVIEW_TARGET_PIXELS / total) ** 0.5
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.LANCZOS,
            )

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=config.PREVIEW_JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    except Exception as e:
        return None


# ---------------------------------------------------------------------------
# Download worker
# ---------------------------------------------------------------------------

def download_one(task: tuple) -> tuple:
    """
    Download and resize one image.
    task = (index, record, delay)
    Returns (filename, bytes_or_None).
    """
    idx, rec, delay = task
    time.sleep(delay)

    med    = rec.get("_medium_class", "unknown")
    artist = rec.get("artist", "unknown")
    title  = rec.get("title", "untitled")
    filename = f"{idx:03d}_{med}_{slugify(artist)}_{slugify(title)}.jpg"

    url = choose_download_url(rec)
    if not url:
        return filename, None

    session = _session()
    data = get_resized_jpeg(url, session)
    return filename, data


# ---------------------------------------------------------------------------
# Index file
# ---------------------------------------------------------------------------

def build_index(records: list) -> bytes:
    """Build a plain-text INDEX.txt listing all works."""
    lines = [
        "Canvas Print Candidates — Index\n",
        "=" * 60 + "\n\n",
        f"Total works: {len(records)}\n",
        f"Preview size: ~{config.PREVIEW_TARGET_PIXELS // 1000}k pixels\n\n",
    ]
    for i, rec in enumerate(records, 1):
        med    = rec.get("_medium_class", "?").upper()
        artist = rec.get("artist", "Unknown")
        title  = rec.get("title", "Untitled")
        date   = rec.get("date", "")
        medium = rec.get("medium", "")[:60]
        url    = rec.get("public_url") or rec.get("detail_url") or ""
        px_w   = rec.get("pixel_width") or 0
        px_h   = rec.get("pixel_height") or 0
        dpi    = f"{px_w / config.PRINT_WIDTH_INCHES:.0f} DPI@{config.PRINT_WIDTH_INCHES}\"" if px_w else "res unknown"

        lines.append(f"{i:03d}. [{med}] {artist}\n")
        lines.append(f'     "{title}" ({date})\n')
        lines.append(f"     {medium}\n")
        lines.append(f"     {dpi}\n")
        if url:
            lines.append(f"     {url}\n")
        lines.append("\n")

    return "".join(lines).encode("utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Build tarball of preview images for Mac Finder slideshow",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input",   default=config.DEFAULT_CANDIDATES_FILE)
    p.add_argument("--output",  default=config.DEFAULT_TARBALL_FILE)
    p.add_argument("--workers", type=int, default=config.TARBALL_DOWNLOAD_WORKERS,
                   help="Parallel download workers (be gentle with museum servers)")
    p.add_argument("--delay",   type=float, default=config.TARBALL_DOWNLOAD_DELAY,
                   help="Delay between requests per worker (seconds)")
    args = p.parse_args()

    data        = json.loads(Path(args.input).read_text(encoding="utf-8"))
    watercolors = data.get("watercolors", [])
    smooth_oils = data.get("smooth_oils", [])
    all_recs    = watercolors + smooth_oils

    target_mpx = config.PREVIEW_TARGET_PIXELS / 1_000_000
    print(f"Preparing to download {len(all_recs)} images")
    print(f"Preview target:  {config.PREVIEW_TARGET_PIXELS:,}px (~{target_mpx:.2f}MP)")
    print(f"Workers: {args.workers}, delay: {args.delay}s/worker")

    tasks = [(i + 1, rec, args.delay) for i, rec in enumerate(all_recs)]

    results = []
    failed  = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_one, t): t for t in tasks}
        for future in as_completed(futures):
            filename, img_bytes = future.result()
            if img_bytes:
                results.append((filename, img_bytes))
                kb = len(img_bytes) // 1024
                print(f"  ✓ {filename}  ({kb}KB)")
            else:
                idx = futures[future][0]
                rec = futures[future][1]
                print(f"  ✗ Failed #{idx}: {rec.get('artist')} — {rec.get('title')}")
                failed += 1

    results.sort(key=lambda x: x[0])

    print(f"\nBuilding: {args.output}")
    inner = config.TARBALL_INNER_DIR
    with tarfile.open(args.output, "w:gz") as tar:
        for filename, img_bytes in results:
            info = tarfile.TarInfo(name=f"{inner}/{filename}")
            info.size = len(img_bytes)
            tar.addfile(info, io.BytesIO(img_bytes))

        index_bytes = build_index(all_recs)
        info = tarfile.TarInfo(name=f"{inner}/INDEX.txt")
        info.size = len(index_bytes)
        tar.addfile(info, io.BytesIO(index_bytes))

    size_mb = Path(args.output).stat().st_size / 1024 / 1024
    print(f"\n✓ Tarball created: {args.output}")
    print(f"  Size:    {size_mb:.1f} MB")
    print(f"  Success: {len(results)}, Failed: {failed}")
    print(f"\nTo view as slideshow on Mac:")
    print(f"  tar xzf {args.output} && open {inner}/")
    print(f"  # Select all images in Finder, press Space for Quick Look slideshow")


if __name__ == "__main__":
    main()
