"""SVG rendering pipeline, CSS generation, and text rendering."""

import base64
import logging
import string
import typing as tp
from pathlib import Path
from xml.sax.saxutils import escape as _escape_attrib

from rmscene import read_tree, SceneTree
from rmscene import scene_items as si
from rmscene.text import TextDocument
from rmscene.crdt_sequence import CrdtId

# Import from device module
from .device import rmc_config

# Import from fonts module
from .fonts import (
    FONTS,
    FONTS_DIR,
    FONT_CONFIG,
    FONT_WEIGHT_INLINE_BOLD,
    FONT_FAMILY_SANS,
    FONT_FAMILY_SERIF,
    get_font_family_sans,
    get_font_family_serif,
    _resolve_font_config,
    wrap_text_to_width,
    get_text_width_screen,
    get_char_width_screen,
)

# Import from layout module
from .layout import (
    CHECKBOX_SIZE,
    BULLET_SIZE,
    BULLET_INDENT,
    BULLET2_INDENT,
    NUMBERED_INDENT,
    NUMBERED2_INDENT,
    TEXT_WRAP_MARGIN,
    BULLET_SECTION_GAP,
    CHECKBOX_ITEM_SPACING,
    BULLET_ITEM_SPACING,
    CHECKBOX_TEXT_GAP,
    CHECKBOX2_INDENT,
    BULLET_GAP,
    NUMBERED2_OFFSET,
    LINE_HEIGHTS,
    SOFT_LINE_HEIGHTS,
    SPACE_AFTER,
    TEXT_TOP_Y,
    TEXT_DOCUMENT_TOP_Y_CRDT_ID,
    TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID,
    calculate_paragraph_layouts,
)

# Import writing tools
from ..writing_tools import Pen

_logger = logging.getLogger(__name__)


# =============================================================================
# RENDERING CODE
# =============================================================================

SVG_HEADER = string.Template("""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" height="$height" width="$width" viewBox="$viewbox">""")


def rm_to_svg(rm_path, svg_path):
    """Convert `rm_path` to SVG at `svg_path`.

    :param rm_path: Path to .rm file
    :param svg_path: Path to output SVG file
    """
    with open(rm_path, "rb") as infile, open(svg_path, "wt") as outfile:
        tree = read_tree(infile)
        tree_to_svg(tree, outfile)


def read_template_svg(template_path: Path) -> str:
    lines = template_path.read_text().splitlines()
    return "\n".join(lines[2:-2])


def get_text_bounding_box(text: tp.Optional[si.Text]) -> tp.Tuple[float, float, float, float]:
    """
    Get the bounding box of the text content.

    Uses calculate_paragraph_layouts() to ensure layout calculation matches
    build_anchor_pos() and draw_text() exactly.

    :return: x_min, x_max, y_min, y_max in screen units
    """
    if text is None:
        return (0, 0, 0, 0)

    # Collect Y positions as paragraphs are laid out
    y_positions = []

    for layout in calculate_paragraph_layouts(text):
        # Record Y position after this paragraph's line height is added
        # (before soft breaks and wrapping)
        y_base = text.pos_y + layout['y_offset_before'] + layout['line_height']
        y_positions.append(y_base)

        # If there were soft breaks or extra wrapped lines, record final position too
        if layout['num_soft_breaks'] > 0 or layout['extra_wrapped_lines'] > 0:
            y_positions.append(text.pos_y + layout['y_offset_after'])

    if not y_positions:
        return (0, 0, 0, 0)

    # Text spans from pos_x to pos_x + width
    x_min = text.pos_x
    x_max = text.pos_x + text.width

    # Y range from first to last text line (with padding for text height)
    y_min = y_positions[0] - 50  # approximate text ascent
    y_max = y_positions[-1] + 20  # approximate text descent

    return (x_min, x_max, y_min, y_max)


