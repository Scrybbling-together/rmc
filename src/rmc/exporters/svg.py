"""Convert blocks to svg file.

Code originally from https://github.com/lschwetlick/maxio through
https://github.com/chemag/maxio .
"""

import logging
import string
import base64
import typing as tp
from pathlib import Path

from rmscene.scene_items import Pen as PenType
from rmscene import CrdtId, SceneTree, read_tree
from rmscene import scene_items as si
from rmscene.text import TextDocument
from xml.etree.ElementTree import _escape_attrib

from .writing_tools import Pen

from .. import ASSETS

_logger = logging.getLogger(__name__)

# Device profiles with screen dimensions
DEVICE_PROFILES = {
    "RM2": {"width": 1404, "height": 1872, "dpi": 226},
    "RMPP": {"width": 1620, "height": 2160, "dpi": 229},
}

# Current device profile (default to RMPP)
_current_device = "RMPP"

def set_device(device: str) -> None:
    """Set the current device profile. Valid values: 'RM2', 'RMPP'"""
    global _current_device, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_DPI
    global SCALE, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, X_SHIFT
    
    if device not in DEVICE_PROFILES:
        raise ValueError(f"Unknown device: {device}. Valid options: {list(DEVICE_PROFILES.keys())}")
    
    _current_device = device
    profile = DEVICE_PROFILES[device]
    SCREEN_WIDTH = profile["width"]
    SCREEN_HEIGHT = profile["height"]
    SCREEN_DPI = profile["dpi"]
    SCALE = 72.0 / SCREEN_DPI
    PAGE_WIDTH_PT = SCREEN_WIDTH * SCALE
    PAGE_HEIGHT_PT = SCREEN_HEIGHT * SCALE
    X_SHIFT = PAGE_WIDTH_PT // 2
    _logger.debug(f"Set device to {device}: {SCREEN_WIDTH}x{SCREEN_HEIGHT} @ {SCREEN_DPI} DPI")

def get_device() -> str:
    """Get the current device profile name."""
    return _current_device

def detect_device_from_pdf_size(width_pt: float, height_pt: float) -> str:
    """
    Detect the most likely device based on PDF page dimensions.
    
    :param width_pt: PDF page width in points
    :param height_pt: PDF page height in points
    :return: Device name ('RM2' or 'RMPP')
    """
    best_device = "RMPP"
    best_score = float('inf')
    
    for device, profile in DEVICE_PROFILES.items():
        scale = 72.0 / profile["dpi"]
        expected_w = profile["width"] * scale
        expected_h = profile["height"] * scale
        
        # Calculate how close this device's dimensions are to the PDF
        # Use ratio comparison to handle different aspect ratios
        w_ratio = width_pt / expected_w
        h_ratio = height_pt / expected_h
        
        # Score based on how close ratios are to 1.0
        score = abs(1 - w_ratio) + abs(1 - h_ratio)
        
        if score < best_score:
            best_score = score
            best_device = device
    
    _logger.debug(f"Detected device {best_device} for PDF size {width_pt}x{height_pt} pt (score={best_score:.3f})")
    return best_device

def set_device_from_pdf_size(width_pt: float, height_pt: float) -> str:
    """
    Detect and set the device profile based on PDF page dimensions.
    
    :param width_pt: PDF page width in points
    :param height_pt: PDF page height in points
    :return: Device name that was set
    """
    device = detect_device_from_pdf_size(width_pt, height_pt)
    set_device(device)
    return device

# Initialize with default device (RMPP)
SCREEN_WIDTH = DEVICE_PROFILES["RMPP"]["width"]
SCREEN_HEIGHT = DEVICE_PROFILES["RMPP"]["height"]
SCREEN_DPI = DEVICE_PROFILES["RMPP"]["dpi"]

# Margin to add around content bounding box (in screen units)
BBOX_MARGIN = 0

TEXT_DOCUMENT_TOP_Y_CRDT_ID = 0xfffffffffffe
TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID = 0xffffffffffff

SCALE = 72.0 / SCREEN_DPI

PAGE_WIDTH_PT = SCREEN_WIDTH * SCALE
PAGE_HEIGHT_PT = SCREEN_HEIGHT * SCALE
X_SHIFT = PAGE_WIDTH_PT // 2


# Checkbox positioning constants (used in both build_anchor_pos and draw_text)
CHECKBOX_SIZE = 12  # Size in points
CHECKBOX_TEXT_GAP = 4  # Gap between checkbox and text in points
CHECKBOX_ITEM_SPACING = 30  # Extra spacing between checkbox items in screen units
CHECKBOX2_INDENT = 12  # Indentation for nested checkbox in points

# Bullet list positioning constants
BULLET_SIZE = 4  # Bullet circle diameter in points
BULLET_INDENT = 12  # Indentation for bullet text in points
BULLET2_INDENT = 24  # Indentation for nested bullet text in points
BULLET_GAP = 6  # Gap between bullet and text in points
BULLET_ITEM_SPACING = 20  # Extra spacing between bullet items in screen units
BULLET_SECTION_GAP = 30  # Gap before bullet section starts (from non-bullet paragraph)

# Numbered list constants
NUMBERED_INDENT = 12  # Indentation for numbered list text in points (matching BULLET_INDENT)
NUMBERED2_INDENT = 24  # Indentation for nested numbered list text in points (matching BULLET2_INDENT)
NUMBERED_GAP = 4  # Gap between number and text in points
NUMBERED2_OFFSET = 12  # Offset for nested numbered list number position

# Text wrap margin - the device appears to use less than the full text.width
# for line wrapping. This margin is subtracted from text.width.
TEXT_WRAP_MARGIN = 236  # Approximate margin in screen units

def scale(screen_unit: float) -> float:
    return screen_unit * SCALE


# For now, at least, the xx and yy function are identical to scale
xx = scale
yy = scale

TEXT_TOP_Y = -88
base = 69.5
LINE_HEIGHTS = {
    si.ParagraphStyle.PLAIN: base,
    si.ParagraphStyle.BULLET: base/2,
    si.ParagraphStyle.BULLET2: base/2,
    si.ParagraphStyle.BOLD: base,
    si.ParagraphStyle.HEADING: base*2,
    si.ParagraphStyle.CHECKBOX: base/2,
    si.ParagraphStyle.CHECKBOX_CHECKED: base/2,
    si.ParagraphStyle.CHECKBOX2: base/2,
    si.ParagraphStyle.CHECKBOX2_CHECKED: base/2,
    si.ParagraphStyle.NUMBERED: base/2,
    si.ParagraphStyle.NUMBERED2: base/2,
}

