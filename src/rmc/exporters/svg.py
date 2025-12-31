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
LINE_HEIGHTS = {
    # Based on a rm file having 4 anchors based on the line height I was able to find a value of
    # 69.5, but decided on 70 (to keep integer values)
    si.ParagraphStyle.PLAIN: 70,
    si.ParagraphStyle.BULLET: 35,
    si.ParagraphStyle.BULLET2: 35,
    si.ParagraphStyle.BOLD: 70,
    si.ParagraphStyle.HEADING: 150,
    si.ParagraphStyle.CHECKBOX: 35,
    si.ParagraphStyle.CHECKBOX_CHECKED: 35,

    # There appears to be another format code (value 0) which is used when the
    # text starts far down the page, which case it has a negative offset (line
    # height) of about -20?
    #
    # Probably, actually, the line height should be added *after* the first
    # line, but there is still something a bit odd going on here.
}

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
    anchor_pos, newline_offsets = build_anchor_pos(tree.root_text)
    _logger.debug("anchor_pos: %s", anchor_pos)
    _logger.debug("newline_offsets: %s", newline_offsets)

    # find the extremum along x and y (for strokes)
    x_min, x_max, y_min, y_max = get_bounding_box(tree.root, anchor_pos, newline_offsets)
    
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

    draw_group(tree.root, output, anchor_pos, newline_offsets)

    # Closing page group
    output.write('\t</g>\n')
    # END notebook
    output.write('</svg>\n')


def build_anchor_pos(text: tp.Optional[si.Text]) -> tp.Tuple[tp.Dict[CrdtId, int], tp.Dict[CrdtId, int]]:
    """
    Find the anchor positions for every text node, including special top and
    bottom of text anchors.

    :param text: the root text of the remarkable file
    :return: (anchor_pos, newline_offsets) where:
        - anchor_pos maps CrdtId -> y position
        - newline_offsets maps newline CrdtIds -> offset to subtract (one line height)
    """
    # Start with placeholder values for special anchors - will be updated below
    anchor_pos = {
        CrdtId(0, TEXT_DOCUMENT_TOP_Y_CRDT_ID): 100,
        CrdtId(0, TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID): 100,
    }
    
    # Track newline anchors and their line height offset
    # A paragraph's start_id is the newline that ENDS the previous paragraph.
    # Strokes anchored to a newline should appear at the PREVIOUS line's position,
    # so we need to subtract one line height when rendering.
    newline_offsets: tp.Dict[CrdtId, int] = {}

    if text is not None:
        doc = TextDocument.from_scene_item(text)
        y_offset = TEXT_TOP_Y
        
        for i, p in enumerate(doc.contents):
            # Add line height first (to match draw_text behavior)
            line_height = LINE_HEIGHTS.get(p.style.value, 70)
            y_offset += line_height
            ypos = text.pos_y + y_offset
            
            # Store position for this paragraph's start_id
            anchor_pos[p.start_id] = ypos
            
            # For paragraphs after the first, the start_id is a newline character
            # that visually belongs to the PREVIOUS line. Record the offset needed.
            if i > 0:
                newline_offsets[p.start_id] = line_height
            
            # Characters in this paragraph get this paragraph's position
            for subp in p.contents:
                for k in subp.i:
                    anchor_pos[k] = ypos
 
        # Update special anchors to align with text positions:
        # - TEXT_DOCUMENT_TOP_Y_CRDT_ID -> first text baseline
        # - TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID -> last text baseline
        if doc.contents:
            first_y_offset = TEXT_TOP_Y + LINE_HEIGHTS.get(doc.contents[0].style.value, 70)
            anchor_pos[CrdtId(0, TEXT_DOCUMENT_TOP_Y_CRDT_ID)] = text.pos_y + first_y_offset
            anchor_pos[CrdtId(0, TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID)] = text.pos_y + y_offset  # last position

    return anchor_pos, newline_offsets


def get_anchor(item: si.Group, anchor_pos, newline_offsets=None):
    """
    Get the anchor position for a group.
    
    :param item: The group to get anchor for
    :param anchor_pos: Map of CrdtId -> y position
    :param newline_offsets: Map of newline CrdtIds -> offset to subtract.
        When a stroke is anchored to a newline character, it should be
        positioned at the PREVIOUS line, so we subtract the line height.
    """
    if newline_offsets is None:
        newline_offsets = {}
        
    anchor_x = 0.0
    anchor_y = 0.0
    if item.anchor_id is not None:
        assert item.anchor_origin_x is not None
        anchor_x = item.anchor_origin_x.value
        if item.anchor_id.value in anchor_pos:
            anchor_y = anchor_pos[item.anchor_id.value]
            
            # If this anchor is a newline, adjust y to previous line's position
            if item.anchor_id.value in newline_offsets:
                anchor_y -= newline_offsets[item.anchor_id.value]
                _logger.debug("Group anchor: %s -> y=%.1f (newline, shifted up by %d)",
                              item.anchor_id.value,
                              anchor_y,
                              newline_offsets[item.anchor_id.value])
            else:
                _logger.debug("Group anchor: %s -> y=%.1f (scalded y=%.1f)",
                              item.anchor_id.value,
                              anchor_y,
                              yy(anchor_y))
        else:
            _logger.warning("Group anchor: %s is unknown!", item.anchor_id.value)

    return anchor_x, anchor_y


