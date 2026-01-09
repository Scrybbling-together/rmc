"""Font configuration, resolution, metrics, and text measurement."""

import logging
import typing as tp
from pathlib import Path

from rmscene import scene_items as si

# Import from parent package
from ... import ASSETS

# Import from device module for SCALE and SCREEN_DPI
from . import device

_logger = logging.getLogger(__name__)

# =============================================================================
# FONT CONFIGURATION
# =============================================================================
# All font files, sizes (in points), and weights are defined here.
# Change these values to adjust text rendering throughout the document.
#
# To add a new font:
# 1. Add .woff2/ttf file to rmc/assets/fonts/
# 2. Add an entry to FONTS below with a unique key
# 3. Reference it in FONT_CONFIG or CSS generation as needed

# Font directory within assets
FONTS_DIR = ASSETS / "fonts"

# Font definitions - maps font keys to their configuration
# Each entry specifies:
#   - file: filename in the fonts directory
#   - family: CSS font-family name
#   - style: CSS font-style (normal, italic)
#   - weight_range: CSS font-weight range for variable fonts
#   - format: font format for CSS (woff2, truetype)
#   - fallback: optional fallback font config if primary doesn't exist
FONTS = {
    "sans": {
        "file": "reMarkableSans.woff2",
        "family": "reMarkable Sans VF",
        "style": "normal",
        "weight_range": "300 700",
        "format": "woff2",
        "fallback": {
            "file": "NotoSans-VariableFont_wdth,wght.ttf",
            "family": "Noto Sans",
            "format": "truetype",
            "weight_range": "100 900",
        },
    },
    "sans_italic": {
        "file": "reMarkableSansItalic.woff2",  # doesn't exist, will trigger fallback
        "family": "reMarkable Sans VF",
        "style": "italic",
        "weight_range": "300 700",
        "format": "woff2",
        "fallback": {
            "file": "NotoSans-Italic-VariableFont_wdth,wght.ttf",
            "family": "Noto Sans",
            "format": "truetype",
            "weight_range": "100 900",
        },
    },
    "serif": {
        "file": "reMarkableSerif.woff2",
        "family": "reMarkable Serif VF",
        "style": "normal",
        "weight_range": "300 800",
        "format": "woff2",
        "fallback": {
            "file": "EBGaramond-VariableFont_wght.ttf",
            "family": "EB Garamond",
            "format": "truetype",
            "weight_range": "400 800",
        },
    },
    "serif_italic": {
        "file": "reMarkableSerifItalic.woff2",
        "family": "reMarkable Serif VF",
        "style": "italic",
        "weight_range": "300 800",
        "format": "woff2",
        "fallback": {
            "file": "EBGaramond-Italic-VariableFont_wght.ttf",
            "family": "EB Garamond",
            "format": "truetype",
            "weight_range": "400 800",
        },
    },
}


def _resolve_font_config(font_key: str) -> tp.Optional[dict]:
    """Resolve font config, falling back if primary font file doesn't exist."""
    font_config = FONTS.get(font_key)
    if font_config is None:
        return None

    primary_path = FONTS_DIR / font_config["file"]
    if primary_path.exists():
        return {
            "file": font_config["file"],
            "family": font_config["family"],
            "style": font_config["style"],
            "weight_range": font_config["weight_range"],
            "format": font_config.get("format", "woff2"),
        }

    # Try fallback
    fallback = font_config.get("fallback")
    if fallback:
        fallback_path = FONTS_DIR / fallback["file"]
        if fallback_path.exists():
            return {
                "file": fallback["file"],
                "family": fallback["family"],
                "style": font_config["style"],  # inherit style from primary
                "weight_range": fallback["weight_range"],
                "format": fallback["format"],
            }

    return None


def _get_resolved_font_family(font_key: str) -> str:
    """Get the resolved font family name for a font key."""
    resolved = _resolve_font_config(font_key)
    if resolved:
        return resolved["family"]
    # Fallback to original config family
    return FONTS[font_key]["family"] if FONTS.get(font_key) else "sans-serif"


# Convenience aliases for font families (resolved dynamically)
# These are initialized lazily to allow fallback resolution
_font_family_serif: tp.Optional[str] = None
_font_family_sans: tp.Optional[str] = None


def _ensure_font_families():
    """Ensure font family globals are initialized."""
    global _font_family_serif, _font_family_sans
    if _font_family_serif is None:
        _font_family_serif = _get_resolved_font_family("serif")
    if _font_family_sans is None:
        _font_family_sans = _get_resolved_font_family("sans")


def get_font_family_serif() -> str:
    """Get the resolved serif font family name."""
    _ensure_font_families()
    return _font_family_serif


def get_font_family_sans() -> str:
    """Get the resolved sans font family name."""
    _ensure_font_families()
    return _font_family_sans


# Keep these for backwards compatibility but they may not reflect fallback fonts
# Use get_font_family_serif() and get_font_family_sans() for resolved names
FONT_FAMILY_SERIF = FONTS["serif"]["family"]
FONT_FAMILY_SANS = FONTS["sans"]["family"]

# Font weight ranges (derived from FONTS config)
FONT_WEIGHT_RANGE_SERIF = FONTS["serif"]["weight_range"]
FONT_WEIGHT_RANGE_SANS = FONTS["sans"]["weight_range"]

