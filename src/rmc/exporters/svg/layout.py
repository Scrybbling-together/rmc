"""Text layout calculation, anchor positioning, and bounding box computation."""

import logging
import typing as tp

from rmscene import CrdtId
from rmscene import scene_items as si
from rmscene.text import TextDocument

# Import from sibling modules
from . import device
from . import fonts

_logger = logging.getLogger(__name__)

# =============================================================================
# LAYOUT CONSTANTS
# =============================================================================

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
    si.ParagraphStyle.HEADING: base * 0.3,  # Add extra space after headings
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

# Special anchor IDs for text document boundaries
TEXT_DOCUMENT_TOP_Y_CRDT_ID = 0xfffffffffffe
TEXT_DOCUMENT_BOTTOM_Y_CRDT_ID = 0xffffffffffff


class ParagraphLayoutInfo(tp.TypedDict):
    """Layout information for a single paragraph, calculated during text flow."""

    # Paragraph identity
    paragraph: object  # TextDocument paragraph object
    paragraph_index: int
    prev_style: tp.Optional[si.ParagraphStyle]

    # Y-offset tracking (core layout calculation)
    y_offset_before: float  # y_offset before processing this paragraph
    y_offset_after: float   # y_offset after processing this paragraph (includes all spacing)
    line_height: float
    soft_line_height: float

    # Style classification (determines indentation and spacing)
    is_list_style: bool
    prev_para_is_list_style: bool # is previous paragraph a list?
    is_checkbox: bool
    is_checkbox2: bool
    is_bullet: bool
    is_bullet2: bool
    is_numbered: bool
    is_numbered2: bool

    # Word wrapping calculations
    available_width: float
    content: str  # str(paragraph)
    num_soft_breaks: int  # Count of LINE_SEPARATOR characters
    segments: tp.List[str]  # content.split(LINE_SEPARATOR)
    total_wrapped_lines: int
    extra_wrapped_lines: int  # Beyond segments count

    # Spacing (applied to y_offset_after)
    space_after: float  # SPACE_AFTER[style] (e.g., after headings)
    item_spacing: float  # CHECKBOX_ITEM_SPACING or BULLET_ITEM_SPACING