def tree_to_svg(tree: SceneTree, output, include_template: Path | None = None):
    """Convert Blocks to SVG.

    :param tree: The scene tree to convert
    :param output: Output file object to write SVG to
    :param include_template: Optional template SVG to include as background
    """

    # find the anchor pos for further use
    # newline_offsets contains the offset to subtract for strokes anchored to newlines
    # anchor_x_pos contains computed X positions for characters
    anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset = build_anchor_pos(tree.root_text, extended=True)
    _logger.debug("anchor_pos: %s", anchor_pos)
    _logger.debug("newline_offsets: %s", newline_offsets)

    # Get text_pos_x for TEXT_CHAR anchor calculations
    text_pos_x = tree.root_text.pos_x if tree.root_text is not None else None

    # find the extremum along x and y (for strokes)
    # get_bounding_box defaults to device dimensions, expanding if content extends beyond
    x_min, x_max, y_min, y_max = get_bounding_box(
        tree.root, anchor_pos, newline_offsets, text_pos_x, anchor_x_pos, anchor_soft_offset
    )
    
    width_pt = rmc_config.xx(x_max - x_min + 1)
    height_pt = rmc_config.yy(y_max - y_min + 1)
    _logger.debug("x_min, x_max, y_min, y_max: %.1f, %.1f, %.1f, %.1f ; scaled %.1f, %.1f, %.1f, %.1f",
                  x_min, x_max, y_min, y_max, rmc_config.xx(x_min), rmc_config.xx(x_max), rmc_config.yy(y_min), rmc_config.yy(y_max))

    # add svg header
    output.write(SVG_HEADER.substitute(width=width_pt,
                                       height=height_pt,
                                       viewbox=f"{rmc_config.xx(x_min)} {rmc_config.yy(y_min)} {width_pt} {height_pt}") + "\n")

    if include_template is not None:
        output.write(read_template_svg(include_template))
        output.write(f'\n\t<rect fill="url(#template)" x="{rmc_config.xx(x_min)}" y="{rmc_config.yy(y_min)}"'
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

    Uses calculate_paragraph_layouts() to ensure layout calculation matches
    get_text_bounding_box() and draw_text() exactly.

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

    # Initialize tracking structures
    anchor_pos = {
        CrdtId(0, TEXT_DOCUMENT_TOP_Y_CRDT_ID): 100,
        CrdtId(0, TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID): 100,
    }
    newline_offsets: tp.Dict[CrdtId, int] = {}
    anchor_x_pos: tp.Dict[CrdtId, float] = {}
    anchor_soft_offset: tp.Dict[CrdtId, float] = {}

    if text is None:
        if extended:
            return anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset
        else:
            return anchor_pos

    # Track special anchor positions
    last_content_y_offset = TEXT_TOP_Y
    first_line_height = None

    for layout in calculate_paragraph_layouts(text):
        p = layout['paragraph']
        i = layout['paragraph_index']

        # Capture first line height for top anchor
        if first_line_height is None:
            first_line_height = layout['line_height']

        # Y position for this paragraph (after line_height is added)
        ypos = text.pos_y + layout['y_offset_before'] + layout['line_height']
        anchor_pos[p.start_id] = ypos

        # Track newline offsets for paragraph boundaries
        if i > 0:
            prev_space_after = SPACE_AFTER.get(layout['prev_style'], 0)
            newline_offsets[p.start_id] = layout['line_height'] + prev_space_after

        # Track character-level positions (unique to build_anchor_pos)
        # This is the only part that can't be shared, as it needs per-character iteration
        current_soft_offset = 0
        cumulative_x = 0.0

        for subp in p.contents:
            for j, k in enumerate(subp.i):
                anchor_pos[k] = ypos + current_soft_offset
                anchor_x_pos[k] = text.pos_x + cumulative_x
                anchor_soft_offset[k] = current_soft_offset

                char = subp.s[j] if j < len(subp.s) else ''
                if char == LINE_SEPARATOR:
                    current_soft_offset += layout['soft_line_height']
                    cumulative_x = 0.0  # Reset X for new line
                else:
                    cumulative_x += get_char_width_screen(char, p.style.value)

        # Track last content position for bottom anchor
        visible_content = layout['content'].replace(LINE_SEPARATOR, '').strip()
        if visible_content:
            last_content_y_offset = layout['y_offset_after']

    # Update special anchors
    doc = TextDocument.from_scene_item(text)
    if doc.contents and first_line_height is not None:
        first_y_offset = TEXT_TOP_Y + first_line_height
        anchor_pos[CrdtId(0, TEXT_DOCUMENT_TOP_Y_CRDT_ID)] = text.pos_y + first_y_offset
        anchor_pos[CrdtId(0, TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID)] = text.pos_y + last_content_y_offset

    if extended:
        return anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset
    else:
        # Backward compatibility: return anchor_pos with newline_offsets pre-applied
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
    """Get the bounding box of the given item.

    Default bounds are device dimensions, expanding to include any content beyond.
    """
    if newline_offsets is None:
        newline_offsets = {}
    if anchor_x_pos is None:
        anchor_x_pos = {}
    if anchor_soft_offset is None:
        anchor_soft_offset = {}
    # Compute default based on current device settings (can't use in parameter default
    # because those are evaluated at function definition time, not call time)
    if default is None:
        default = (- rmc_config.screen_width // 2, rmc_config.screen_width // 2, 0, rmc_config.screen_height)
        
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
    output.write(f'\t\t<g id="{item.node_id}" transform="translate({rmc_config.xx(anchor_x)}, {rmc_config.yy(anchor_y)})">\n')
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
                         f'stroke-width:{rmc_config.xx(segment_width):.3f}; opacity:{segment_opacity}" ')
            output.write(f'stroke-linecap="{pen.stroke_linecap}" ')
            output.write('points="')
            if point_idx > 0:
                output.write(f'{rmc_config.xx(last_xpos):.3f},{rmc_config.yy(last_ypos):.3f} ')
        last_xpos = xpos
        last_ypos = ypos
        last_segment_width = segment_width
        output.write(f'{rmc_config.xx(xpos):.3f},{rmc_config.yy(ypos):.3f} ')

    output.write('" />\n')


# Cache for base64-encoded fonts (loaded once per session)
# Maps font_key -> {"data": base64_string, "config": resolved_config}
_font_data_cache: tp.Optional[tp.Dict[str, tp.Dict[str, tp.Any]]] = None


def _load_font_data() -> tp.Dict[str, tp.Dict[str, tp.Any]]:
    """Load and base64-encode all fonts defined in FONTS configuration.

    Returns a dict mapping font keys to their base64-encoded data and resolved config.
    Uses fallback fonts if primary fonts are not available.
    """
    global _font_data_cache
    if _font_data_cache is not None:
        return _font_data_cache

    _font_data_cache = {}
    for font_key in FONTS.keys():
        resolved = _resolve_font_config(font_key)
        if resolved is None:
            continue
        font_path = FONTS_DIR / resolved["file"]
        try:
            font_data = font_path.read_bytes()
            _font_data_cache[font_key] = {
                "data": base64.b64encode(font_data).decode("ascii"),
                "config": resolved,
            }
        except Exception as e:
            _logger.warning(f"Failed to load font data for {font_key}: {e}")

    return _font_data_cache


def _generate_font_face_css() -> str:
    """Generate @font-face CSS declarations for all fonts in FONTS configuration.

    Uses resolved font configs (including fallbacks) and appropriate MIME types.
    """
    font_data = _load_font_data()
    css_rules = []

    for font_key, entry in font_data.items():
        config = entry["config"]
        data = entry["data"]

        # Determine MIME type based on format
        mime_type = "font/woff2" if config["format"] == "woff2" else "font/ttf"

        css_rules.append(f'''@font-face {{
                  font-family: "{config["family"]}";
                  src: url("data:{mime_type};base64,{data}") format("{config["format"]}");
                  font-style: {config["style"]};
                  font-weight: {config["weight_range"]};
                }}''')

    return "\n                ".join(css_rules)


def _generate_font_css() -> str:
    """Generate CSS for all font styles from FONT_CONFIG."""
    css_rules = []

    # Use resolved font families (which account for fallbacks)
    serif_family = get_font_family_serif()
    sans_family = get_font_family_sans()

    for style_name, config in FONT_CONFIG.items():
        family = serif_family if config["family"] == "serif" else sans_family
        fallback = "serif" if config["family"] == "serif" else "sans-serif"

        css_rules.append(f'''text.{style_name} {{
                    font-family: "{family}", {fallback};
                    font-size: {config["size"]}pt;
                    font-weight: {config["weight"]};
                }}''')

    return "\n                ".join(css_rules)


def draw_text(text: si.Text, output):
    output.write('\t\t<g class="root-text" style="display:inline">')

    # Get config values for default text style
    plain_config = FONT_CONFIG["plain"]

    output.write(f'''
            <style><![CDATA[
                {_generate_font_face_css()}
                text {{
                    font-family: "{FONT_FAMILY_SANS}", sans-serif;
                    font-size: {plain_config["size"]}pt;
                    font-weight: {plain_config["weight"]};
                }}
                {_generate_font_css()}
                text.checkbox_checked, text.checkbox2_checked {{
                    text-decoration: line-through;
                }}
                tspan.inline-bold {{
                    font-weight: {FONT_WEIGHT_INLINE_BOLD};
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
        prev_was_list_style = prev_style in LIST_STYLES if prev_style else False
        if is_list_style and not prev_was_list_style and prev_style is not None:
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
            checkbox_x = rmc_config.xx(xpos) + checkbox_offset
            checkbox_y = rmc_config.yy(ypos) - CHECKBOX_SIZE + 2  # Align with text baseline
            output.write(f'\t\t\t<use href="#{checkbox_id}" x="{checkbox_x}" y="{checkbox_y}" '
                        f'width="{CHECKBOX_SIZE}" height="{CHECKBOX_SIZE}"/>\n')
            # Push text to the right of checkbox
            text_xpos = xpos + (checkbox_offset + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / rmc_config.scale
        elif is_bullet or is_bullet2:
            # Determine indentation and bullet style
            indent = BULLET_INDENT if is_bullet else BULLET2_INDENT
            bullet_id = "bullet" if is_bullet else "bullet2"
            
            # Position bullet before text
            bullet_x = rmc_config.xx(xpos) + indent - BULLET_SIZE - BULLET_GAP
            bullet_y = rmc_config.yy(ypos) - BULLET_SIZE / 2 - 1  # Center vertically with text
            output.write(f'\t\t\t<use href="#{bullet_id}" x="{bullet_x}" y="{bullet_y}" '
                        f'width="{BULLET_SIZE}" height="{BULLET_SIZE}"/>\n')
            # Indent text
            text_xpos = xpos + indent / rmc_config.scale
        elif is_numbered or is_numbered2:
            # Determine indentation and counter
            indent = NUMBERED_INDENT if is_numbered else NUMBERED2_INDENT
            counter = numbered_counter if is_numbered else numbered2_counter
            number_text = f"{counter}."
            
            # Render the number as text
            # For NUMBERED2, offset the number position to show nesting
            number_offset = 0 if is_numbered else NUMBERED2_OFFSET
            number_x = rmc_config.xx(xpos) + number_offset
            number_y = rmc_config.yy(ypos)
            output.write(f'\t\t\t<text x="{number_x}" y="{number_y}" class="{style_name}" xml:space="preserve">{number_text}</text>\n')
            # Indent text after number
            text_xpos = xpos + indent / rmc_config.scale
        
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
                available_width -= (CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / rmc_config.scale
            elif is_checkbox2:
                # Reduce available width by indented checkbox space
                available_width -= (CHECKBOX2_INDENT + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / rmc_config.scale
            elif is_bullet:
                # Reduce available width by bullet indent
                available_width -= BULLET_INDENT / rmc_config.scale
            elif is_bullet2:
                # Reduce available width by nested bullet indent
                available_width -= BULLET2_INDENT / rmc_config.scale
            elif is_numbered:
                # Reduce available width by numbered list indent
                available_width -= NUMBERED_INDENT / rmc_config.scale
            elif is_numbered2:
                # Reduce available width by nested numbered list indent
                available_width -= NUMBERED2_INDENT / rmc_config.scale
            
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
                    output.write(f'\t\t\t<text x="{rmc_config.xx(text_xpos)}" y="{rmc_config.yy(line_ypos)}" class="{style_name}" xml:space="preserve">')
                    
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
                    output.write(f'\t\t\t<text x="{rmc_config.xx(text_xpos)}" y="{rmc_config.yy(line_ypos)}" class="{style_name}" xml:space="preserve">{_escape_attrib(wrapped_text)}</text>\n')
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