# Extra space to add AFTER certain paragraph styles
# This creates visual separation between headings and body text
SPACE_AFTER = {
    si.ParagraphStyle.HEADING: base * 0.5,  # Add extra space after headings
}

# Soft line heights for LINE_SEPARATOR (U+2028) breaks within paragraphs
# These are tighter than paragraph breaks
soft_base = 60
small_soft_base = 40
SOFT_LINE_HEIGHTS = {
    si.ParagraphStyle.PLAIN: soft_base,
    si.ParagraphStyle.BULLET: small_soft_base,
    si.ParagraphStyle.BULLET2: small_soft_base,
    si.ParagraphStyle.BOLD: small_soft_base,
    si.ParagraphStyle.HEADING: soft_base,
    si.ParagraphStyle.CHECKBOX: small_soft_base,
    si.ParagraphStyle.CHECKBOX_CHECKED: small_soft_base,
    si.ParagraphStyle.CHECKBOX2: small_soft_base,
    si.ParagraphStyle.CHECKBOX2_CHECKED: small_soft_base,
    si.ParagraphStyle.NUMBERED: small_soft_base,
    si.ParagraphStyle.NUMBERED2: small_soft_base,
}

# Font sizes in points (from CSS styles)
FONT_SIZES_PT = {
    si.ParagraphStyle.PLAIN: 7.7,
    si.ParagraphStyle.BULLET: 7.7,
    si.ParagraphStyle.BULLET2: 7.7,
    si.ParagraphStyle.BOLD: 8.3,
    si.ParagraphStyle.HEADING: 15,
    si.ParagraphStyle.CHECKBOX: 7.7,
    si.ParagraphStyle.CHECKBOX_CHECKED: 7.7,
    si.ParagraphStyle.CHECKBOX2: 7.7,
    si.ParagraphStyle.CHECKBOX2_CHECKED: 7.7,
    si.ParagraphStyle.NUMBERED: 7.7,
    si.ParagraphStyle.NUMBERED2: 7.7,
}

# Font metrics - loaded lazily
_font_metrics: tp.Optional[dict] = None

def _load_font_metrics():
    """Load font metrics from woff2 files using fonttools."""
    global _font_metrics
    if _font_metrics is not None:
        return _font_metrics
    
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        _logger.warning("fonttools not available, using estimated character widths")
        _font_metrics = {}
        return _font_metrics
    
    current_dir = Path(__file__).parent.parent
    assets = current_dir / "assets"
    
    _font_metrics = {}
    
    # Load sans font (used for most text)
    sans_path = assets / "reMarkableSans.woff2"
    if sans_path.exists():
        try:
            sans_font = TTFont(sans_path)
            _font_metrics['sans'] = {
                'cmap': sans_font.getBestCmap(),
                'hmtx': sans_font['hmtx'],
                'upem': sans_font['head'].unitsPerEm,
            }
        except Exception as e:
            _logger.warning(f"Failed to load sans font: {e}")
    
    # Load serif font (used for headings)
    serif_path = assets / "reMarkableSerif.woff2"
    if serif_path.exists():
        try:
            serif_font = TTFont(serif_path)
            _font_metrics['serif'] = {
                'cmap': serif_font.getBestCmap(),
                'hmtx': serif_font['hmtx'],
                'upem': serif_font['head'].unitsPerEm,
            }
        except Exception as e:
            _logger.warning(f"Failed to load serif font: {e}")
    
    return _font_metrics

def get_char_width_screen(char: str, style: si.ParagraphStyle) -> float:
    """Get character width in screen units using font metrics."""
    if not char:
        return 0.0
    
    metrics = _load_font_metrics()
    
    is_heading = style == si.ParagraphStyle.HEADING
    font_key = 'serif' if is_heading else 'sans'
    
    if font_key not in metrics:
        # Fallback to estimated widths
        fallback_widths = {
            si.ParagraphStyle.PLAIN: 11,
            si.ParagraphStyle.BULLET: 11,
            si.ParagraphStyle.BULLET2: 11,
            si.ParagraphStyle.BOLD: 12,
            si.ParagraphStyle.HEADING: 22,
            si.ParagraphStyle.CHECKBOX: 11,
            si.ParagraphStyle.CHECKBOX_CHECKED: 11,
            si.ParagraphStyle.CHECKBOX2: 11,
            si.ParagraphStyle.CHECKBOX2_CHECKED: 11,
            si.ParagraphStyle.NUMBERED: 11,
            si.ParagraphStyle.NUMBERED2: 11,
        }
        return fallback_widths.get(style, 11)
    
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
    font_size_pt = FONT_SIZES_PT.get(style, 7.7)
    font_size_screen = font_size_pt * SCREEN_DPI / 72
    
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

SVG_HEADER = string.Template("""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" height="$height" width="$width" viewBox="$viewbox">""")


def rm_to_svg(rm_path, svg_path):
    """Convert `rm_path` to SVG at `svg_path`."""
    with open(rm_path, "rb") as infile, open(svg_path, "wt") as outfile:
        tree = read_tree(infile)
        tree_to_svg(tree, outfile)


def read_template_svg(template_path: Path) -> str:
    lines = template_path.read_text().splitlines()
    return "\n".join(lines[2:-2])


