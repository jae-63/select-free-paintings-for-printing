# select-free-paintings-for-printing

A Python toolkit that searches public-domain museum collections for landscape
paintings suitable for high-resolution canvas printing — then outputs either a
browseable HTML gallery or a tarball of preview images for Mac Finder slideshow.

## What it does

1. **Fetches** landscape paintings from open museum APIs (The Met, Art Institute
   of Chicago, optionally Europeana) — no scraping, all proper API access
2. **Filters** by:
   - Medium: watercolors/gouache first, then smooth-technique oils
   - Aspect ratio: wider than it is tall (configurable, default ≥ 1.4:1)
   - Resolution: enough pixels for 200 DPI at 40" print width (configurable)
   - Excludes ≈1,000 of the most famous paintings in history
3. **Classifies oils** — uses Claude vision AI to assess whether an oil painting
   has smooth/flat brushwork (good for printing) vs heavy impasto texture (bad);
   falls back to artist-name heuristics if no API key is set
4. **Outputs** an HTML gallery with thumbnails, metadata, and museum links, and/or
   a tarball of quarter-megapixel preview images for slideshowing in Finder

## Default targets

- **80 watercolors** (watercolor, gouache, aquarelle)
- **20 smooth oils** (Luminist, Barbizon, Hague School, etc.)
- All works fully public-domain (CC0) with downloadable high-resolution images

## Setup

```bash
git clone https://github.com/jae-63/select-free-paintings-for-printing.git
cd select-free-paintings-for-printing
pip install -r requirements.txt
```

### API keys

The Met Museum API needs **no key**. The Art Institute of Chicago API also needs
**no key** for read access. Europeana requires a free key (optional but expands
coverage significantly for European collections).

```bash
cp config.example.env .env
# Edit .env and fill in keys you want to use:
#   EUROPEANA_API_KEY   — free at https://apis.europeana.eu/api/apikey-form
#   ANTHROPIC_API_KEY   — free tier at https://console.anthropic.com
#                         (only needed for Claude vision oil classification)
```

> **Security note:** `.env` is in `.gitignore` and will never be committed.
> The file `config.example.env` is the safe template that _is_ committed.

## Usage

### Step 1 — Fetch and filter candidates

```bash
# Quick test (skips slow resolution probing):
python fetch_candidates.py --no-resolution-check

# Full run:
python fetch_candidates.py

# With Europeana (more European watercolorists):
python fetch_candidates.py --sources met aic europeana

# Custom print spec (e.g. 48" wide at 300 DPI):
python fetch_candidates.py --print-width 48 --print-dpi 300

# Heuristics only, no Claude vision:
python fetch_candidates.py --no-vision
```

### Step 2a — HTML gallery

```bash
python make_report.py --input candidates.json --output report.html
open report.html
```

Each card shows: thumbnail, artist, title, date, medium, physical dimensions,
pixel count, estimated DPI at print width, and links to the museum page and
full-resolution image.

### Step 2b — Mac Finder slideshow tarball

```bash
python make_tarball.py --input candidates.json --output canvas_picks.tar.gz
tar xzf canvas_picks.tar.gz
open canvas_picks/
```

Images are named `001_watercolor_artist_title.jpg` so Finder's Quick Look
slideshow shows them in order. An `INDEX.txt` with full metadata is included.

## Configuration

All parameters live in **`config.py`** — edit it instead of touching the scripts.
Key settings:

| Setting | Default | Description |
|---|---|---|
| `WATERCOLOR_TARGET` | 80 | Target watercolor count |
| `OIL_TARGET` | 20 | Target smooth-oil count |
| `MIN_ASPECT_RATIO` | 1.4 | Minimum width/height ratio |
| `PRINT_WIDTH_INCHES` | 40 | Print width for DPI calculation |
| `PRINT_DPI` | 200 | Required DPI at print width |
| `MAX_CANDIDATES_PER_SOURCE` | 2000 | API fetch limit per source |
| `USE_CLAUDE_VISION` | True | Use Claude vision for oil assessment |
| `CLAUDE_VISION_SMOOTHNESS_THRESHOLD` | 3 | Min smoothness score (1–5) |
| `SMOOTH_OIL_ARTISTS` | (long list) | Heuristic artist list for oil fallback |
| `WATERCOLOR_MEDIUM_TERMS` | (list) | Medium strings recognized as watercolor |
| `IMPASTO_DISQUALIFY_TERMS` | (list) | Terms that disqualify an oil painting |
| `PREVIEW_TARGET_PIXELS` | 175,000 | Target pixels for tarball previews |
| `TARBALL_DOWNLOAD_WORKERS` | 3 | Parallel download threads |

CLI flags override config values for one-off runs (see `--help` on each script).

## Sources

| Source | API key | Coverage |
|---|---|---|
| [The Met](https://metmuseum.github.io/) | None needed | ~500k works, global |
| [Art Institute of Chicago](https://api.artic.edu/docs/) | None needed | ~120k works, strong on American/European |
| [Europeana](https://pro.europeana.eu/page/search) | Free | Aggregates 800+ European institutions |

All returned works are public domain / CC0. Images are downloaded directly from
museum servers; we do not redistribute or cache art images.

## Oil painting smoothness — how it works

Oil paintings with heavy impasto (thick, textured paint) reproduce poorly as flat
canvas prints — the 3D texture is invisible in a photo and the image looks muddy.

When `USE_CLAUDE_VISION = True` and `ANTHROPIC_API_KEY` is set, the tool sends
each candidate oil thumbnail to Claude with a structured prompt asking for a
smoothness score 1–5. Works scoring ≥ `CLAUDE_VISION_SMOOTHNESS_THRESHOLD` (default 3)
pass through.

When vision is disabled, the tool falls back to matching the artist name against
`SMOOTH_OIL_ARTISTS` — a curated list of painters known for smooth, flat, or
luminous technique (Luminist school, Barbizon, Hague School, Spanish impressionists,
Russian realists, etc.).

## Exclusions

The file `exclusions.py` contains ≈450 `(artist, title)` pairs and ≈30
title-only entries covering the most famous paintings in history. Works matching
these entries are excluded from results regardless of other criteria.

To add your own exclusions, append to the `FAMOUS_WORKS` list in `exclusions.py`.

## Contributing

Pull requests welcome — especially:
- Additional museum API sources
- Better medium-classification vocabulary
- Fixes to the famous-paintings exclusion list
- Improvements to the HTML report styling

## License

MIT. The code is yours to use freely. The artwork images themselves are public
domain — please check individual museum terms for commercial use.
