"""
oil_classifier.py

Uses the Anthropic Claude vision API to assess whether an oil painting
has smooth/flat brushwork suitable for canvas printing, rather than
heavy impasto texture that would look poor when printed flat.

Falls back to heuristics (filters.is_smooth_oil_heuristic) when:
  - ANTHROPIC_API_KEY is not set
  - USE_CLAUDE_VISION is False in config
  - The API call fails for any reason

No separate API key is needed if you already have one in your environment
from using Claude.ai Pro via the API. The key is read from the ANTHROPIC_API_KEY
environment variable (or .env file). See config.example.env.

Rate note: Claude API has a free tier. This classifier is called only for
candidate oil paintings (expected: O(20–100) calls per full run), so
usage should remain well within free-tier limits.
"""

import base64
import io
import time
import requests
import config
from filters import is_smooth_oil_heuristic, classify_medium


# ---------------------------------------------------------------------------
# Internal state: lazily initialised Anthropic client
# ---------------------------------------------------------------------------

_client = None
_vision_available = None   # None = not yet tested; True/False after first attempt


def _get_client():
    """Lazily create the Anthropic client. Returns None if unavailable."""
    global _client, _vision_available

    if _vision_available is False:
        return None

    if _client is not None:
        return _client

    if not config.USE_CLAUDE_VISION:
        _vision_available = False
        return None

    if not config.ANTHROPIC_API_KEY:
        print("[vision] ANTHROPIC_API_KEY not set — falling back to heuristics.")
        _vision_available = False
        return None

    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        _vision_available = True
        print(f"[vision] Claude vision enabled ({config.CLAUDE_VISION_MODEL})")
        return _client
    except ImportError:
        print("[vision] 'anthropic' package not installed. Run: pip install anthropic")
        print("[vision] Falling back to heuristics.")
        _vision_available = False
        return None


def _fetch_thumbnail_b64(url: str) -> str | None:
    """
    Download a small image from url and return as base64-encoded JPEG string.
    Resizes to a small thumbnail to minimise token cost.
    """
    try:
        from PIL import Image

        resp = requests.get(
            url,
            timeout=config.HTTP_TIMEOUT_IMAGE,
            headers={"User-Agent": config.HTTP_USER_AGENT},
        )
        resp.raise_for_status()

        img = Image.open(io.BytesIO(resp.content)).convert("RGB")

        # Shrink to at most 512px on the long side — enough for texture assessment
        MAX_SIDE = 512
        w, h = img.size
        if max(w, h) > MAX_SIDE:
            scale = MAX_SIDE / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    except Exception as e:
        print(f"  [vision] Thumbnail fetch failed: {e}")
        return None


def _ask_claude(image_b64: str, artist: str, title: str) -> int | None:
    """
    Send image to Claude and get a smoothness score 1–5.
    Returns int 1–5, or None on failure.
    """
    client = _get_client()
    if client is None:
        return None

    try:
        message = client.messages.create(
            model=config.CLAUDE_VISION_MODEL,
            max_tokens=config.CLAUDE_VISION_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f'Artist: {artist}\nTitle: "{title}"\n\n'
                                + config.CLAUDE_VISION_PROMPT
                            ),
                        },
                    ],
                }
            ],
        )
        raw = message.content[0].text.strip()
        # Expect a single digit 1–5
        if raw and raw[0].isdigit():
            score = int(raw[0])
            if 1 <= score <= 5:
                return score
        # Claude returned non-numeric text (e.g. refused, got a non-painting image)
        return None
    except Exception as e:
        print(f"  [vision] Claude API error: {e}")
        return None


def is_smooth_oil(
    artist: str,
    title: str,
    medium: str,
    image_url: str = "",
    description: str = "",
) -> bool:
    """
    Primary entry point: decide whether an oil painting is smooth enough
    for canvas printing.

    1. If medium is impasto or not oil → False immediately.
    2. Try Claude vision if enabled and image_url is available.
       Score >= CLAUDE_VISION_SMOOTHNESS_THRESHOLD → True.
    3. Fall back to heuristic if vision unavailable or fails.

    Args:
        artist:      Artist display name
        title:       Artwork title
        medium:      Medium string from museum metadata
        image_url:   URL for a small/medium image to send to Claude (optional)
        description: Additional text description (for heuristic fallback)

    Returns:
        True if the work is considered smooth-technique, False otherwise.
    """
    med_class = classify_medium(medium)
    if med_class != "oil":
        return False   # impasto_oil, watercolor, other — not what we want here

    # Try Claude vision
    client = _get_client()
    if client is not None and image_url:
        image_b64 = _fetch_thumbnail_b64(image_url)
        if image_b64:
            score = _ask_claude(image_b64, artist, title)
            time.sleep(config.CLAUDE_VISION_DELAY)

            if score is not None:
                smooth = score >= config.CLAUDE_VISION_SMOOTHNESS_THRESHOLD
                label = f"{score}/5 ({'✓ smooth' if smooth else '✗ textured'})"
                print(f"    [vision] {artist} — {title!r}: {label}")
                return smooth

    # Heuristic fallback
    result = is_smooth_oil_heuristic(artist, medium, description)
    return result


def vision_status() -> str:
    """Return a human-readable status string for use in help/report output."""
    if not config.USE_CLAUDE_VISION:
        return "disabled (USE_CLAUDE_VISION=False in config.py)"
    if not config.ANTHROPIC_API_KEY:
        return "disabled (ANTHROPIC_API_KEY not set)"
    return f"enabled ({config.CLAUDE_VISION_MODEL}, threshold={config.CLAUDE_VISION_SMOOTHNESS_THRESHOLD}/5)"
