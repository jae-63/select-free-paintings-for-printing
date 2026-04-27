"""
filters.py

Filtering logic for aspect ratio, pixel resolution, and medium classification.
All thresholds and vocabulary lists come from config.py.
"""

import re
import config


def classify_medium(medium: str) -> str:
    """
    Classify a medium string into one of:
      'watercolor'   — watercolor, gouache, aquarelle, wash, etc.
      'impasto_oil'  — oil with texture keywords (disqualified)
      'oil'          — oil painting without impasto flags
      'other'        — unrecognized medium

    Vocabulary lists are defined in config.py.
    """
    m = (medium or "").lower()

    # Reproductive / print processes disqualify regardless of other terms.
    # Catches e.g. "Color lithograph; watercolor facsimile".
    for kw in config.EXCLUDE_MEDIUM_TERMS:
        if kw in m:
            return "other"

    for kw in config.IMPASTO_DISQUALIFY_TERMS:
        if kw in m:
            return "impasto_oil"

    for term in config.WATERCOLOR_MEDIUM_TERMS:
        if term in m:
            return "watercolor"

    is_oil = any(term in m for term in config.OIL_MEDIUM_TERMS) or "oil" in m
    if is_oil:
        return "oil"

    return "other"


def is_smooth_oil_heuristic(artist: str, medium: str, description: str = "") -> bool:
    """
    Heuristic fallback (no AI): returns True if this oil painting is likely
    smooth-technique based on artist name and medium keywords.
    Used when Claude vision is disabled or the API key is absent.
    """
    med_class = classify_medium(medium)
    if med_class != "oil":
        return False

    combined = (medium + " " + description).lower()

    for kw in config.SMOOTH_OIL_MEDIUM_HINT_TERMS:
        if kw in combined:
            return True

    artist_lower = artist.lower()
    for fragment in config.SMOOTH_OIL_ARTISTS:
        if fragment in artist_lower:
            return True

    return False


def check_aspect_ratio(width: float, height: float, min_ratio: float = None) -> bool:
    """Returns True if width / height >= min_ratio (default from config)."""
    if min_ratio is None:
        min_ratio = config.MIN_ASPECT_RATIO
    if height <= 0:
        return False
    return (width / height) >= min_ratio


def check_pixel_resolution(pixel_width: int, min_pixels: int = None) -> bool:
    """Returns True if pixel_width meets the minimum (default from config)."""
    if min_pixels is None:
        min_pixels = config.MIN_PIXEL_WIDTH
    return pixel_width >= min_pixels


def required_pixel_width(print_width_inches: float = None, print_dpi: int = None) -> int:
    """Return the minimum pixel width for the configured print specs."""
    if print_width_inches is None:
        print_width_inches = config.PRINT_WIDTH_INCHES
    if print_dpi is None:
        print_dpi = config.PRINT_DPI
    return int(print_width_inches * print_dpi)


def parse_dimensions_from_string(dim_str: str) -> tuple:
    """
    Extract (width, height) from a museum dimension string.

    Handles common formats:
      '163.5 × 114.5 cm'
      '81.3 x 101.6 cm (32 x 40 in.)'
      '40 3/8 x 50 1/4 in.'
      '12 × 8'   (bare numbers assumed cm)

    Returns (width_cm, height_cm) or (None, None) if not parseable.

    Note: museums often list H × W, but for ratio-checking we take the
    larger number as width regardless of listing order.
    """
    if not dim_str:
        return None, None

    cm_match = re.findall(r"([\d]+\.?[\d]*)\s*[×xX]\s*([\d]+\.?[\d]*)\s*cm", dim_str)
    if cm_match:
        return float(cm_match[0][0]), float(cm_match[0][1])

    in_match = re.findall(
        r"([\d]+\.?[\d]*)\s*[×xX]\s*([\d]+\.?[\d]*)\s*in", dim_str, re.IGNORECASE
    )
    if in_match:
        return float(in_match[0][0]) * 2.54, float(in_match[0][1]) * 2.54

    frac = re.findall(
        r"(\d+)\s+(\d+)/(\d+)\s*[×xX]\s*(\d+)\s+(\d+)/(\d+)\s*in",
        dim_str, re.IGNORECASE
    )
    if frac:
        m = frac[0]
        w = (int(m[0]) + int(m[1]) / int(m[2])) * 2.54
        h = (int(m[3]) + int(m[4]) / int(m[5])) * 2.54
        return w, h

    bare = re.findall(r"([\d]+\.?[\d]*)\s*[×xX]\s*([\d]+\.?[\d]*)", dim_str)
    if bare:
        return float(bare[0][0]), float(bare[0][1])

    return None, None


def is_religious_title(title: str) -> bool:
    """
    Returns True if the title suggests religious subject matter.
    Used only when --exclude-religious is passed; not a default filter.
    Term list is defined in config.RELIGIOUS_TITLE_TERMS.
    """
    t = (title or "").lower()
    for term in config.RELIGIOUS_TITLE_TERMS:
        if term in t:
            return True
    return False


def dimensions_are_landscape(w, h, min_ratio: float = None) -> bool:
    """
    Return True if the larger dimension / smaller dimension >= min_ratio.

    Museums list dimensions inconsistently — some use W×H, others H×W.
    We always take max/min so that a painting listed as either "30×50cm"
    or "50×30cm" is correctly identified as landscape-oriented.
    This means we accept any work whose longer axis is >= min_ratio times
    its shorter axis, regardless of which the museum lists first.
    """
    if w is None or h is None:
        return False
    larger, smaller = max(w, h), min(w, h)
    return check_aspect_ratio(larger, smaller, min_ratio)


if __name__ == "__main__":
    print("=== Medium classification ===")
    cases = [
        ("Watercolor on paper", "watercolor"),
        ("Watercolour and gouache", "watercolor"),
        ("Oil on canvas", "oil"),
        ("Oil on canvas with impasto technique", "impasto_oil"),
        ("Gouache on board", "watercolor"),
        ("Tempera on panel", "other"),
        ("Huile sur toile", "oil"),
    ]
    for medium, expected in cases:
        result = classify_medium(medium)
        ok = "✓" if result == expected else f"✗ (expected {expected})"
        print(f"  {ok}  {medium!r} → {result}")

    print("\n=== Dimension parsing ===")
    for s in ["163.5 × 114.5 cm", "40 3/8 x 50 1/4 in.", "12 × 8"]:
        w, h = parse_dimensions_from_string(s)
        print(f"  {s!r} → {w}, {h}  landscape={dimensions_are_landscape(w, h)}")

    print("\n=== Smooth oil heuristic ===")
    oil_cases = [
        ("Joaquin Sorolla", "Oil on canvas", True),
        ("Vincent van Gogh", "Oil, impasto", False),
        ("James McNeill Whistler", "Oil on canvas", True),
        ("Unknown Artist", "Oil on canvas", False),
    ]
    for artist, medium, expected in oil_cases:
        result = is_smooth_oil_heuristic(artist, medium)
        ok = "✓" if result == expected else f"✗ (expected {expected})"
        print(f"  {ok}  {artist!r} → {result}")
