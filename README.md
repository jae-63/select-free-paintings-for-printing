# select-free-paintings-for-printing

A Python toolkit that searches public-domain museum collections for landscape
paintings suitable for high-resolution canvas printing — then outputs either a
browseable HTML gallery or a tarball of preview images for Mac Finder slideshow.

## What it does

1. **Fetches** landscape paintings from open museum APIs (The Met, Art Institute
   of Chicago, National Gallery of Art, Cleveland Museum of Art, Yale Center for
   British Art, Library of Congress, Europeana, J. Paul Getty Museum, Smithsonian) —
   no scraping, all proper documented API access
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
- **20 smooth oils** (Luminist, Barbizon, Hague School, Dutch Golden Age, British landscapes, etc.)
- All works fully public-domain (CC0 or equivalent) with downloadable high-res images

## Setup

```bash
git clone https://github.com/jae-63/select-free-paintings-for-printing.git
cd select-free-paintings-for-printing
pip install -r requirements.txt
```

### API keys

Most sources need **no key at all** — The Met, Art Institute of Chicago,
National Gallery of Art, Cleveland Museum of Art, Yale Center for British Art,
J. Paul Getty Museum, and Library of Congress are all keyless. Europeana and
Smithsonian each require a free personal key. Claude vision for oil classification
requires an Anthropic API key (free tier available); without it the tool falls
back to artist-name heuristics.

```bash
cp config.example.env .env
# Edit .env and add any keys you have:
#   EUROPEANA_API_KEY    — free at https://apis.europeana.eu/api/apikey-form
#   SMITHSONIAN_API_KEY  — free at https://api.data.gov/signup/
#   ANTHROPIC_API_KEY    — free tier at https://console.anthropic.com
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

# Art Institute of Chicago (no API key needed; fast IIIF dimension lookup)
python fetch_candidates.py --sources aic --output candidates_aic.json

# National Gallery of Art (no API key needed; streams GitHub CSV data)
python fetch_candidates.py --sources nga --output candidates_nga.json

# Cleveland Museum of Art (no API key needed; CC0 open access REST API)
python fetch_candidates.py --sources cleveland --output candidates_cleveland.json

# Yale Center for British Art (no API key needed; OAI-PMH + IIIF manifests)
python fetch_candidates.py --sources ycba --output candidates_ycba.json

# Library of Congress (no API key needed; targets the Highsmith Archive for 8k+ photos)
python fetch_candidates.py --sources loc --output candidates_loc.json

# Europeana (requires EUROPEANA_API_KEY in .env)
python fetch_candidates.py --sources europeana --output candidates_europeana.json

# J. Paul Getty Museum (no API key needed; Linked Art / SPARQL API)
python fetch_candidates.py --sources getty --output candidates_getty.json

# Smithsonian (requires SMITHSONIAN_API_KEY in .env)
# Commenting out this line, in this procedure, because the cost-benefit is so poor
# python fetch_candidates.py --sources smithsonian --output candidates_smithsonian.json
```

For a quick test without the slow resolution-probing step:
```bash
python fetch_candidates.py --sources aic --no-resolution-check --output test.json
```

### Step 2 — Merge sources into final selection