def get_text_bounding_box(text: tp.Optional[si.Text]) -> tp.Tuple[float, float, float, float]:
    """
    Get the bounding box of the text content.
    
    :return: x_min, x_max, y_min, y_max in screen units
    """
    LINE_SEPARATOR = '\u2028'
    
    if text is None:
        return (0, 0, 0, 0)
    
    doc = TextDocument.from_scene_item(text)
    if not doc.contents:
        return (0, 0, 0, 0)
    
    # Define which styles are "list" styles (must match draw_text)
    LIST_STYLES = {
        si.ParagraphStyle.BULLET,
        si.ParagraphStyle.BULLET2,
        si.ParagraphStyle.CHECKBOX,
        si.ParagraphStyle.CHECKBOX_CHECKED,
        si.ParagraphStyle.CHECKBOX2,
        si.ParagraphStyle.CHECKBOX2_CHECKED,
        si.ParagraphStyle.NUMBERED,
        si.ParagraphStyle.NUMBERED2,
    }
    
    # Calculate y positions the same way draw_text does
    y_offset = TEXT_TOP_Y
    y_positions = []
    prev_style = None
    for p in doc.contents:
        # Add section gap when transitioning from non-list to list style (must match draw_text)
        is_list_style = p.style.value in LIST_STYLES
        was_list_style = prev_style in LIST_STYLES if prev_style else False
        if is_list_style and not was_list_style and prev_style is not None:
            y_offset += BULLET_SECTION_GAP
        
        y_offset += LINE_HEIGHTS.get(p.style.value, 70)
        y_positions.append(text.pos_y + y_offset)
        
        # Account for soft line breaks
        content = str(p)
        num_soft_breaks = content.count(LINE_SEPARATOR)
        soft_line_height = SOFT_LINE_HEIGHTS.get(p.style.value, 50)
        if num_soft_breaks > 0:
            y_offset += num_soft_breaks * soft_line_height
            y_positions.append(text.pos_y + y_offset)
        
        # Account for line wrapping
        available_width = text.width - TEXT_WRAP_MARGIN
        is_checkbox = p.style.value in (si.ParagraphStyle.CHECKBOX, si.ParagraphStyle.CHECKBOX_CHECKED)
        is_checkbox2 = p.style.value in (si.ParagraphStyle.CHECKBOX2, si.ParagraphStyle.CHECKBOX2_CHECKED)
        is_bullet = p.style.value == si.ParagraphStyle.BULLET
        is_bullet2 = p.style.value == si.ParagraphStyle.BULLET2
        is_numbered = p.style.value == si.ParagraphStyle.NUMBERED
        is_numbered2 = p.style.value == si.ParagraphStyle.NUMBERED2
        if is_checkbox:
            available_width -= (CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / SCALE
        elif is_checkbox2:
            available_width -= (CHECKBOX2_INDENT + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / SCALE
        elif is_bullet:
            available_width -= BULLET_INDENT / SCALE
        elif is_bullet2:
            available_width -= BULLET2_INDENT / SCALE
        elif is_numbered:
            available_width -= NUMBERED_INDENT / SCALE
        elif is_numbered2:
            available_width -= NUMBERED2_INDENT / SCALE
        
        segments = content.split(LINE_SEPARATOR)
        total_wrapped_lines = 0
        for segment in segments:
            if segment.strip():
                wrapped = wrap_text_to_width(segment, available_width, p.style.value)
                total_wrapped_lines += len(wrapped)
            else:
                total_wrapped_lines += 1
        
        extra_wrapped_lines = total_wrapped_lines - len(segments)
        if extra_wrapped_lines > 0:
            y_offset += extra_wrapped_lines * soft_line_height
            y_positions.append(text.pos_y + y_offset)
        
        # Account for space after
        space_after = SPACE_AFTER.get(p.style.value, 0)
        if space_after > 0:
            y_offset += space_after
        
        # Account for checkbox item spacing
        if is_checkbox or is_checkbox2:
            y_offset += CHECKBOX_ITEM_SPACING
        
        # Account for bullet/numbered list item spacing
        if is_bullet or is_bullet2 or is_numbered or is_numbered2:
            y_offset += BULLET_ITEM_SPACING
        
        prev_style = p.style.value
    
    # Text starts at pos_x and extends to pos_x + width
    x_min = text.pos_x
    x_max = text.pos_x + text.width
    
    # Y range from first to last text line (with some padding for text height)
    y_min = y_positions[0] - 50  # approximate text ascent
    y_max = y_positions[-1] + 20  # approximate text descent
    
    return (x_min, x_max, y_min, y_max)


def tree_to_svg(tree: SceneTree, output, include_template: Path | None = None):
    """Convert Blocks to SVG."""

    # find the anchor pos for further use
    # newline_offsets contains the offset to subtract for strokes anchored to newlines
    # anchor_x_pos contains computed X positions for characters
    anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset = build_anchor_pos(tree.root_text, extended=True)
    _logger.debug("anchor_pos: %s", anchor_pos)
    _logger.debug("newline_offsets: %s", newline_offsets)

    # Get text_pos_x for TEXT_CHAR anchor calculations
    text_pos_x = tree.root_text.pos_x if tree.root_text is not None else None

    # find the extremum along x and y (for strokes)
    x_min, x_max, y_min, y_max = get_bounding_box(tree.root, anchor_pos, newline_offsets, text_pos_x, anchor_x_pos, anchor_soft_offset)
    
    # Also include text bounds
    # NOTE: For backward compatibility with external code that calls get_bounding_box
    # directly, we don't add text bounds or BBOX_MARGIN here. The SVG viewBox should
    # match what get_bounding_box returns.
    
    width_pt = xx(x_max - x_min + 1)
    height_pt = yy(y_max - y_min + 1)
    _logger.debug("x_min, x_max, y_min, y_max: %.1f, %.1f, %.1f, %.1f ; scalded %.1f, %.1f, %.1f, %.1f",
                  x_min, x_max, y_min, y_max, xx(x_min), xx(x_max), yy(y_min), yy(y_max))

    # add svg header
    output.write(SVG_HEADER.substitute(width=width_pt,
                                       height=height_pt,
                                       viewbox=f"{xx(x_min)} {yy(y_min)} {width_pt} {height_pt}") + "\n")

    if include_template is not None:
        output.write(read_template_svg(include_template))
        output.write(f'\n\t<rect fill="url(#template)" x="{xx(x_min)}" y="{yy(y_min)}"'
                     f' width="{width_pt}" height="{height_pt}"/>\n')

    output.write(f'\t<g id="p1" style="display:inline">\n')

    if tree.root_text is not None:
        draw_text(tree.root_text, output)

    draw_group(tree.root, output, anchor_pos, newline_offsets, text_pos_x, anchor_x_pos, anchor_soft_offset)

    # Closing page group
    output.write('\t</g>\n')
    # END notebook
    output.write('</svg>\n')


def build_anchor_pos(text: tp.Optional[si.Text], extended: bool = False):
    """
    Find the anchor positions for every text node, including special top and
    bottom of text anchors.

    :param text: the root text of the remarkable file
    :param extended: if True, return all computed values; if False (default), return only anchor_pos for backward compatibility
    :return: If extended=False: anchor_pos dict
             If extended=True: (anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset) where:
        - anchor_pos maps CrdtId -> y position (includes soft line offset)
        - newline_offsets maps newline CrdtIds -> offset to subtract (line height + prev SPACE_AFTER)
        - anchor_x_pos maps CrdtId -> x position (for all characters)
        - anchor_soft_offset maps CrdtId -> soft line offset applied to that character
    """
    LINE_SEPARATOR = '\u2028'
    
    # Start with placeholder values for special anchors - will be updated below
    anchor_pos = {
        CrdtId(0, TEXT_DOCUMENT_TOP_Y_CRDT_ID): 100,
        CrdtId(0, TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID): 100,
    }
    
    # Track newline anchors and their line height offset
    newline_offsets: tp.Dict[CrdtId, int] = {}
    
    # Track X positions for each character
    anchor_x_pos: tp.Dict[CrdtId, float] = {}
    
    # Track soft line offset for each character
    anchor_soft_offset: tp.Dict[CrdtId, float] = {}

    if text is not None:
        doc = TextDocument.from_scene_item(text)
        y_offset = TEXT_TOP_Y
        last_content_y_offset = TEXT_TOP_Y
        prev_style = None
        
        # Define which styles are "list" styles (must match draw_text)
        LIST_STYLES = {
            si.ParagraphStyle.BULLET,
            si.ParagraphStyle.BULLET2,
            si.ParagraphStyle.CHECKBOX,
            si.ParagraphStyle.CHECKBOX_CHECKED,
            si.ParagraphStyle.CHECKBOX2,
            si.ParagraphStyle.CHECKBOX2_CHECKED,
            si.ParagraphStyle.NUMBERED,
            si.ParagraphStyle.NUMBERED2,
        }
        
        for i, p in enumerate(doc.contents):
            line_height = LINE_HEIGHTS.get(p.style.value, 70)
            soft_line_height = SOFT_LINE_HEIGHTS.get(p.style.value, 50)
            
            # Add section gap when transitioning from non-list to list style (must match draw_text)
            is_list_style = p.style.value in LIST_STYLES
            was_list_style = prev_style in LIST_STYLES if prev_style else False
            if is_list_style and not was_list_style and prev_style is not None:
                y_offset += BULLET_SECTION_GAP
            
            y_offset += line_height
            ypos = text.pos_y + y_offset
            
            anchor_pos[p.start_id] = ypos
            
            if i > 0:
                # Include SPACE_AFTER from previous paragraph in the offset
                # This accounts for extra spacing after headings, etc.
                prev_space_after = SPACE_AFTER.get(prev_style, 0)
                newline_offsets[p.start_id] = line_height + prev_space_after
            
            # Track character positions
            current_soft_offset = 0
            cumulative_x = 0.0
            
            for subp in p.contents:
                for j, k in enumerate(subp.i):
                    anchor_pos[k] = ypos + current_soft_offset
                    anchor_x_pos[k] = text.pos_x + cumulative_x
                    anchor_soft_offset[k] = current_soft_offset
                    
                    char = subp.s[j] if j < len(subp.s) else ''
                    if char == LINE_SEPARATOR:
                        current_soft_offset += soft_line_height
                        cumulative_x = 0.0  # Reset X for new line
                    else:
                        cumulative_x += get_char_width_screen(char, p.style.value)
            
            content = str(p)
            num_soft_breaks = content.count(LINE_SEPARATOR)
            if num_soft_breaks > 0:
                y_offset += num_soft_breaks * soft_line_height
            
            # Calculate extra lines from word wrapping (must match draw_text)
            # Split content by LINE_SEPARATOR first, then wrap each segment
            available_width = text.width - TEXT_WRAP_MARGIN
            is_checkbox = p.style.value in (si.ParagraphStyle.CHECKBOX, si.ParagraphStyle.CHECKBOX_CHECKED)
            is_checkbox2 = p.style.value in (si.ParagraphStyle.CHECKBOX2, si.ParagraphStyle.CHECKBOX2_CHECKED)
            is_bullet = p.style.value == si.ParagraphStyle.BULLET
            is_bullet2 = p.style.value == si.ParagraphStyle.BULLET2
            is_numbered = p.style.value == si.ParagraphStyle.NUMBERED
            is_numbered2 = p.style.value == si.ParagraphStyle.NUMBERED2
            if is_checkbox:
                available_width -= (CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / SCALE
            elif is_checkbox2:
                available_width -= (CHECKBOX2_INDENT + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / SCALE
            elif is_bullet:
                available_width -= BULLET_INDENT / SCALE
            elif is_bullet2:
                available_width -= BULLET2_INDENT / SCALE
            elif is_numbered:
                available_width -= NUMBERED_INDENT / SCALE
            elif is_numbered2:
                available_width -= NUMBERED2_INDENT / SCALE
            
            segments = content.split(LINE_SEPARATOR)
            total_wrapped_lines = 0
            for segment in segments:
                if segment.strip():
                    wrapped = wrap_text_to_width(segment, available_width, p.style.value)
                    total_wrapped_lines += len(wrapped)
                else:
                    total_wrapped_lines += 1  # Empty segment counts as one line
            
            # Extra wrapped lines beyond the soft breaks (first line of each segment is already counted)
            num_segments = len(segments)
            extra_wrapped_lines = total_wrapped_lines - num_segments
            if extra_wrapped_lines > 0:
                y_offset += extra_wrapped_lines * soft_line_height
            
            # Add extra space after certain paragraph styles (e.g., headings)
            space_after = SPACE_AFTER.get(p.style.value, 0)
            if space_after > 0:
                y_offset += space_after
            
            # Add spacing after checkbox items (must match draw_text)
            if is_checkbox or is_checkbox2:
                y_offset += CHECKBOX_ITEM_SPACING
            
            # Add spacing after bullet/numbered list items (must match draw_text)
            if is_bullet or is_bullet2 or is_numbered or is_numbered2:
                y_offset += BULLET_ITEM_SPACING
            
            visible_content = content.replace(LINE_SEPARATOR, '').strip()
            if visible_content:
                last_content_y_offset = y_offset
            
            prev_style = p.style.value
 
        if doc.contents:
            first_y_offset = TEXT_TOP_Y + LINE_HEIGHTS.get(doc.contents[0].style.value, 70)
            anchor_pos[CrdtId(0, TEXT_DOCUMENT_TOP_Y_CRDT_ID)] = text.pos_y + first_y_offset
            anchor_pos[CrdtId(0, TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID)] = text.pos_y + last_content_y_offset

    if extended:
        return anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset
    else:
        # For backward compatibility: return anchor_pos with newline_offsets pre-applied
        # This ensures get_bounding_box returns correct bounds even without extended params
        adjusted_anchor_pos = dict(anchor_pos)
        for crdt_id, offset in newline_offsets.items():
            if crdt_id in adjusted_anchor_pos:
                adjusted_anchor_pos[crdt_id] -= offset
        return adjusted_anchor_pos


def get_anchor(item: si.Group, anchor_pos, newline_offsets=None, text_pos_x=None, anchor_x_pos=None, anchor_soft_offset=None):
    """
    Get the anchor position for a group.
    
    :param item: The group to get anchor for
    :param anchor_pos: Map of CrdtId -> y position
    :param newline_offsets: Map of newline CrdtIds -> offset to subtract
    :param text_pos_x: X position of text block (fallback for TEXT_CHAR anchors)
    :param anchor_x_pos: Map of CrdtId -> x position for characters
    :param anchor_soft_offset: Map of CrdtId -> soft line offset for TEXT_CHAR adjustment
    """
    if newline_offsets is None:
        newline_offsets = {}
    if anchor_x_pos is None:
        anchor_x_pos = {}
    if anchor_soft_offset is None:
        anchor_soft_offset = {}
        
    anchor_x = 0.0
    anchor_y = 0.0
    if item.anchor_id is not None:
        assert item.anchor_origin_x is not None
        anchor_x = item.anchor_origin_x.value
        
        # For TEXT_CHAR anchors (anchor_type=1) with anchor_origin_x=0,
        # use the computed character X position
        if item.anchor_type is not None and item.anchor_type.value == 1 and anchor_x == 0:
            if item.anchor_id.value in anchor_x_pos:
                anchor_x = anchor_x_pos[item.anchor_id.value]
                _logger.debug("TEXT_CHAR anchor: using char x=%.1f for %s",
                              anchor_x, item.anchor_id.value)
            elif text_pos_x is not None:
                anchor_x = text_pos_x
                _logger.debug("TEXT_CHAR anchor: fallback to text_pos_x=%.1f", text_pos_x)
        
        if item.anchor_id.value in anchor_pos:
            anchor_y = anchor_pos[item.anchor_id.value]
            
            # NOTE: anchor_threshold exists but we don't apply it uniformly.
            # The threshold value (typically ~35.7) seems to be a baseline offset,
            # but applying it causes misalignment in various cases.
            # For now, we don't apply threshold - elements align with their anchor Y directly.
            # TODO: Determine correct rule for when threshold should be applied.
            
            # For TEXT_CHAR anchors, subtract excess soft offset beyond first line
            # This is because stroke coordinates are relative to the first content line,
            # not the specific soft line the anchor character is on
            if item.anchor_type is not None and item.anchor_type.value == 1:
                soft_off = anchor_soft_offset.get(item.anchor_id.value, 0)
                # Only subtract offset beyond first line (assume first line is at soft_off = 60)
                # This brings anchors from line 2+ back to line 1
                first_line_offset = 60  # SOFT_LINE_HEIGHTS default for first content line
                if soft_off > first_line_offset:
                    excess = soft_off - first_line_offset
                    anchor_y -= excess
                    _logger.debug("TEXT_CHAR anchor: subtracting excess soft_offset=%.1f for %s",
                                  excess, item.anchor_id.value)
            
            if item.anchor_id.value in newline_offsets:
                anchor_y -= newline_offsets[item.anchor_id.value]
                _logger.debug("Group anchor: %s -> y=%.1f (newline, shifted up by %.1f)",
                              item.anchor_id.value, anchor_y, newline_offsets[item.anchor_id.value])
            else:
                _logger.debug("Group anchor: %s -> y=%.1f", item.anchor_id.value, anchor_y)
        else:
            _logger.warning("Group anchor: %s is unknown!", item.anchor_id.value)

    return anchor_x, anchor_y


def get_bounding_box(item: si.Group,
                     anchor_pos: tp.Dict[CrdtId, int],
                     newline_offsets: tp.Dict[CrdtId, int] = None,
                     text_pos_x: float = None,
                     anchor_x_pos: tp.Dict[CrdtId, float] = None,
                     anchor_soft_offset: tp.Dict[CrdtId, float] = None,
                     default: tp.Tuple[int, int, int, int] = None) \
        -> tp.Tuple[int, int, int, int]:
    """Get the bounding box of the given item."""
    if newline_offsets is None:
        newline_offsets = {}
    if anchor_x_pos is None:
        anchor_x_pos = {}
    if anchor_soft_offset is None:
        anchor_soft_offset = {}
    # Compute default based on current device settings (can't use in parameter default
    # because those are evaluated at function definition time, not call time)
    if default is None:
        default = (- SCREEN_WIDTH // 2, SCREEN_WIDTH // 2, 0, SCREEN_HEIGHT)
        
    x_min, x_max, y_min, y_max = default

    for child_id in item.children:
        child = item.children[child_id]
        if isinstance(child, si.Group):
            anchor_x, anchor_y = get_anchor(child, anchor_pos, newline_offsets, text_pos_x, anchor_x_pos, anchor_soft_offset)
            x_min_t, x_max_t, y_min_t, y_max_t = get_bounding_box(child, anchor_pos, newline_offsets, text_pos_x, anchor_x_pos, anchor_soft_offset, (0, 0, 0, 0))
            x_min = min(x_min, x_min_t + anchor_x)
            x_max = max(x_max, x_max_t + anchor_x)
            y_min = min(y_min, y_min_t + anchor_y)
            y_max = max(y_max, y_max_t + anchor_y)
        elif isinstance(child, si.Line):
            x_min = min([x_min] + [p.x for p in child.points])
            x_max = max([x_max] + [p.x for p in child.points])
            y_min = min([y_min] + [p.y for p in child.points])
            y_max = max([y_max] + [p.y for p in child.points])

    return x_min, x_max, y_min, y_max


def draw_group(item: si.Group, output, anchor_pos, newline_offsets=None, text_pos_x=None, anchor_x_pos=None, anchor_soft_offset=None):
    if newline_offsets is None:
        newline_offsets = {}
    if anchor_x_pos is None:
        anchor_x_pos = {}
    if anchor_soft_offset is None:
        anchor_soft_offset = {}
    anchor_x, anchor_y = get_anchor(item, anchor_pos, newline_offsets, text_pos_x, anchor_x_pos, anchor_soft_offset)
    output.write(f'\t\t<g id="{item.node_id}" transform="translate({xx(anchor_x)}, {yy(anchor_y)})">\n')
    for child_id in item.children:
        child = item.children[child_id]
        _logger.debug("Group child: %s %s", child_id, type(child))
        if _logger.root.level == logging.DEBUG:
            output.write(f'\t\t<!-- child {child_id} {type(child)} -->\n')
        if isinstance(child, si.Group):
            draw_group(child, output, anchor_pos, newline_offsets, text_pos_x, anchor_x_pos, anchor_soft_offset)
        elif isinstance(child, si.Line):
            draw_stroke(child, output)
    output.write(f'\t\t</g>\n')


def draw_stroke(item: si.Line, output):
    if _logger.root.level == logging.DEBUG:
        _logger.debug("Writing line: %s", item)
        output.write(f'\t\t\t<!-- Stroke tool: {item.tool.name} '
                     f'color: {item.color.name} thickness_scale: {item.thickness_scale} -->\n')

    pen = Pen.create(item.tool.value, item.color.value, item.thickness_scale)

    last_xpos = -1.
    last_ypos = -1.
    last_segment_width = segment_width = 0
    for point_idx, point in enumerate(item.points):
        xpos = point.x
        ypos = point.y
        if point_idx % pen.segment_length == 0:
            if point_idx > 0:
                output.write('"/>\n')

            segment_color = pen.get_segment_color(point.speed, point.direction, point.width, point.pressure,
                                                  last_segment_width)
            segment_width = pen.get_segment_width(point.speed, point.direction, point.width, point.pressure,
                                                  last_segment_width)
            segment_opacity = pen.get_segment_opacity(point.speed, point.direction, point.width, point.pressure,
                                                      last_segment_width)
            output.write('\t\t\t<polyline ')
            output.write(f'style="fill:none; stroke:{segment_color}; '
                         f'stroke-width:{scale(segment_width):.3f}; opacity:{segment_opacity}" ')
            output.write(f'stroke-linecap="{pen.stroke_linecap}" ')
            output.write('points="')
            if point_idx > 0:
                output.write(f'{xx(last_xpos):.3f},{yy(last_ypos):.3f} ')
        last_xpos = xpos
        last_ypos = ypos
        last_segment_width = segment_width
        output.write(f'{xx(xpos):.3f},{yy(ypos):.3f} ')

    output.write('" />\n')


def draw_text(text: si.Text, output):
    output.write('\t\t<g class="root-text" style="display:inline">')

    remarkable_serif_woff2 = ASSETS / 'reMarkableSerif.woff2'
    remarkable_serif = "reMarkable Serif VF"
    remarkable_serif_data = remarkable_serif_woff2.read_bytes()
    remarkable_serif_b64 = base64.b64encode(remarkable_serif_data).decode("ascii")

    remarkable_sans_woff2 = ASSETS / 'reMarkableSans.woff2'
    remarkable_sans = "reMarkable Sans VF"
    remarkable_sans_data = remarkable_sans_woff2.read_bytes()
    remarkable_sans_b64 = base64.b64encode(remarkable_sans_data).decode("ascii")

    output.write(f'''
            <style><![CDATA[
                @font-face {{
                  font-family: "{remarkable_serif}";
                  src: url("data:font/woff2;base64,{remarkable_serif_b64}") format("woff2");
                  font-style: normal;
                  font-weight: 300 800;
                }}
                @font-face {{
                  font-family: "{remarkable_sans}";
                  src: url("data:font/woff2;base64,{remarkable_sans_b64}") format("woff2");
                  font-style: normal;
                  font-weight: 300 700;
                }}
                text.heading {{
                    font-family: "{remarkable_serif}", serif;
                    font-size: 15pt;
                    font-weight: 400; 
                }}
                text.bold {{
                    font-family: "{remarkable_sans}", sans-serif;
                    font-size: 8.3pt;
                    font-weight: 500; 
                }}
                text, text.plain, text.basic {{
                    font-family: "{remarkable_sans}", sans-serif;
                    font-size: 7.7pt;
                    font-weight: 400;
                }}
                text.bullet, text.bullet2 {{
                    font-family: "{remarkable_sans}", sans-serif;
                    font-size: 7.7pt;
                    font-weight: 400;
                }}
                text.checkbox, text.checkbox_checked, text.checkbox2, text.checkbox2_checked {{
                    font-family: "{remarkable_sans}", sans-serif;
                    font-size: 7.7pt;
                    font-weight: 400;
                }}
                text.checkbox_checked, text.checkbox2_checked {{
                    text-decoration: line-through;
                }}
                text.numbered, text.numbered2 {{
                    font-family: "{remarkable_sans}", sans-serif;
                    font-size: 7.7pt;
                    font-weight: 400;
                }}
                tspan.inline-bold {{
                    font-weight: 700;
                }}
                tspan.inline-italic {{
                    font-style: italic;
                }}
            ]]></style>
            <defs>
                <symbol id="checkbox-unchecked" viewBox="0 0 40 40">
                    <path fill-rule="evenodd" clip-rule="evenodd" d="M32,4l4,4v28H8l-4-4V4H32z M6,6h24v24H6V6z"/>
                </symbol>
                <symbol id="checkbox-checked" viewBox="0 0 40 40">
                    <path fill-rule="evenodd" clip-rule="evenodd" d="M36,8H8v28h28V8z M12,24l7,6l13-14l-2-2L19,26l-5-4L12,24z"/>
                </symbol>
                <symbol id="bullet" viewBox="0 0 10 10">
                    <circle cx="5" cy="5" r="4" fill="currentColor"/>
                </symbol>
                <symbol id="bullet2" viewBox="0 0 10 10">
                    <line x1="1" y1="5" x2="9" y2="5" stroke="currentColor" stroke-width="2"/>
                </symbol>
            </defs>
    ''')

    LINE_SEPARATOR = '\u2028'
    y_offset = TEXT_TOP_Y
    
    # Track previous style for section gaps and numbered list counters
    prev_style = None
    numbered_counter = 0
    numbered2_counter = 0
    
    # Define which styles are "list" styles (bullet, numbered)
    LIST_STYLES = {
        si.ParagraphStyle.BULLET,
        si.ParagraphStyle.BULLET2,
        si.ParagraphStyle.CHECKBOX,
        si.ParagraphStyle.CHECKBOX_CHECKED,
        si.ParagraphStyle.CHECKBOX2,
        si.ParagraphStyle.CHECKBOX2_CHECKED,
        si.ParagraphStyle.NUMBERED,
        si.ParagraphStyle.NUMBERED2,
    }

    doc = TextDocument.from_scene_item(text)
    for p_idx, p in enumerate(doc.contents):
        line_height = LINE_HEIGHTS.get(p.style.value, 70)
        soft_line_height = SOFT_LINE_HEIGHTS.get(p.style.value, 50)
        
        # Add section gap when transitioning from non-list to list style
        is_list_style = p.style.value in LIST_STYLES
        was_list_style = prev_style in LIST_STYLES if prev_style else False
        if is_list_style and not was_list_style and prev_style is not None:
            y_offset += BULLET_SECTION_GAP
        
        # Manage numbered list counters
        if p.style.value == si.ParagraphStyle.NUMBERED:
            # Reset counter if previous wasn't NUMBERED
            if prev_style != si.ParagraphStyle.NUMBERED:
                numbered_counter = 0
            numbered_counter += 1
        elif p.style.value == si.ParagraphStyle.NUMBERED2:
            # Reset counter if previous wasn't NUMBERED2
            if prev_style != si.ParagraphStyle.NUMBERED2:
                numbered2_counter = 0
            numbered2_counter += 1
        
        y_offset += line_height

        xpos = text.pos_x
        ypos = text.pos_y + y_offset
        style_name = p.style.value.name.lower()
        
        # Draw checkbox symbol for checkbox styles
        is_checkbox = p.style.value in (si.ParagraphStyle.CHECKBOX, si.ParagraphStyle.CHECKBOX_CHECKED)
        is_checkbox2 = p.style.value in (si.ParagraphStyle.CHECKBOX2, si.ParagraphStyle.CHECKBOX2_CHECKED)
        is_checked = p.style.value in (si.ParagraphStyle.CHECKBOX_CHECKED, si.ParagraphStyle.CHECKBOX2_CHECKED)
        
        # Check for bullet styles
        is_bullet = p.style.value == si.ParagraphStyle.BULLET
        is_bullet2 = p.style.value == si.ParagraphStyle.BULLET2
        
        # Check for numbered list styles
        is_numbered = p.style.value == si.ParagraphStyle.NUMBERED
        is_numbered2 = p.style.value == si.ParagraphStyle.NUMBERED2
        
        # Adjust text position for checkbox items
        text_xpos = xpos
        if is_checkbox or is_checkbox2:
            checkbox_id = "checkbox-checked" if is_checked else "checkbox-unchecked"
            # Position checkbox - indent for CHECKBOX2
            checkbox_offset = CHECKBOX2_INDENT if is_checkbox2 else 0
            checkbox_x = xx(xpos) + checkbox_offset
            checkbox_y = yy(ypos) - CHECKBOX_SIZE + 2  # Align with text baseline
            output.write(f'\t\t\t<use href="#{checkbox_id}" x="{checkbox_x}" y="{checkbox_y}" '
                        f'width="{CHECKBOX_SIZE}" height="{CHECKBOX_SIZE}"/>\n')
            # Push text to the right of checkbox
            text_xpos = xpos + (checkbox_offset + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / SCALE
        elif is_bullet or is_bullet2:
            # Determine indentation and bullet style
            indent = BULLET_INDENT if is_bullet else BULLET2_INDENT
            bullet_id = "bullet" if is_bullet else "bullet2"
            
            # Position bullet before text
            bullet_x = xx(xpos) + indent - BULLET_SIZE - BULLET_GAP
            bullet_y = yy(ypos) - BULLET_SIZE / 2 - 1  # Center vertically with text
            output.write(f'\t\t\t<use href="#{bullet_id}" x="{bullet_x}" y="{bullet_y}" '
                        f'width="{BULLET_SIZE}" height="{BULLET_SIZE}"/>\n')
            # Indent text
            text_xpos = xpos + indent / SCALE
        elif is_numbered or is_numbered2:
            # Determine indentation and counter
            indent = NUMBERED_INDENT if is_numbered else NUMBERED2_INDENT
            counter = numbered_counter if is_numbered else numbered2_counter
            number_text = f"{counter}."
            
            # Render the number as text
            # For NUMBERED2, offset the number position to show nesting
            number_offset = 0 if is_numbered else NUMBERED2_OFFSET
            number_x = xx(xpos) + number_offset
            number_y = yy(ypos)
            output.write(f'\t\t\t<text x="{number_x}" y="{number_y}" class="{style_name}" xml:space="preserve">{number_text}</text>\n')
            # Indent text after number
            text_xpos = xpos + indent / SCALE
        
        # Render text with inline formatting support
        # First, collect all text segments with their formatting
        all_segments = []
        for subp in p.contents:
            props = getattr(subp, 'properties', {})
            is_bold = props.get('font-weight') == 'bold'
            is_italic = props.get('font-style') == 'italic'
            
            text_content = str(subp)
            
            # Split by LINE_SEPARATOR but keep track of segments
            parts = text_content.split(LINE_SEPARATOR)
            for i, part in enumerate(parts):
                if part:
                    all_segments.append({
                        'text': part,
                        'bold': is_bold,
                        'italic': is_italic,
                        'newline_after': False
                    })
                if i < len(parts) - 1:
                    # Mark that a newline follows
                    if all_segments:
                        all_segments[-1]['newline_after'] = True
                    else:
                        # Empty line at start
                        all_segments.append({
                            'text': '',
                            'bold': False,
                            'italic': False,
                            'newline_after': True
                        })
        
        # Now group segments into lines
        lines = []
        current_line = []
        for seg in all_segments:
            if seg['text']:
                current_line.append(seg)
            if seg['newline_after']:
                lines.append(current_line)
                current_line = []
        if current_line:
            lines.append(current_line)
        
        line_offset = 0
        wrapped_line_count = 0  # Track total wrapped lines for y_offset
        
        for line_parts in lines:
            # Skip empty lines
            full_text = ''.join(part['text'] for part in line_parts)
            if not full_text.strip():
                line_offset += 1
                wrapped_line_count += 1
                continue
            
            # Check if we need tspans (for inline formatting)
            needs_tspans = any(part['bold'] or part['italic'] for part in line_parts)
            
            # Apply word wrapping based on available width
            available_width = text.width - TEXT_WRAP_MARGIN
            if is_checkbox:
                # Reduce available width by checkbox space
                available_width -= (CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / SCALE
            elif is_checkbox2:
                # Reduce available width by indented checkbox space
                available_width -= (CHECKBOX2_INDENT + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / SCALE
            elif is_bullet:
                # Reduce available width by bullet indent
                available_width -= BULLET_INDENT / SCALE
            elif is_bullet2:
                # Reduce available width by nested bullet indent
                available_width -= BULLET2_INDENT / SCALE
            elif is_numbered:
                # Reduce available width by numbered list indent
                available_width -= NUMBERED_INDENT / SCALE
            elif is_numbered2:
                # Reduce available width by nested numbered list indent
                available_width -= NUMBERED2_INDENT / SCALE
            
            if needs_tspans:
                # For inline formatting, we need to wrap while preserving spans
                # Simple approach: wrap the full text, then re-apply formatting
                wrapped_lines = wrap_text_to_width(full_text, available_width, p.style.value)
                
                for wrapped_idx, wrapped_text in enumerate(wrapped_lines):
                    line_ypos = ypos + (line_offset * soft_line_height)
                    
                    if _logger.root.level == logging.DEBUG:
                        output.write(f'\t\t\t<!-- Text line char_id: {p.start_id} offset {line_offset} wrapped {wrapped_idx} -->\n')
                    
                    # Re-apply formatting to wrapped text
                    # Find which parts of the original segments map to this wrapped line
                    output.write(f'\t\t\t<text x="{xx(text_xpos)}" y="{yy(line_ypos)}" class="{style_name}" xml:space="preserve">')
                    
                    # Track position in wrapped text to apply formatting
                    remaining = wrapped_text
                    pos_in_original = sum(len(wrap_text_to_width(full_text, available_width, p.style.value)[i]) + 1 
                                         for i in range(wrapped_idx)) if wrapped_idx > 0 else 0
                    
                    # Simple approach: render wrapped text with original formatting spans
                    char_pos = 0
                    for part in line_parts:
                        part_text = part['text']
                        part_start = full_text.find(part_text, char_pos)
                        part_end = part_start + len(part_text)
                        
                        # Find overlap with wrapped line
                        wrap_start = pos_in_original
                        wrap_end = pos_in_original + len(wrapped_text)
                        
                        overlap_start = max(part_start, wrap_start)
                        overlap_end = min(part_end, wrap_end)
                        
                        if overlap_start < overlap_end:
                            overlap_text = full_text[overlap_start:overlap_end]
                            escaped_text = _escape_attrib(overlap_text)
                            if part['bold'] and part['italic']:
                                output.write(f'<tspan class="inline-bold inline-italic">{escaped_text}</tspan>')
                            elif part['bold']:
                                output.write(f'<tspan class="inline-bold">{escaped_text}</tspan>')
                            elif part['italic']:
                                output.write(f'<tspan class="inline-italic">{escaped_text}</tspan>')
                            else:
                                output.write(escaped_text)
                        
                        char_pos = part_end
                    
                    output.write('</text>\n')
                    line_offset += 1
                
                wrapped_line_count += len(wrapped_lines)
            else:
                # Simple text - apply word wrapping
                wrapped_lines = wrap_text_to_width(full_text, available_width, p.style.value)
                
                for wrapped_idx, wrapped_text in enumerate(wrapped_lines):
                    if _logger.root.level == logging.DEBUG:
                        output.write(f'\t\t\t<!-- Text line char_id: {p.start_id} offset {line_offset} wrapped {wrapped_idx} -->\n')
                    
                    line_ypos = ypos + (line_offset * soft_line_height)
                    output.write(f'\t\t\t<text x="{xx(text_xpos)}" y="{yy(line_ypos)}" class="{style_name}" xml:space="preserve">{_escape_attrib(wrapped_text)}</text>\n')
                    line_offset += 1
                
                wrapped_line_count += len(wrapped_lines)
        
        # Use wrapped line count minus 1 for y_offset (first line is already accounted for)
        # But we also need to account for LINE_SEPARATOR breaks in the original content
        content = str(p)
        num_soft_breaks = content.count(LINE_SEPARATOR)
        # Additional wrapped lines beyond soft breaks
        extra_wrapped_lines = wrapped_line_count - len(lines)
        if num_soft_breaks > 0 or extra_wrapped_lines > 0:
            total_extra = num_soft_breaks + extra_wrapped_lines
            y_offset += total_extra * soft_line_height
        
        # Add extra space after certain paragraph styles (e.g., headings)
        space_after = SPACE_AFTER.get(p.style.value, 0)
        if space_after > 0:
            y_offset += space_after
        
        # Add spacing after checkbox items
        if is_checkbox or is_checkbox2:
            y_offset += CHECKBOX_ITEM_SPACING
        
        # Add spacing after bullet/numbered list items
        if is_bullet or is_bullet2 or is_numbered or is_numbered2:
            y_offset += BULLET_ITEM_SPACING
        
        # Update previous style for next iteration
        prev_style = p.style.value
    
    output.write('\t\t</g>\n')
