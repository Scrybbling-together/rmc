"""Convert blocks to svg file.

Code originally from https://github.com/lschwetlick/maxio through
https://github.com/chemag/maxio .
"""

import logging
import string
import typing as tp
from pathlib import Path

from rmscene.scene_items import Pen as PenType
from rmscene import CrdtId, SceneTree, read_tree
from rmscene import scene_items as si
from rmscene.text import TextDocument
from xml.etree.ElementTree import _escape_attrib

from .writing_tools import Pen

_logger = logging.getLogger(__name__)

SCREEN_WIDTH = 1404
SCREEN_HEIGHT = 1872
SCREEN_DPI = 226

TEXT_DOCUMENT_TOP_Y_CRDT_ID = 0xfffffffffffe
TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID = 0xffffffffffff

SCALE = 72.0 / SCREEN_DPI

PAGE_WIDTH_PT = SCREEN_WIDTH * SCALE
PAGE_HEIGHT_PT = SCREEN_HEIGHT * SCALE
X_SHIFT = PAGE_WIDTH_PT // 2


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
}

# Estimated character widths per style (fallback values)
CHAR_WIDTHS = {
    si.ParagraphStyle.PLAIN: 11,
    si.ParagraphStyle.BULLET: 11,
    si.ParagraphStyle.BULLET2: 11,
    si.ParagraphStyle.BOLD: 12,
    si.ParagraphStyle.HEADING: 22,
    si.ParagraphStyle.CHECKBOX: 11,
    si.ParagraphStyle.CHECKBOX_CHECKED: 11,
}

def get_char_width_screen(char: str, style: si.ParagraphStyle) -> float:
    """Get character width in screen units using estimated widths."""
    if not char:
        return 0.0
    return CHAR_WIDTHS.get(style, 11)

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

    # Calculate y positions the same way draw_text does
    y_offset = TEXT_TOP_Y
    y_positions = []
    for p in doc.contents:
        y_offset += LINE_HEIGHTS.get(p.style.value, 70)
        y_positions.append(text.pos_y + y_offset)

        # Account for soft line breaks
        content = str(p)
        num_soft_breaks = content.count(LINE_SEPARATOR)
        if num_soft_breaks > 0:
            soft_line_height = SOFT_LINE_HEIGHTS.get(p.style.value, 50)
            y_offset += num_soft_breaks * soft_line_height
            y_positions.append(text.pos_y + y_offset)

        # Account for space after
        space_after = SPACE_AFTER.get(p.style.value, 0)
        if space_after > 0:
            y_offset += space_after

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
    anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset = build_anchor_pos(tree.root_text)
    _logger.debug("anchor_pos: %s", anchor_pos)
    _logger.debug("newline_offsets: %s", newline_offsets)

    # Get text_pos_x for TEXT_CHAR anchor calculations
    text_pos_x = tree.root_text.pos_x if tree.root_text is not None else None

    # find the extremum along x and y (for strokes)
    x_min, x_max, y_min, y_max = get_bounding_box(tree.root, anchor_pos, newline_offsets, text_pos_x, anchor_x_pos, anchor_soft_offset)

    # Also include text bounds
    txt_x_min, txt_x_max, txt_y_min, txt_y_max = get_text_bounding_box(tree.root_text)
    if tree.root_text is not None:
        x_min = min(x_min, txt_x_min)
        x_max = max(x_max, txt_x_max)
        y_min = min(y_min, txt_y_min)
        y_max = max(y_max, txt_y_max)

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


def build_anchor_pos(text: tp.Optional[si.Text]) -> tp.Tuple[tp.Dict[CrdtId, int], tp.Dict[CrdtId, int], tp.Dict[CrdtId, float], tp.Dict[CrdtId, float]]:
    """
    Find the anchor positions for every text node, including special top and
    bottom of text anchors.

    :param text: the root text of the remarkable file
    :return: (anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset) where:
        - anchor_pos maps CrdtId -> y position (includes soft line offset)
        - newline_offsets maps newline CrdtIds -> offset to subtract (one line height)
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

        for i, p in enumerate(doc.contents):
            line_height = LINE_HEIGHTS.get(p.style.value, 70)
            soft_line_height = SOFT_LINE_HEIGHTS.get(p.style.value, 50)
            y_offset += line_height
            ypos = text.pos_y + y_offset

            anchor_pos[p.start_id] = ypos

            if i > 0:
                newline_offsets[p.start_id] = line_height

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

            # Add extra space after certain paragraph styles (e.g., headings)
            space_after = SPACE_AFTER.get(p.style.value, 0)
            if space_after > 0:
                y_offset += space_after

            visible_content = content.replace(LINE_SEPARATOR, '').strip()
            if visible_content:
                last_content_y_offset = y_offset

        if doc.contents:
            first_y_offset = TEXT_TOP_Y + LINE_HEIGHTS.get(doc.contents[0].style.value, 70)
            anchor_pos[CrdtId(0, TEXT_DOCUMENT_TOP_Y_CRDT_ID)] = text.pos_y + first_y_offset
            anchor_pos[CrdtId(0, TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID)] = text.pos_y + last_content_y_offset

    return anchor_pos, newline_offsets, anchor_x_pos, anchor_soft_offset


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
                _logger.debug("Group anchor: %s -> y=%.1f (newline, shifted up by %d)",
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
                     default: tp.Tuple[int, int, int, int] = (- SCREEN_WIDTH // 2, SCREEN_WIDTH // 2, 0, SCREEN_HEIGHT)) \
        -> tp.Tuple[int, int, int, int]:
    """Get the bounding box of the given item."""
    if newline_offsets is None:
        newline_offsets = {}
    if anchor_x_pos is None:
        anchor_x_pos = {}
    if anchor_soft_offset is None:
        anchor_soft_offset = {}

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

    # add some style to get readable text
    output.write('''
            <style>
                text.heading {
                    font: 14pt serif;
                }
                text.bold {
                    font: 8pt sans-serif bold;
                }
                text, text.plain {
                    font: 7pt sans-serif;
                }
            </style>
''')

    LINE_SEPARATOR = '\u2028'
    y_offset = TEXT_TOP_Y

    doc = TextDocument.from_scene_item(text)
    for p in doc.contents:
        line_height = LINE_HEIGHTS.get(p.style.value, 70)
        soft_line_height = SOFT_LINE_HEIGHTS.get(p.style.value, 50)
        y_offset += line_height

        xpos = text.pos_x
        ypos = text.pos_y + y_offset
        cls = p.style.value.name.lower()
        content = str(p)

        lines = content.split(LINE_SEPARATOR)
        line_offset = 0
        for line_content in lines:
            if line_content.strip():
                if _logger.root.level == logging.DEBUG:
                    output.write(f'\t\t\t<!-- Text line char_id: {p.start_id} offset {line_offset} -->\n')
                line_ypos = ypos + (line_offset * soft_line_height)
                output.write(f'\t\t\t<text x="{xx(xpos)}" y="{yy(line_ypos)}" class="{cls}" xml:space="preserve">{_escape_attrib(line_content)}</text>\n')
            line_offset += 1

        extra_lines = len(lines) - 1
        if extra_lines > 0:
            y_offset += extra_lines * soft_line_height

        # Add extra space after certain paragraph styles (e.g., headings)
        space_after = SPACE_AFTER.get(p.style.value, 0)
        if space_after > 0:
            y_offset += space_after

    output.write('\t\t</g>\n')