```bash
python merge_candidates.py \
  --inputs candidates_met.json candidates_aic.json candidates_nga.json \
           candidates_cleveland.json candidates_ycba.json candidates_loc.json \
           candidates_europeana.json candidates_getty.json \
  --watercolor-target 240 \
  --oil-target 60 \
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
| [National Gallery of Art](https://github.com/NationalGalleryOfArt/opendata) | None | Streams two GitHub CSV files; pixel dimensions in the data |
| [Cleveland Museum of Art](https://openaccess-api.clevelandart.org/) | None | CC0 open access; TIFF dimensions returned directly by the API |
| [Yale Center for British Art](https://britishart.yale.edu/collections-data-sharing) | None | OAI-PMH identifier harvest + per-item IIIF v3 manifest; British oils and watercolors |
| [Library of Congress](https://www.loc.gov/apis/json-and-yaml/) | None | Targets the Carol M. Highsmith Archive for 8000px+ photographs |
| [Europeana](https://pro.europeana.eu/page/search) | Free (personal key sufficient) | Aggregates 800+ European institutions; medium often inferred from multilingual concept tags |
| [J. Paul Getty Museum](https://data.getty.edu/museum/collection/) | None | Linked Art / SPARQL API; excellent scan quality (often 20 000px+) |
| [Smithsonian](https://edan.si.edu/openaccess/apidocs/) | Free (personal key sufficient) | Not much high resolution art |

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

**National Gallery of Art:** Fetches two CSV files from the NGA's GitHub open-data
repository (`objects.csv` and `published_images.csv`), joins them on object ID,
and filters by classification (Painting, Drawing). Pixel dimensions and IIIF URLs
are available directly in the data — no per-item HTTP requests beyond the two
initial CSV downloads.

**Cleveland Museum of Art:** The CMA Open Access API returns a `full` image tier
(TIFF) with pixel dimensions embedded in the response, so no header probing is
needed. Watercolors are filed under the "Drawing" artwork type rather than a
dedicated "Watercolor" type.

**Yale Center for British Art:** Uses the OAI-PMH harvester
(`harvester-bl.britishart.yale.edu`) to page through painting and drawing object
IDs, then fetches each IIIF v3 manifest for metadata and image URLs. The OAI-PMH
server is slow (allow 60s per page); this is handled automatically. Scan
resolution varies by painting size — large oils (≥24" wide) reliably exceed
8000px; smaller works often do not. Claude vision is strongly recommended for
this source, as the no-vision heuristic knows too few British artists by name.

**Library of Congress:** Queries the loc.gov JSON search API targeting the Carol
M. Highsmith Archive, which provides 8000–14,000 px TIFF masters of American
landscapes and landmarks. TIFF URLs are derived from the search result's
`image_url` array (replacing the service path with the master path) — no
per-item API calls are needed. The API can return 429 responses under heavy load;
the source retries automatically with backoff.

**Europeana:** Many records omit the `dcFormat` (medium) field entirely. The tool
infers medium from three fallback locations in priority order: multilingual concept
tags (`edmConceptPrefLabelLangAware`), the title string (many institutions prefix
titles with the medium, e.g. `"Watercolor, Landscape"`), and the description text.
Medium prefixes are stripped from titles in the output. Watercolor and oil
candidates are fetched in separate passes so neither medium starves the other.

**J. Paul Getty Museum:** Uses the Getty's Linked Art SPARQL endpoint to query for
paintings with IIIF manifests. Image quality is excellent — scans are often
20,000px or wider. Because the Getty collection skews toward old master paintings
(many portraits and religious subjects), Claude vision is recommended to filter
for landscapes and smooth-technique works.

**Smithsonian:** Included for completeness, but not much high-resolution art.

### Sources investigated but not currently supported

**Rijksmuseum** — The Rijksmuseum migrated to a new Linked Art Search API
(`data.rijksmuseum.nl/search/collection`) in 2024, deprecating their previous
collection API (which now returns 410 Gone). The new API requires 2–3 HTTP calls
per object for metadata, plus a separate IIIF manifest fetch for image URLs —
too many roundtrips for practical bulk harvesting. A partial implementation exists
in the `experimental/rijksmuseum-getty` branch for reference.

## Oil painting smoothness — how it works

Oil paintings with heavy impasto (thick, textured brushwork) reproduce poorly as
flat canvas prints — the 3D surface texture is lost entirely and the image can
look muddy. Smooth, glazed, or atmospheric oils reproduce well.

When `USE_CLAUDE_VISION = True` and `ANTHROPIC_API_KEY` is set, each candidate
oil thumbnail is sent to Claude with a structured prompt requesting a smoothness
score from 1 (heavy impasto, e.g. Van Gogh's Starry Night style) to 5 (very
smooth/glazed, e.g. Dutch Golden Age). Works scoring ≥
`CLAUDE_VISION_SMOOTHNESS_THRESHOLD` (default 3) are accepted.

[The full prompt text](./config.py#L31) is in `config.py` under `CLAUDE_VISION_PROMPT` and can be
tuned without touching any other file.

When vision is disabled or no API key is present, the tool falls back to matching
the artist name against `SMOOTH_OIL_ARTISTS` in `config.py` — a curated list of
~120 painters known for smooth, flat, or luminous technique (American Luminists,
Barbizon School, Hague School, Dutch Golden Age, Spanish impressionists, Russian
realists, British landscape painters, and more).

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

**YCBA yields 0 oils without Claude vision**
The no-vision heuristic checks the artist name against `SMOOTH_OIL_ARTISTS`. The
YCBA collection's early TMS records tend to be portraits and genre paintings; the
heuristic will reject them if the artist isn't in the list. Either enable Claude
vision (`USE_CLAUDE_VISION = True` with `ANTHROPIC_API_KEY` set) or increase
`--limit` to sample more of the collection past the early portrait-heavy records.

**LoC returns 0 results (rate-limited)**
The Library of Congress API can temporarily block IPs that send too many requests
in a short period. Wait a few hours and retry. The source retries automatically
with backoff during a run, but repeated test runs can exhaust the grace period.

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
NGA and Cleveland return pixel dimensions directly from their data sources, so
neither requires probing.

**`ftp://` image URLs fail silently**
Some Europeana records (particularly from Skokloster Castle) provide `ftp://`
image URLs which cannot be probed or downloaded over HTTP. These records are
accepted during `--no-resolution-check` runs but will fail resolution probing
and tarball download. They will be present in the JSON but produce no image file.

## Live demo

A sample report generated from the supported sources is viewable at:
https://jae-63.github.io/select-free-paintings-for-printing/

For future report versions, overwrite `index.html` on the `gh-pages` branch and push.

## Contributing

Pull requests welcome — especially:
- Additional museum API sources (Rijksmuseum, Wikimedia Commons, Musée d'Orsay)
- Improved medium-classification vocabulary for non-English museum metadata
- Additions or corrections to the famous-paintings exclusion list
- Improvements to the HTML report design

## License

MIT. The code is yours to use freely. The artwork images themselves are public
domain — please check individual museum terms if you intend commercial use of
the prints.