def get_bounding_box(item: si.Group,
                     anchor_pos: tp.Dict[CrdtId, int],
                     newline_offsets: tp.Dict[CrdtId, int] = None,
                     default: tp.Tuple[int, int, int, int] = (- SCREEN_WIDTH // 2, SCREEN_WIDTH // 2, 0, SCREEN_HEIGHT)) \
        -> tp.Tuple[int, int, int, int]:
    """
    Get the bounding box of the given item.
    The minimum size is the default size of the screen.

    :return: x_min, x_max, y_min, y_max: the bounding box in screen units (need to be scalded using xx and yy functions)
    """
    if newline_offsets is None:
        newline_offsets = {}
        
    x_min, x_max, y_min, y_max = default

    for child_id in item.children:
        child = item.children[child_id]
        if isinstance(child, si.Group):
            anchor_x, anchor_y = get_anchor(child, anchor_pos, newline_offsets)
            x_min_t, x_max_t, y_min_t, y_max_t = get_bounding_box(child, anchor_pos, newline_offsets, (0, 0, 0, 0))
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


def draw_group(item: si.Group, output, anchor_pos, newline_offsets=None):
    if newline_offsets is None:
        newline_offsets = {}
    anchor_x, anchor_y = get_anchor(item, anchor_pos, newline_offsets)
    output.write(f'\t\t<g id="{item.node_id}" transform="translate({xx(anchor_x)}, {yy(anchor_y)})">\n')
    for child_id in item.children:
        child = item.children[child_id]
        _logger.debug("Group child: %s %s", child_id, type(child))
        if _logger.root.level == logging.DEBUG:
            output.write(f'\t\t<!-- child {child_id} {type(child)} -->\n')
        if isinstance(child, si.Group):
            draw_group(child, output, anchor_pos, newline_offsets)
        elif isinstance(child, si.Line):
            draw_stroke(child, output)
    output.write(f'\t\t</g>\n')


def draw_stroke(item: si.Line, output):
    # print debug infos
    if _logger.root.level == logging.DEBUG:
        _logger.debug("Writing line: %s", item)
        output.write(f'\t\t\t<!-- Stroke tool: {item.tool.name} '
                     f'color: {item.color.name} thickness_scale: {item.thickness_scale} -->\n')

    # initiate the pen
    pen = Pen.create(item.tool.value, item.color.value, item.thickness_scale)

    last_xpos = -1.
    last_ypos = -1.
    last_segment_width = segment_width = 0
    # Iterate through the point to form a polyline
    for point_idx, point in enumerate(item.points):
        # align the original position
        xpos = point.x
        ypos = point.y
        if point_idx % pen.segment_length == 0:
            # if there was a previous segment, end it
            if point_idx > 0:
                output.write('"/>\n')

            segment_color = pen.get_segment_color(point.speed, point.direction, point.width, point.pressure,
                                                  last_segment_width)
            segment_width = pen.get_segment_width(point.speed, point.direction, point.width, point.pressure,
                                                  last_segment_width)
            segment_opacity = pen.get_segment_opacity(point.speed, point.direction, point.width, point.pressure,
                                                      last_segment_width)
            # create the next segment of the stroke
            output.write('\t\t\t<polyline ')
            output.write(f'style="fill:none; stroke:{segment_color}; '
                         f'stroke-width:{scale(segment_width):.3f}; opacity:{segment_opacity}" ')
            output.write(f'stroke-linecap="{pen.stroke_linecap}" ')
            output.write('points="')
            if point_idx > 0:
                # Join to previous segment
                output.write(f'{xx(last_xpos):.3f},{yy(last_ypos):.3f} ')
        # store the last position
        last_xpos = xpos
        last_ypos = ypos
        last_segment_width = segment_width

        # add current point
        output.write(f'{xx(xpos):.3f},{yy(ypos):.3f} ')

    # end stroke
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

    y_offset = TEXT_TOP_Y

    doc = TextDocument.from_scene_item(text)
    for p in doc.contents:
        y_offset += LINE_HEIGHTS.get(p.style.value, 70)

        xpos = text.pos_x
        ypos = text.pos_y + y_offset
        cls = p.style.value.name.lower()
        content = str(p)
        if content.strip():
            # TODO: this doesn't take into account the CrdtStr.properties (font-weight/font-style)
            if _logger.root.level == logging.DEBUG:
                output.write(f'\t\t\t<!-- Text line char_id: {p.start_id} -->\n')
            output.write(f'\t\t\t<text x="{xx(xpos)}" y="{yy(ypos)}" class="{cls}" xml:space="preserve">{_escape_attrib(content)}</text>\n')
    output.write('\t\t</g>\n')
