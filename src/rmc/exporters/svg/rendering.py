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

# Import from device module
from .device import rmc_config

# Import from fonts module
from .fonts import (
    FONTS,
    FONT_CONFIG,
    FONT_WEIGHT_INLINE_BOLD,
    FONT_FAMILY_SANS,
    get_font_family_sans,
    get_font_family_serif,
    _resolve_font_config,
    wrap_text_to_width,
)

# Import from layout module
from .layout import (
    build_anchor_pos,
    get_anchor,
    get_bounding_box,
)

# Import from paragraph_styles module
from .paragraph_styles import (
    get_style_config,
    BULLET_SECTION_GAP,
    TEXT_WRAP_MARGIN,
    TEXT_TOP_Y,
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
        font_path = resolved["path"]
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

    # Track previous style for section gaps
    prev_style = None
    prev_style_config = None

    # Counter management - keyed by counter_key
    counters: tp.Dict[str, int] = {}

    doc = TextDocument.from_scene_item(text)
    for p_idx, p in enumerate(doc.contents):
        # Get style configuration
        style_config = get_style_config(p.style.value)
        line_height = style_config.line_height
        soft_line_height = style_config.soft_line_height

        # Add section gap when transitioning from non-list to list style
        is_list_style = style_config.is_list_style
        prev_was_list_style = prev_style_config.is_list_style if prev_style_config else False
        if is_list_style and not prev_was_list_style and prev_style is not None:
            y_offset += BULLET_SECTION_GAP

        # Counter management - generalized via style_config
        counter_value = None
        if style_config.needs_counter:
            key = style_config.counter_key
            # Reset counter if previous style used a different counter
            prev_key = prev_style_config.counter_key if prev_style_config else None
            if prev_key != key:
                counters[key] = 0
            counters[key] = counters.get(key, 0) + 1
            counter_value = counters[key]

        y_offset += line_height

        xpos = text.pos_x
        ypos = text.pos_y + y_offset
        style_name = p.style.value.name.lower()

        # Draw marker using style_config (checkbox/bullet/number)
        style_config.draw_marker(xpos, ypos, output, rmc_config, counter=counter_value)

        # Calculate text X offset using style_config
        text_xpos = xpos + style_config.text_x_offset(rmc_config.scale)
        
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
            available_width -= style_config.width_reduction(rmc_config.scale)
            
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
        space_after = style_config.space_after
        if space_after > 0:
            y_offset += space_after

        # Add list item spacing
        item_spacing = style_config.item_spacing
        if item_spacing > 0:
            y_offset += item_spacing

        # Update previous style for next iteration
        prev_style = p.style.value
        prev_style_config = style_config

    output.write('\t\t</g>\n')
