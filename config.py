"""
config.py

Single source of truth for all parameters in canvas_finder.
Edit this file to change behavior without touching any other script.

API keys are loaded from environment variables or a .env file (never hardcoded).
See config.example.env for the template.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env file if present (for local development convenience)
# Never commit the actual .env file — it's in .gitignore
# ---------------------------------------------------------------------------
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


# ===========================================================================
# API KEYS  (read from environment — never hardcode)
# ===========================================================================

# Europeana: free key at https://apis.europeana.eu/api/apikey-form
EUROPEANA_API_KEY = os.environ.get("EUROPEANA_API_KEY", "")

# Anthropic: for Claude vision oil-smoothness classification
# Free at https://console.anthropic.com — but see note below on key reuse.
# If blank, the oil classifier falls back to heuristics only.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# ===========================================================================
# SEARCH & FILTERING TARGETS
# ===========================================================================

# Number of qualifying works to find in each category
WATERCOLOR_TARGET = 80
OIL_TARGET = 20

# Minimum width/height aspect ratio (landscape orientation)
# 1.4 means width must be at least 40% greater than height
MIN_ASPECT_RATIO = 1.4

# Minimum pixel width of the downloadable full image,
# to achieve 200 DPI when printed at PRINT_WIDTH_INCHES
PRINT_WIDTH_INCHES = 40
PRINT_DPI = 200
MIN_PIXEL_WIDTH = PRINT_WIDTH_INCHES * PRINT_DPI  # = 8000

# Maximum candidates to pull from each API source before filtering.
# Increase if not reaching targets; decrease for faster test runs.
MAX_CANDIDATES_PER_SOURCE = 4000  # raised from 2000; AIC needs more to hit watercolor target


# ===========================================================================
# API SOURCE SETTINGS
# ===========================================================================

# Which sources to query by default (can be overridden via CLI --sources)
DEFAULT_SOURCES = ["met", "aic"]

# Politeness delay between API requests, in seconds, per source
MET_REQUEST_DELAY    = 0.35   # ~3 req/s; Met 403s at higher rates without a key
AIC_REQUEST_DELAY    = 0.20   # AIC asks for reasonable use
EUROPEANA_REQUEST_DELAY = 0.30

# Max pages to fetch per query per source (each page = up to 100 results)
AIC_MAX_PAGES_PER_QUERY = 10
EUROPEANA_MAX_PAGES_PER_QUERY = 5
EUROPEANA_MAX_RESULTS_PER_QUERY = 500  # hard cap regardless of pagination

# HTTP request timeout in seconds
HTTP_TIMEOUT = 15
HTTP_TIMEOUT_IMAGE = 30   # longer for image downloads

# User-Agent string sent with all requests
# If sharing this project, update with your own contact info
HTTP_USER_AGENT = (
    "CanvasPrintFinder/1.0 "
    "(public-domain art research; https://github.com/YOUR_USERNAME/canvas-print-finder)"
)

# Number of bytes to read when probing image dimensions from a URL
# 64KB is enough for JPEG/PNG/TIFF headers in nearly all cases
IMAGE_PROBE_CHUNK_BYTES = 65536

# Number of retries for transient API errors
HTTP_RETRIES = 3


# ===========================================================================
# TARBALL / PREVIEW IMAGE SETTINGS
# ===========================================================================

# Target total pixels for preview images in the slideshow tarball.
# 500 × 350 = 175,000 ≈ quarter-megapixel. Increase for sharper previews.
PREVIEW_TARGET_PIXELS = 500 * 350   # ~175k pixels

# JPEG quality for saved preview images (1–95)
PREVIEW_JPEG_QUALITY = 85

# Width (px) to request from AIC IIIF server for preview downloads
# (AIC resizes server-side, so we don't have to download full images)
AIC_PREVIEW_WIDTH_PX = 700

# Parallel download workers for make_tarball.py
# Be gentle — museum servers are shared infrastructure
TARBALL_DOWNLOAD_WORKERS = 3
TARBALL_DOWNLOAD_DELAY   = 0.30   # seconds between requests per worker

# Directory name inside the tarball
TARBALL_INNER_DIR = "canvas_picks"


# ===========================================================================
# CLAUDE VISION — OIL SMOOTHNESS CLASSIFICATION
# ===========================================================================

# Whether to use Claude vision API to assess oil painting smoothness.
# Requires ANTHROPIC_API_KEY to be set.
# Falls back to heuristic (artist name / medium keyword) if disabled or no key.
USE_CLAUDE_VISION = True

# Model to use for vision classification
CLAUDE_VISION_MODEL = "claude-sonnet-4-20250514"

# Max tokens for vision classification response (short answer expected)
CLAUDE_VISION_MAX_TOKENS = 150

# Delay between Claude API calls (seconds) to stay within rate limits
CLAUDE_VISION_DELAY = 0.5

# Confidence threshold: Claude returns a score 1–5.
# Works rated >= this threshold are considered "smooth enough" for canvas.
# 3 = "moderate smoothness, probably fine"; 4 = "clearly smooth"
CLAUDE_VISION_SMOOTHNESS_THRESHOLD = 3

# Prompt sent to Claude for each oil painting thumbnail
CLAUDE_VISION_PROMPT = """\
You are evaluating whether an oil painting would make an attractive canvas print.

