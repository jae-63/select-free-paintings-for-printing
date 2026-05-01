#!/usr/bin/env python3
"""
make_report.py

Generates a dark-themed HTML gallery page from candidates.json.
All display settings come from config.py.

Usage:
    python make_report.py [--input candidates.json] [--output report.html]
    open report.html
"""

import argparse
import json
from pathlib import Path

import config

# ---------------------------------------------------------------------------
# HTML template (appearance settings come from config)
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{report_title}</title>
<style>
  :root {{
    --bg:        #1a1a1a;
    --card-bg:   #252525;
    --text:      #e0e0e0;
    --muted:     #999;
    --accent:    #c8a96e;
    --border:    #333;
    --wc-tag:    #3a7a5a;
    --oil-tag:   #5a4a7a;
    --photo-tag: #5a6a3a;
    --shadow:    0 4px 16px rgba(0,0,0,0.5);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: Georgia, 'Times New Roman', serif;
    padding: 2rem;
  }}
  h1 {{ color: var(--accent); font-size: 2rem; margin-bottom: 0.4rem; }}
  .subtitle {{
    color: var(--muted); font-size: 0.9rem; margin-bottom: 1.5rem;
    font-family: 'Helvetica Neue', Arial, sans-serif;
  }}
  .stats {{
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 0.8rem 1.4rem; margin-bottom: 2rem;
    font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 0.82rem;
    color: var(--muted); display: flex; gap: 2rem; flex-wrap: wrap;
  }}
  .stats b {{ color: var(--text); }}
  .section-header {{
    font-size: 1.4rem; color: var(--accent);
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.4rem; margin: 2.5rem 0 1.4rem; font-style: italic;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 1.4rem;
  }}
  .card {{
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 10px; overflow: hidden; box-shadow: var(--shadow);
    transition: transform .2s, box-shadow .2s;
  }}
  .card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,.7); }}
  .card img {{
    width: 100%; height: 185px; object-fit: cover; object-position: center;
    display: block; background: #111;
  }}
  .no-image {{
    width: 100%; height: 185px; background: #111;
    display: flex; align-items: center; justify-content: center;
    color: #444; font-size: 0.8rem; font-family: 'Helvetica Neue', Arial, sans-serif;
  }}
  .card-body {{ padding: 0.9rem 1rem 1rem; }}
  .tag {{
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.68rem; font-family: 'Helvetica Neue', Arial, sans-serif;
    font-weight: bold; letter-spacing: .05em; text-transform: uppercase;
    margin-right: 4px; margin-bottom: 6px;
  }}
  .tag-wc    {{ background: var(--wc-tag);    color: #a8e8c8; }}
  .tag-oil   {{ background: var(--oil-tag);   color: #c8b8f0; }}
  .tag-photo {{ background: var(--photo-tag); color: #d0e8a0; }}
  .tag-src {{ background: #333; color: #aaa; }}
  .card-title  {{ font-size: 0.98rem; color: var(--text); margin-bottom: .25rem; font-style: italic; }}
  .card-artist {{ font-size: 0.83rem; color: var(--accent); margin-bottom: .45rem;
                  font-family: 'Helvetica Neue', Arial, sans-serif; font-weight: bold; }}
  .card-meta   {{ font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 0.74rem;
                  color: var(--muted); line-height: 1.55; }}
  .dims        {{ margin-top: .3rem; font-size: 0.70rem; color: #666; font-family: monospace; }}
  .card-links  {{ margin-top: .7rem; font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 0.74rem; }}
  .card-links a {{ color: var(--accent); text-decoration: none; margin-right: 1rem; }}
  .card-links a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>

<h1>🎨 {report_title}</h1>
<p class="subtitle">{report_subtitle}</p>

<div class="stats">
  <div>Watercolors: <b>{n_wc}</b></div>
  <div>Smooth Oils: <b>{n_oil}</b></div>
  <div>Photographs: <b>{n_photo}</b></div>
  <div>Total: <b>{n_total}</b></div>
  <div>Min aspect ratio: <b>{min_ratio}:1</b></div>
  <div>Print spec: <b>{print_width}" @ {print_dpi} DPI ({min_px}px)</b></div>
  <div>Sources: <b>{sources}</b></div>
  <div>Vision: <b>{vision}</b></div>
</div>

<div class="section-header">Watercolors &amp; Gouaches — {n_wc} works</div>
<div class="grid">
{watercolor_cards}
</div>

<div class="section-header">Smooth-Technique Oils — {n_oil} works</div>
<div class="grid">
{oil_cards}
</div>

{photo_section}

</body>
</html>
"""

CARD_TEMPLATE = """\
<div class="card">
  {img_tag}
  <div class="card-body">
    <span class="tag tag-{med_class}">{med_label}</span>
    <span class="tag tag-src">{source}</span>
    <div class="card-title">"{title}"</div>
    <div class="card-artist">{artist}</div>
    <div class="card-meta">{date_html}{medium_html}</div>
    <div class="dims">{dims_html}{px_html}</div>
    <div class="card-links"><a href="{full_url}" target="_blank">Full image ↗</a>{detail_link}</div>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------

SOURCE_NAMES = {
    "met":       "The Met",
    "aic":       "Art Institute",
    "europeana": "Europeana",
    "wikimedia": "Wikimedia",
    "loc":       "Library of Congress",
    "nga":       "Natl Gallery",
    "cleveland": "Cleveland Museum",
    "ycba":      "Yale YCBA",
}


def make_card(rec: dict) -> str:
    mc = rec.get("_medium_class", "")
    if mc == "watercolor":
        med_class, med_label = "wc",    "Watercolor"
    elif mc == "photograph":
        med_class, med_label = "photo", "Photograph"
    else:
        med_class, med_label = "oil",   "Smooth Oil"
    source = rec.get("source", "?")

    img_url = rec.get("image_url_small") or rec.get("image_url_full") or ""
    title_attr = rec.get("title", "").replace('"', "&quot;")
    img_tag = (
        f'<img src="{img_url}" alt="{title_attr}" loading="lazy">'
        if img_url else
        '<div class="no-image">No preview available</div>'
    )

    title  = rec.get("title", "Untitled")[:config.REPORT_TITLE_TRUNCATE]
    artist = rec.get("artist", "Unknown")[:config.REPORT_ARTIST_TRUNCATE]
    date   = rec.get("date", "")
    medium = rec.get("medium", "")[:config.REPORT_MEDIUM_TRUNCATE]

    date_html   = f"<b>{date}</b><br>" if date else ""
    medium_html = f"{medium}{'…' if len(rec.get('medium','')) > config.REPORT_MEDIUM_TRUNCATE else ''}<br>" if medium else ""

    # Physical dimensions
    w_cm = rec.get("width_cm")
    h_cm = rec.get("height_cm")
    dims_raw = rec.get("dimensions_raw", "")
    if w_cm and h_cm:
        ratio = max(w_cm, h_cm) / min(w_cm, h_cm)
        dims_html = f"Physical: {w_cm:.1f} × {h_cm:.1f} cm (ratio {ratio:.2f})<br>"
    elif dims_raw:
        dims_html = f"Dims: {dims_raw[:60]}<br>"
    else:
        dims_html = ""

    # Pixel info
    px_w = rec.get("pixel_width")
    px_h = rec.get("pixel_height")
    if px_w and px_h:
        dpi_at_width = px_w / config.PRINT_WIDTH_INCHES
        px_html = f"Image: {px_w} × {px_h}px ({dpi_at_width:.0f} DPI@{config.PRINT_WIDTH_INCHES}\")"
    else:
        px_html = "Resolution: not checked"

    # Links
    full_url = rec.get("image_url_full", "#")
    detail_url = rec.get("public_url") or rec.get("detail_url") or ""
    link_text = SOURCE_NAMES.get(source, source.upper())
    detail_link = f'<a href="{detail_url}" target="_blank">{link_text} page ↗</a>' if detail_url else ""

    return CARD_TEMPLATE.format(
        img_tag=img_tag,
        med_class=med_class,
        med_label=med_label,
        source=source.upper(),
        title=title,
        artist=artist,
        date_html=date_html,
        medium_html=medium_html,
        dims_html=dims_html,
        px_html=px_html,
        full_url=full_url,
        detail_link=detail_link,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Generate HTML gallery report from candidates.json",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input",  default=config.DEFAULT_CANDIDATES_FILE)
    p.add_argument("--output", default=config.DEFAULT_REPORT_FILE)
    args = p.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    meta         = data.get("meta", {})
    watercolors  = data.get("watercolors", [])
    smooth_oils  = data.get("smooth_oils", [])
    photographs  = data.get("photographs", [])

    wc_cards    = "\n".join(make_card(r) for r in watercolors)
    oil_cards   = "\n".join(make_card(r) for r in smooth_oils)
    photo_cards = "\n".join(make_card(r) for r in photographs)

    if photographs:
        photo_section = (
            f'<div class="section-header">Photographs — {len(photographs)} works</div>\n'
            f'<div class="grid">\n{photo_cards}\n</div>'
        )
    else:
        photo_section = ""

    html = HTML_TEMPLATE.format(
        report_title    = config.REPORT_TITLE,
        report_subtitle = config.REPORT_SUBTITLE,
        n_wc            = len(watercolors),
        n_oil           = len(smooth_oils),
        n_photo         = len(photographs),
        n_total         = len(watercolors) + len(smooth_oils) + len(photographs),
        min_ratio       = meta.get("min_ratio", config.MIN_ASPECT_RATIO),
        print_width     = meta.get("print_width_inches", config.PRINT_WIDTH_INCHES),
        print_dpi       = meta.get("print_dpi", config.PRINT_DPI),
        min_px          = meta.get("min_width_px", config.MIN_PIXEL_WIDTH),
        sources         = ", ".join(meta.get("sources", [])).upper(),
        vision          = meta.get("vision_status", "unknown"),
        watercolor_cards = wc_cards,
        oil_cards        = oil_cards,
        photo_section    = photo_section,
    )

    Path(args.output).write_text(html, encoding="utf-8")
    print(f"✓ Report written to: {args.output}")
    print(f"  Open with: open {args.output}")


if __name__ == "__main__":
    main()
