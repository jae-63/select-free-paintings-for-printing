# select-free-paintings-for-printing

A Python toolkit that searches public-domain museum collections for landscape
paintings suitable for high-resolution canvas printing — then outputs either a
browseable HTML gallery or a tarball of preview images for Mac Finder slideshow.

## What it does

1. **Fetches** landscape paintings from open museum APIs (The Met, Art Institute
   of Chicago, Europeana) — no scraping, all proper documented API access
2. **Filters** by:
   - Medium: watercolors/gouache first, then smooth-technique oils
   - Aspect ratio: wider than it is tall (configurable, default ≥ 1.4:1)
   - Resolution: enough pixels for 200 DPI at 40" print width (configurable)
   - Excludes ~1,000 of the most famous paintings in history
3. **Classifies oils** — uses Claude vision AI to assess whether an oil painting
   has smooth/flat brushwork (good for printing) vs heavy impasto texture (bad);
   falls back to artist-name heuristics if no API key is set
4. **Merges** per-source results, deduplicates, and ranks by metadata quality
5. **Outputs** an HTML gallery with thumbnails, metadata, and museum links, and/or
   a tarball of quarter-megapixel preview images for slideshowing in Mac Finder

## Default targets

- **80 watercolors** (watercolor, gouache, aquarelle, and multilingual equivalents)
- **20 smooth oils** (Luminist, Barbizon, Hague School, Dutch Golden Age, etc.)
- All works fully public-domain (CC0 or equivalent) with downloadable high-res images

## Setup

```bash
git clone https://github.com/jae-63/select-free-paintings-for-printing.git
cd select-free-paintings-for-printing
pip install -r requirements.txt
```

### API keys

The Met Museum and Art Institute of Chicago APIs need **no key**. Europeana
requires a free personal key. Claude vision for oil classification requires an
Anthropic API key (also free tier available); without it the tool falls back to
artist-name heuristics.

```bash
cp config.example.env .env
# Edit .env and add any keys you have:
#   EUROPEANA_API_KEY   — free at https://apis.europeana.eu/api/apikey-form
#   ANTHROPIC_API_KEY   — free tier at https://console.anthropic.com
```

> **Security:** `.env` is gitignored and never committed. `config.example.env`
> is the safe committed template.

## Recommended workflow

Run each source separately so you can monitor progress and restart any source
independently. Each step writes its own output file.

### Step 1 — Fetch from each source

```bash
# The Met (no API key needed; slowest due to per-object fetching)
python fetch_candidates.py --sources met --output candidates_met.json

# Art Institute of Chicago (no API key needed; fast IIIF resolution lookup)
python fetch_candidates.py --sources aic --output candidates_aic.json

# Europeana (requires EUROPEANA_API_KEY in .env)
# Automatically runs two passes: one for watercolors, one for oils
python fetch_candidates.py --sources europeana --output candidates_europeana.json
```

For a quick test without the slow resolution-probing step:
```bash
python fetch_candidates.py --sources aic --no-resolution-check --output test.json
```

### Step 2 — Merge sources into final selection

```bash
python merge_candidates.py \
  --inputs candidates_met.json candidates_aic.json candidates_europeana.json \
  --watercolor-target 80 \
  --oil-target 20 \
  --output candidates_final.json
```

Optional flags:
- `--require-artist` — exclude works where the artist is listed as "Unknown"
- `--shuffle` — randomise order within sources before trimming (adds variety)
- `--verbose` — print every selected work

### Step 3a — HTML gallery

```bash
python make_report.py --input candidates_final.json --output report.html
open report.html
```

Each card shows: thumbnail, artist, title, date, medium, physical dimensions,
pixel count, estimated DPI at your target print width, and links to the museum
page and full-resolution image download.

### Step 3b — Mac Finder slideshow tarball

```bash
python make_tarball.py --input candidates_final.json --output canvas_picks.tar.gz
tar xzf canvas_picks.tar.gz
open canvas_picks/
```

Images are named `001_watercolor_artist_title.jpg` so Finder's Quick Look
slideshow (select all → Space) shows them in sequence. An `INDEX.txt` with full
metadata is included in the tarball.