For canvas printing purposes, paintings with SMOOTH, FLAT, or GLAZED brushwork
reproduce well. Paintings with HEAVY IMPASTO (thick 3D paint texture) do NOT
reproduce well on flat canvas prints — the texture is lost and the image looks muddy.

Look at this painting thumbnail and rate its surface smoothness on this scale:
  1 = Heavy impasto / very thick texture (e.g. Van Gogh's Starry Night style)
  2 = Moderate texture / visible brushstrokes
  3 = Some texture but mostly flat / moderate impressionism
  4 = Smooth / flat / luminous (e.g. Whistler, Corot, Luminist style)
  5 = Very smooth / almost photographic / glazed (e.g. academic, Dutch Golden Age)

Reply with ONLY a single digit (1–5) and nothing else.
"""

# ---------------------------------------------------------------------------
# MEDIUM CLASSIFICATION VOCABULARY
# These lists drive filters.py — edit here to broaden/narrow medium detection
# ---------------------------------------------------------------------------

# Any of these terms in the medium field → classify as "watercolor"
WATERCOLOR_MEDIUM_TERMS = [
    "watercolor", "watercolour", "water color", "water colour",
    "aquarelle", "gouache", "wash",
]

# Any of these terms in the medium field → candidate oil painting
OIL_MEDIUM_TERMS = [
    "oil on canvas", "oil on panel", "oil on board", "oil on wood",
    "oil on copper", "oil on paper", "huile sur toile",
]

# If any of these terms appear in medium or description → reject as impasto
IMPASTO_DISQUALIFY_TERMS = [
    "impasto",
    "heavily textured",
    "thick paint",
    "palette knife",
    "encaustic",
]

# If any of these appear in medium/description → heuristically flag as smooth oil
SMOOTH_OIL_MEDIUM_HINT_TERMS = [
    "glazing", "glaze", "smooth", "detailed", "luminous", "academic", "trompe",
]

# Artists whose oils are typically smooth/flat enough for canvas printing.
# This list is the heuristic fallback when Claude vision is disabled or unavailable.
# All entries are lowercase substrings matched against the normalized artist name.
SMOOTH_OIL_ARTISTS = [
    "whistler", "corot", "inness", "gifford",
    "kensett", "john kensett",
    "fitz henry lane", "lane",
    "martin johnson heade", "heade",
    "george inness",
    "camille corot",
    "camille pissarro",
    "alfred sisley",
    "berthe morisot",
    "armand guillaumin",
    "jean-baptiste", "vernet", "claude-joseph vernet",
    "nicolas poussin", "poussin",
    "claude lorrain", "lorrain",
    "jacob van ruisdael", "ruisdael",
    "meindert hobbema", "hobbema",
    "aelbert cuyp", "cuyp",
    "jan van goyen", "van goyen",
    "salomon van ruysdael",
    "pieter de molijn",
    "jan both",
    "adam pynacker",
    "philips koninck",
    "thomas cole",
    "asher durand",
    "thomas doughty",
    "jasper cropsey",
    "sanford robinson gifford",
    "worthington whittredge",
    "william trost richards",
    "david johnson",
    "childe hassam",
    "john henry twachtman", "twachtman",
    "julian alden weir",
    "frank weston benson",
    "edmund tarbell",
    "theodore robinson",
    "willard leroy metcalf",
    "dennis miller bunker",
    "robert vonnoh",
    "maxfield parrish",
    "joaquin sorolla", "sorolla",
    "anders zorn",
    "carl larsson",
    "peder monsted",
    "fritz thaulow",
    "hans dahl",
    "charles-francois daubigny", "daubigny",
    "eugene boudin", "boudin",
    "ivan shishkin", "shishkin",
    "isaak levitan", "levitan",
    "arkhip kuindzhi", "kuindzhi",
    "vasily polenov", "polenov",
    "fyodor vasilyev", "vasilyev",
    "albert marquet", "marquet",
    "henri le sidaner", "le sidaner",
    "edward seago", "seago",
    "albert bierstadt", "bierstadt",
    "frederic church",
    "thomas cole",
]

# ---------------------------------------------------------------------------
# HTML REPORT APPEARANCE
# ---------------------------------------------------------------------------

REPORT_TITLE = "Canvas Print Candidates"
REPORT_SUBTITLE = (
    "Public-domain landscapes filtered for high-resolution canvas printing "
    "(≥{dpi} DPI at {width}\")".format(dpi=PRINT_DPI, width=PRINT_WIDTH_INCHES)
)

# Max characters shown for medium description in the HTML card
REPORT_MEDIUM_TRUNCATE = 80

# Max characters for artist name in HTML card
REPORT_ARTIST_TRUNCATE = 60

# Max characters for title in HTML card
REPORT_TITLE_TRUNCATE = 80

# ---------------------------------------------------------------------------
# MISC
# ---------------------------------------------------------------------------

# Default output filenames
DEFAULT_CANDIDATES_FILE = "candidates.json"
DEFAULT_REPORT_FILE     = "report.html"
DEFAULT_TARBALL_FILE    = "canvas_picks.tar.gz"
