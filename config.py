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

# Smithsonian: free key at https://api.data.gov/signup/
SMITHSONIAN_API_KEY = os.environ.get("SMITHSONIAN_API_KEY", "")

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
MET_REQUEST_DELAY          = 0.35   # ~3 req/s; Met 403s at higher rates without a key
AIC_REQUEST_DELAY          = 0.20   # AIC asks for reasonable use
EUROPEANA_REQUEST_DELAY    = 0.30
SMITHSONIAN_REQUEST_DELAY  = 0.25
CLEVELAND_REQUEST_DELAY    = 0.20
LOC_REQUEST_DELAY          = 0.35   # two requests per item (search + resource)
YCBA_REQUEST_DELAY         = 0.25   # one manifest fetch per item
YCBA_OAI_TIMEOUT           = 60     # OAI-PMH server is slow; 15s default times out

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
You are selecting oil paintings for high-resolution canvas printing in a home.

Rate this painting combining TWO criteria into a single 1-5 score:

SUBJECT (does it suit a home?)
- Landscapes, seascapes, coastal/river views, pastoral scenes = good
- Portraits, figure studies, battle scenes, mythological scenes = bad
- Still lifes, animal studies = neutral (only pass if also smooth)

TECHNIQUE (will it print well flat?)
- Smooth, flat, glazed, luminous brushwork = good
- Heavy impasto / thick 3D texture = bad (texture disappears in a flat print)

Scoring:
  1 = Bad subject (portrait/battle) OR heavy impasto — reject
  2 = Portrait or figure painting, or very textured — likely reject
  3 = Borderline: acceptable subject with moderate texture, or good subject slightly textured
  4 = Landscape/seascape with smooth or flat technique — good
  5 = Ideal landscape/seascape, very smooth or glazed technique — excellent

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
# "photograph" is included so LoC and similar photo sources pass this filter;
# photographs are flat / smooth and print well on canvas.
OIL_MEDIUM_TERMS = [
    "oil on canvas", "oil on panel", "oil on board", "oil on wood",
    "oil on copper", "oil on paper", "huile sur toile",
    "photograph",
]

# If any of these terms appear in medium or description → reject as impasto
IMPASTO_DISQUALIFY_TERMS = [
    "impasto",
    "heavily textured",
    "thick paint",
    "palette knife",
    "encaustic",
]

# Medium terms that indicate a reproductive or print process rather than an
# original painting — excluded regardless of whether "watercolor" also appears.
# E.g. "Color lithograph; watercolor facsimile" should not pass as a watercolor.
EXCLUDE_MEDIUM_TERMS = [
    "lithograph",
    "facsimile",
    "engraving",
    "etching",
    "aquatint",
    "mezzotint",
    "woodcut",
    "screenprint",
    "silkscreen",
    "photogravure",
    "chromolithograph",
    "reproduction",
    "printed",
    "daguerreotype",
]

# If any of these appear in medium/description → heuristically flag as smooth oil
# "photograph" is included so photos don't need Claude vision or artist matching
SMOOTH_OIL_MEDIUM_HINT_TERMS = [
    "glazing", "glaze", "smooth", "detailed", "luminous", "academic", "trompe",
    "photograph",
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
    # British and Italian landscape/view painters (primary YCBA collection)
    "canaletto",
    "samuel scott",
    "richard parkes bonington", "bonington",
    "edward lear",
    "richard wilson",
    "thomas gainsborough",
    "george morland",
    "john constable", "constable",
    "francis danby",
    "james ward",
    "patrick nasmyth",
    "julius caesar ibbetson",
    "william marlow",
    "john crome",
    "peter de wint",
    "george vincent",
    "james stark",
    "john berney crome",
    "thomas girtin", "girtin",
    "john varley",
    "david cox",
    "peter de wint",
    "william daniell",
    "george fennel robson",
    "clarkson stanfield",
    "thomas creswick",
    "benjamin williams leader",
    "henry john boddington",
    "george cole",
    "john linnell",
    "samuel palmer", "palmer",
    "james holland",
    "charles bentley",
    "william henry hunt",
    "william james muller",
    "william james webb",
    "john brett",
]