## Configuration

All parameters live in **`config.py`** — edit that file rather than the scripts.
CLI flags override config values for one-off runs (see `--help` on each script).

### Key settings

| Setting | Default | Description |
|---|---|---|
| `WATERCOLOR_TARGET` | 80 | Target watercolor count |
| `OIL_TARGET` | 20 | Target smooth-oil count |
| `MIN_ASPECT_RATIO` | 1.4 | Minimum width/height ratio (landscape orientation) |
| `PRINT_WIDTH_INCHES` | 40 | Print width in inches |
| `PRINT_DPI` | 200 | Required DPI at print width |
| `MIN_PIXEL_WIDTH` | 8000 | Derived: `PRINT_WIDTH_INCHES × PRINT_DPI` |
| `MAX_CANDIDATES_PER_SOURCE` | 4000 | API fetch limit per source per pass |
| `USE_CLAUDE_VISION` | True | Use Claude vision for oil smoothness assessment |
| `CLAUDE_VISION_SMOOTHNESS_THRESHOLD` | 3 | Min score (1–5) to accept an oil painting |
| `CLAUDE_VISION_PROMPT` | (in config) | Full prompt text sent to Claude — editable |
| `SMOOTH_OIL_ARTISTS` | (long list) | Heuristic fallback artist list |
| `WATERCOLOR_MEDIUM_TERMS` | (list) | Medium strings recognised as watercolor |
| `IMPASTO_DISQUALIFY_TERMS` | (list) | Terms that disqualify an oil painting |
| `PREVIEW_TARGET_PIXELS` | 175,000 | ~Quarter-megapixel target for tarball previews |
| `TARBALL_DOWNLOAD_WORKERS` | 3 | Parallel download threads (be gentle with servers) |

## Sources