def calculate_paragraph_layouts(
    text: tp.Optional[si.Text],
) -> tp.Iterator[ParagraphLayoutInfo]:
    """
    Generator that yields layout information for each paragraph in the text.

    The calculation follows the reMarkable text layout algorithm:
    1. Check for list style transitions (add BULLET_SECTION_GAP if transitioning from non-list to list)
    2. Add line_height to y_offset
    3. Count soft line breaks (LINE_SEPARATOR \\u2028) and add their height
    4. Calculate available width after accounting for list indentation (checkbox/bullet/numbered)
    5. Perform word wrapping to determine extra wrapped lines
    6. Add extra spacing (SPACE_AFTER for headings, item spacing for lists)

    Each paragraph's y_offset_after includes ALL spacing (soft breaks, wrapped lines,
    space_after, item_spacing), ready for the next paragraph or for positioning.

    :param text: Text object to process (may be None)
    :yield: ParagraphLayoutInfo for each paragraph in document order
    """
    LINE_SEPARATOR = '\u2028'

    if text is None:
        return

    doc = TextDocument.from_scene_item(text)
    if not doc.contents:
        return

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

    y_offset = TEXT_TOP_Y
    prev_style = None

    for i, p in enumerate(doc.contents):
        # Capture state before processing this paragraph
        y_offset_before = y_offset

        # Get paragraph-specific heights
        line_height = LINE_HEIGHTS.get(p.style.value, 70)
        soft_line_height = SOFT_LINE_HEIGHTS.get(p.style.value, 50)

        # Add section gap when transitioning from non-list to list style (must match draw_text)
        is_list_style = p.style.value in LIST_STYLES
        prev_was_list_style = prev_style in LIST_STYLES if prev_style else False
        if is_list_style and not prev_was_list_style and prev_style is not None:
            y_offset += BULLET_SECTION_GAP

        # Advance by paragraph line height
        y_offset += line_height

        # Get paragraph content for analysis
        content = str(p)

        # Account for soft line breaks (LINE_SEPARATOR)
        num_soft_breaks = content.count(LINE_SEPARATOR)
        if num_soft_breaks > 0:
            y_offset += num_soft_breaks * soft_line_height

        # Calculate available width after accounting for list indentation
        available_width = text.width - TEXT_WRAP_MARGIN

        # Classify paragraph style (determines indentation)
        is_checkbox = p.style.value in (si.ParagraphStyle.CHECKBOX, si.ParagraphStyle.CHECKBOX_CHECKED)
        is_checkbox2 = p.style.value in (si.ParagraphStyle.CHECKBOX2, si.ParagraphStyle.CHECKBOX2_CHECKED)
        is_bullet = p.style.value == si.ParagraphStyle.BULLET
        is_bullet2 = p.style.value == si.ParagraphStyle.BULLET2
        is_numbered = p.style.value == si.ParagraphStyle.NUMBERED
        is_numbered2 = p.style.value == si.ParagraphStyle.NUMBERED2

        # Reduce available width by indentation (must match draw_text)
        if is_checkbox:
            available_width -= (CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / device.rmc_config.scale
        elif is_checkbox2:
            available_width -= (CHECKBOX2_INDENT + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / device.rmc_config.scale
        elif is_bullet:
            available_width -= BULLET_INDENT / device.rmc_config.scale
        elif is_bullet2:
            available_width -= BULLET2_INDENT / device.rmc_config.scale
        elif is_numbered:
            available_width -= NUMBERED_INDENT / device.rmc_config.scale
        elif is_numbered2:
            available_width -= NUMBERED2_INDENT / device.rmc_config.scale

        # Calculate word wrapping (must match draw_text)
        # Split by LINE_SEPARATOR first, then wrap each segment
        segments = content.split(LINE_SEPARATOR)
        total_wrapped_lines = 0
        for segment in segments:
            if segment.strip():
                wrapped = fonts.wrap_text_to_width(segment, available_width, p.style.value)
                total_wrapped_lines += len(wrapped)
            else:
                total_wrapped_lines += 1  # Empty segment counts as one line

        # Calculate extra wrapped lines beyond the segment count
        extra_wrapped_lines = total_wrapped_lines - len(segments)
        if extra_wrapped_lines > 0:
            y_offset += extra_wrapped_lines * soft_line_height

        # Add extra space after certain paragraph styles (e.g., headings)
        space_after = SPACE_AFTER.get(p.style.value, 0)
        if space_after > 0:
            y_offset += space_after

        # Add list item spacing (must match draw_text)
        item_spacing = 0
        if is_checkbox or is_checkbox2:
            item_spacing = CHECKBOX_ITEM_SPACING
            y_offset += CHECKBOX_ITEM_SPACING
        elif is_bullet or is_bullet2 or is_numbered or is_numbered2:
            item_spacing = BULLET_ITEM_SPACING
            y_offset += BULLET_ITEM_SPACING

        # Yield complete layout information for this paragraph
        yield {
            'paragraph': p,
            'paragraph_index': i,
            'prev_style': prev_style,
            'y_offset_before': y_offset_before,
            'y_offset_after': y_offset,
            'line_height': line_height,
            'soft_line_height': soft_line_height,
            'is_list_style': is_list_style,
            'prev_para_is_list_style': prev_was_list_style,
            'is_checkbox': is_checkbox,
            'is_checkbox2': is_checkbox2,
            'is_bullet': is_bullet,
            'is_bullet2': is_bullet2,
            'is_numbered': is_numbered,
            'is_numbered2': is_numbered2,
            'available_width': available_width,
            'content': content,
            'num_soft_breaks': num_soft_breaks,
            'segments': segments,
            'total_wrapped_lines': total_wrapped_lines,
            'extra_wrapped_lines': extra_wrapped_lines,
            'space_after': space_after,
            'item_spacing': item_spacing,
        }

        prev_style = p.style.value


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
                    cumulative_x += fonts.get_char_width_screen(char, p.style.value)

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
        default = (- device.rmc_config.screen_width // 2, device.rmc_config.screen_width // 2, 0, device.rmc_config.screen_height)

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