# ---------------------------------------------------------------------------
# NON-PAINTING SUBJECT FILTER  (always on — these are never suitable)
# ---------------------------------------------------------------------------

# Title substrings indicating decorative arts, architectural drawings,
# botanical illustrations, or other non-painting works that museum APIs
# return when searching for "watercolor". Applied unconditionally.
NON_PAINTING_TITLE_TERMS = [
    # Decorative / applied arts
    "design for", "design of", "design drawing",
    "stained glass",
    "wallpaper", "wall paper",
    "valance", "pelmet", "curtain",
    "rug ", " rug", "carpet",
    "chair back", "chair cover", "sofa",
    "chimneypiece", "chimney piece",
    "overmantel", "girandole", "pier-glass", "pier glass",
    "chandelier", "candelabra", "candelabrum",
    "vase design", "vessel design",
    "furniture design",
    "embroidery", "textile",
    # Vehicles
    "road coach", "coach #", "carriage",
    # Architectural / engineering
    "floor plan", "site plan", "elevation", "section drawing",
    "plans and elevations",
    # Botanical / natural history (unless clearly landscape)
    "study of capers", "study of flowers", "study of leaves",
    "study of insects", "study of beetles",
    "fritillar", "botanical",
    # Reproductions and copies
    "reproduction.", ", reproduction",
    # Untitled / missing metadata signals
    "#agentof",  # malformed Europeana agent IDs in title field
    # Figure studies (not landscapes)
    "nude male figure", "nude female figure",
    "study of a figure", "figure study",
]

# ---------------------------------------------------------------------------
# RELIGIOUS IMAGERY FILTER  (opt-in via --exclude-religious CLI flag)
# ---------------------------------------------------------------------------

# Title substrings (case-insensitive) that suggest religious subject matter.
# Applied only when --exclude-religious is passed to fetch_candidates.py.
# Add terms freely — false positives are better than false negatives here
# since this is a personal-taste filter, not a quality filter.
RELIGIOUS_TITLE_TERMS = [
    # Christian figures and events
    "madonna", "virgin", "annunciation", "nativity", "crucifixion",
    "resurrection", "ascension", "assumption", "pietà", "pieta",
    "saint ", "st.", "st ", "santa ", "san ", "santo ",
    "jesus", "christ", "holy", "sacred", "divine",
    "angel", "archangel", "seraph", "cherub",
    "apostle", "disciple", "prophet", "martyr",
    "baptism", "adoration", "lamentation", "entombment",
    "pentecost", "transfiguration", "epiphany",
    "madonna", "our lady", "blessed virgin",
    "cathedral", "abbey", "chapel", "monastery", "convent",
    "altar", "reliquary", "icon",
    # Old Testament / Hebrew Bible
    "moses", "noah", "abraham", "isaac", "jacob", "joseph",
    "david", "solomon", "elijah", "samson", "judith",
    "eden", "paradise", "exodus", "creation of",
    # Greek/Roman mythology treated as religious
    "zeus", "jupiter", "apollo", "venus", "diana", "minerva",
    "hercules", "heracles", "bacchus", "dionysus", "mercury",
    "neptune", "poseidon", "mars", "ares", "juno", "hera",
    "athena", "prometheus", "orpheus", "eurydice",
    # Islamic / other
    "allah", "muhammad", "quran",
    # Generic religious
    "miracle", "vision of", "temptation of", "martyrdom",
    "last supper", "last judgment", "day of judgment",
    "heaven", "hell", "purgatory", "paradise",
    "sermon", "prayer", "worship", "pilgrimage",
    "church of", "basilica", "mosque", "temple of",
    "saint ", "sainte ", "san ", "santa ", "santo ",
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