# Font configuration per paragraph style
# Each entry contains: family ('serif' or 'sans'), size (in points), weight
FONT_CONFIG = {
    "heading": {
        "family": "serif",
        "size": 15,
        "weight": 450,
    },
    "bold": {
        "family": "sans",
        "size": 8.3,
        "weight": 500,
    },
    "plain": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
    # These styles inherit from plain
    "bullet": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
    "bullet2": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
    "checkbox": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
    "checkbox_checked": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
    "checkbox2": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
    "checkbox2_checked": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
    "numbered": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
    "numbered2": {
        "family": "sans",
        "size": 7.7,
        "weight": 400,
    },
}

# Inline formatting weights
FONT_WEIGHT_INLINE_BOLD = 700


# =============================================================================
# FONT METRICS AND TEXT MEASUREMENT
# =============================================================================

def _get_font_size_pt(style: si.ParagraphStyle) -> float:
    """Get font size in points for a paragraph style."""
    style_name = style.name.lower()
    config = FONT_CONFIG.get(style_name, FONT_CONFIG["plain"])
    return config["size"]


def _get_font_family(style: si.ParagraphStyle) -> str:
    """Get font family key ('serif' or 'sans') for a paragraph style."""
    style_name = style.name.lower()
    config = FONT_CONFIG.get(style_name, FONT_CONFIG["plain"])
    return config["family"]


# Font metrics - loaded lazily
_font_metrics: tp.Optional[dict] = None

def _load_font_metrics():
    """Load font metrics from font files using fonttools.

    Loads all fonts defined in FONTS configuration, using fallbacks as needed.
    """
    global _font_metrics
    if _font_metrics is not None:
        return _font_metrics

    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        _logger.warning("fonttools not available, using estimated character widths")
        _font_metrics = {}
        return _font_metrics

    _font_metrics = {}

    for font_key in FONTS.keys():
        resolved = _resolve_font_config(font_key)
        if resolved is None:
            continue
        font_path = FONTS_DIR / resolved["file"]
        try:
            font = TTFont(font_path)
            _font_metrics[font_key] = {
                'cmap': font.getBestCmap(),
                'hmtx': font['hmtx'],
                'upem': font['head'].unitsPerEm,
            }
        except Exception as e:
            _logger.warning(f"Failed to load {font_key} font from {resolved['file']}: {e}")

    return _font_metrics

def get_char_width_screen(char: str, style: si.ParagraphStyle) -> float:
    """Get character width in screen units using font metrics."""
    if not char:
        return 0.0

    metrics = _load_font_metrics()

    font_key = _get_font_family(style)

    if font_key not in metrics:
        # Fallback to estimated widths based on font size
        font_size = _get_font_size_pt(style)
        # Approximate: average char width is ~0.5 * font size, scaled to screen units
        return font_size * 0.5 * device.rmc_config.screen_dpi / 72

    font = metrics[font_key]
    cmap = font['cmap']
    hmtx = font['hmtx']
    upem = font['upem']

    # Get glyph width in font units
    glyph_name = cmap.get(ord(char))
    if glyph_name:
        width_fu = hmtx[glyph_name][0]
    else:
        width_fu = 500  # fallback

    # Convert to screen units: font_units * (font_size_screen / upem)
    font_size_pt = _get_font_size_pt(style)
    font_size_screen = font_size_pt * device.rmc_config.screen_dpi / 72

    return width_fu * font_size_screen / upem


def get_text_width_screen(text: str, style: si.ParagraphStyle) -> float:
    """Get total width of text string in screen units."""
    return sum(get_char_width_screen(c, style) for c in text)


def wrap_text_to_width(text: str, max_width: float, style: si.ParagraphStyle) -> tp.List[str]:
    """
    Wrap text to fit within max_width, breaking at word boundaries.
    Preserves leading whitespace on the first line.

    :param text: The text to wrap
    :param max_width: Maximum width in screen units
    :param style: Paragraph style (affects character widths)
    :return: List of lines
    """
    if not text:
        return ['']

    # Preserve leading whitespace
    leading_spaces = ''
    stripped_text = text.lstrip(' ')
    if len(stripped_text) < len(text):
        leading_spaces = text[:len(text) - len(stripped_text)]

    # Now wrap the stripped text
    words = stripped_text.split(' ')
    lines = []
    current_line = ''
    current_width = 0.0
    space_width = get_char_width_screen(' ', style)

    # Account for leading spaces in the first line's width
    leading_width = get_text_width_screen(leading_spaces, style) if leading_spaces else 0.0
    first_line = True

    for word in words:
        if not word:  # Skip empty strings from consecutive spaces
            continue

        word_width = get_text_width_screen(word, style)

        if current_line:
            # Check if adding this word (with space) would exceed width
            test_width = current_width + space_width + word_width
            if test_width <= max_width:
                current_line += ' ' + word
                current_width = test_width
            else:
                # Start new line
                lines.append(current_line)
                current_line = word
                current_width = word_width
                first_line = False
        else:
            # First word on line
            if first_line and leading_spaces:
                current_line = leading_spaces + word
                current_width = leading_width + word_width
            else:
                current_line = word
                current_width = word_width

    # Don't forget the last line
    if current_line:
        lines.append(current_line)

    return lines if lines else ['']