| Source | API key | Notes |
|---|---|---|
| [The Met](https://metmuseum.github.io/) | None | ~500k works; fetches one object at a time — slowest source |
| [Art Institute of Chicago](https://api.artic.edu/docs/) | None | ~120k works; fast IIIF dimension lookup |
| [Europeana](https://pro.europeana.eu/page/search) | Free (personal key sufficient) | Aggregates 800+ European institutions; medium often inferred from title or multilingual concept tags rather than a dedicated field |

All returned works are public domain. Images are served directly from museum
infrastructure; this tool does not redistribute or cache artwork.

### Source-specific notes

**The Met:** Uses controlled vocabulary for medium — the search `medium` parameter
requires exact Met terms (e.g. `"Watercolors"` plural, not `"Watercolor"`).
Without the medium filter, queries return a very broad mix including Islamic
manuscripts and Asian art that pass watercolor classification by medium string
but are illuminated manuscripts, not landscape paintings. Department filtering
(depts 9, 11, 21) is applied to constrain results to Western paintings and
works on paper.

**Europeana:** Many records omit the `dcFormat` (medium) field entirely. The tool
infers medium from three fallback locations in priority order: multilingual concept
tags (`edmConceptPrefLabelLangAware`), the title string (many institutions prefix
titles with the medium, e.g. `"Watercolor, Landscape"`), and the description text.
Medium prefixes are stripped from titles in the output. Watercolor and oil
candidates are fetched in separate passes so neither medium starves the other.

### Sources investigated but not currently supported

**Rijksmuseum** — The Rijksmuseum migrated to a new Linked Art Search API
(`data.rijksmuseum.nl/search/collection`) in 2024, deprecating their previous
collection API (which now returns 410 Gone). The new API returns Linked Art
identifiers that must be resolved individually for metadata, requiring 2–3 HTTP
calls per object. More critically, image URLs are not embedded in the Linked Art
object responses — they are accessible only via a separate IIIF manifest, but the
manifest endpoint (`rijksmuseum.nl/api/iiif/{id}/manifest`) also appears to have
moved and returns 404 for tested object numbers. A partial implementation exists
in the `experimental/rijksmuseum-getty` branch for reference.

**J. Paul Getty Museum** — The Getty's collection API (`data.getty.edu`) is built
on a Linked Open Data gateway and returns Linked Art format similar to
Rijksmuseum. The API documentation is a JavaScript single-page application and
not easily machine-readable. Like Rijksmuseum, the architecture requires multiple
roundtrips per object and image URL resolution is non-trivial. A stub
implementation exists in the `experimental/rijksmuseum-getty` branch. The Getty's
IIIF image quality is reportedly excellent (often 20,000px+) and would be worth
revisiting if their API stabilises with better documentation.

## Oil painting smoothness — how it works

Oil paintings with heavy impasto (thick, textured brushwork) reproduce poorly as
flat canvas prints — the 3D surface texture is lost entirely and the image can
look muddy. Smooth, glazed, or atmospheric oils reproduce well.

When `USE_CLAUDE_VISION = True` and `ANTHROPIC_API_KEY` is set, each candidate
oil thumbnail is sent to Claude with a structured prompt requesting a smoothness
score from 1 (heavy impasto, e.g. Van Gogh's Starry Night style) to 5 (very
smooth/glazed, e.g. Dutch Golden Age). Works scoring ≥
`CLAUDE_VISION_SMOOTHNESS_THRESHOLD` (default 3) are accepted.

The full prompt text is in `config.py` under `CLAUDE_VISION_PROMPT` and can be
tuned without touching any other file.

When vision is disabled or no API key is present, the tool falls back to matching
the artist name against `SMOOTH_OIL_ARTISTS` in `config.py` — a curated list of
~90 painters known for smooth, flat, or luminous technique (American Luminists,
Barbizon School, Hague School, Spanish impressionists, Russian realists, etc.).

## Exclusions

`exclusions.py` contains ~450 `(artist_fragment, title_fragment)` pairs and ~30
title-only entries covering the most famous paintings in history — the works you
wouldn't want to hang as a canvas print because everyone has seen them. Matching
is case-insensitive substring matching on both fields.

Works matching any exclusion are skipped regardless of all other criteria.

To add personal exclusions (e.g. artists or subjects you dislike), append to
`FAMOUS_WORKS` in `exclusions.py`.

## Troubleshooting

**Met returns 0 results for all queries**
The Met API `medium` filter uses exact controlled-vocabulary terms. If you've
edited `MET_MEDIUM_FILTER` in `sources/met.py`, verify the terms against the
Met's own facet data. Valid examples: `"Watercolors"`, `"Gouache"`,
`"Oil on canvas"`, `"Oil on panel"`.

**Europeana oils not found**
Verify the dual-pass logic is present in `fetch_candidates.py` — there should be
two separate `fetch_all_candidates()` calls when `--sources europeana` is used,
one for `WATERCOLOR_QUERIES` and one for `OIL_QUERIES`.

**Falling short of watercolor target**
Increase `MAX_CANDIDATES_PER_SOURCE` in `config.py` (default 4000), or add
Europeana as a source. The AIC and Met both have high proportions of portrait-
oriented works that fail the aspect ratio filter, so the effective yield per
fetched record is lower than you might expect.

**Resolution probing is very slow**
Use `--no-resolution-check` for exploratory runs. Resolution probing downloads
the first 64KB of each image to read its pixel dimensions — at ~0.5s per image
across thousands of candidates this adds up. AIC is faster because IIIF provides
dimensions via a lightweight `info.json` endpoint without image download.

**`ftp://` image URLs fail silently**
Some Europeana records (particularly from Skokloster Castle) provide `ftp://`
image URLs which cannot be probed or downloaded over HTTP. These records are
accepted during `--no-resolution-check` runs but will fail resolution probing
and tarball download. They will be present in the JSON but produce no image file.

## Contributing

Pull requests welcome — especially:
- Additional museum API sources (Rijksmuseum, Smithsonian, Wikimedia Commons)
- Improved medium-classification vocabulary for non-English museum metadata
- Additions or corrections to the famous-paintings exclusion list
- Improvements to the HTML report design

## License

MIT. The code is yours to use freely. The artwork images themselves are public
domain — please check individual museum terms if you intend commercial use of
the prints.
