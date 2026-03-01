"""Text layout calculation, anchor positioning, and bounding box computation."""

import logging
import typing as tp

from rmscene import CrdtId
from rmscene import scene_items as si
from rmscene.text import TextDocument

# Import from sibling modules
from . import device
from . import fonts
from .paragraph_styles import (
    ParagraphStyleConfig,
    get_style_config,
    BULLET_SECTION_GAP,
    TEXT_WRAP_MARGIN,
    TEXT_TOP_Y,
)

_logger = logging.getLogger(__name__)

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

    # Style configuration (encapsulates all style-specific behavior)
    style_config: ParagraphStyleConfig
    is_list_style: bool
    prev_para_is_list_style: bool  # is previous paragraph a list?

    # Word wrapping calculations
    available_width: float
    content: str  # str(paragraph)
    num_soft_breaks: int  # Count of LINE_SEPARATOR characters
    segments: tp.List[str]  # content.split(LINE_SEPARATOR)
    total_wrapped_lines: int
    extra_wrapped_lines: int  # Beyond segments count

    # Spacing (applied to y_offset_after)
    space_after: float  # style_config.space_after (e.g., after headings)
    item_spacing: float  # style_config.item_spacing


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
    6. Add extra spacing (space_after for headings, item_spacing for lists)

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

    y_offset = TEXT_TOP_Y
    prev_style = None
    prev_style_config: tp.Optional[ParagraphStyleConfig] = None

    for i, p in enumerate(doc.contents):
        # Get style configuration - replaces LINE_HEIGHTS/SOFT_LINE_HEIGHTS lookups
        style_config = get_style_config(p.style.value)
        line_height = style_config.line_height
        soft_line_height = style_config.soft_line_height

        # Add section gap when transitioning from non-list to list style
        is_list_style = style_config.is_list_style
        prev_was_list_style = prev_style_config.is_list_style if prev_style_config else False
        if is_list_style and not prev_was_list_style and prev_style is not None:
            y_offset += BULLET_SECTION_GAP

        # Capture state AFTER bullet section gap but BEFORE line_height
        # This matches how draw_text calculates ypos = text.pos_y + y_offset (after gap, after line_height)
        y_offset_before = y_offset

        # Advance by paragraph line height
        y_offset += line_height

        # Get paragraph content for analysis
        content = str(p)

        # Account for soft line breaks (LINE_SEPARATOR)
        num_soft_breaks = content.count(LINE_SEPARATOR)
        if num_soft_breaks > 0:
            y_offset += num_soft_breaks * soft_line_height

        # Calculate available width - use style_config.width_reduction()
        available_width = text.width - TEXT_WRAP_MARGIN
        available_width -= style_config.width_reduction(device.rmc_config.scale)

        # Calculate word wrapping
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
        space_after = style_config.space_after
        if space_after > 0:
            y_offset += space_after

        # Add list item spacing
        item_spacing = style_config.item_spacing
        if item_spacing > 0:
            y_offset += item_spacing

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
            'style_config': style_config,
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
        prev_style_config = style_config


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
        if i > 0 and layout['prev_style'] is not None:
            prev_style_config = get_style_config(layout['prev_style'])
            prev_space_after = prev_style_config.space_after
            offset = layout['line_height'] + prev_space_after
            # When transitioning from non-list to list, BULLET_SECTION_GAP was added to y_offset.
            # Include it in newline_offset so strokes anchored to paragraph start align correctly.
            if layout['is_list_style'] and not layout['prev_para_is_list_style']:
                offset += BULLET_SECTION_GAP
            newline_offsets[p.start_id] = offset

        # Track character-level positions (unique to build_anchor_pos)
        # This is the only part that can't be shared, as it needs per-character iteration
        current_soft_offset = 0
        cumulative_x = 0.0
        available_width = layout['available_width']
        soft_line_height = layout['soft_line_height']
        
        # Track word boundaries for proper wrapping
        current_word_start_x = 0.0
        current_word_chars = []  # List of (id, char) tuples in current word

        for subp in p.contents:
            for j, k in enumerate(subp.i):
                char = subp.s[j] if j < len(subp.s) else ''
                
                if char == LINE_SEPARATOR:
                    # Explicit soft line break
                    # First, finalize positions for any pending word
                    for word_k, word_char in current_word_chars:
                        anchor_pos[word_k] = ypos + current_soft_offset
                    current_word_chars = []
                    
                    anchor_pos[k] = ypos + current_soft_offset
                    anchor_x_pos[k] = text.pos_x + cumulative_x
                    anchor_soft_offset[k] = current_soft_offset
                    
                    current_soft_offset += soft_line_height
                    cumulative_x = 0.0
                    current_word_start_x = 0.0
                elif char == ' ':
                    # Space - finalize current word and check if next word needs to wrap
                    for word_k, word_char in current_word_chars:
                        anchor_pos[word_k] = ypos + current_soft_offset
                    current_word_chars = []
                    
                    anchor_pos[k] = ypos + current_soft_offset
                    anchor_x_pos[k] = text.pos_x + cumulative_x
                    anchor_soft_offset[k] = current_soft_offset
                    
                    cumulative_x += fonts.get_char_width_screen(char, p.style.value)
                    current_word_start_x = cumulative_x
                else:
                    # Regular character - add to current word
                    char_width = fonts.get_char_width_screen(char, p.style.value)
                    
                    # Check if adding this character would exceed the line width
                    # If so, wrap the entire current word to the next line
                    if cumulative_x + char_width > available_width and current_word_start_x > 0:
                        # Wrap: move to next line
                        current_soft_offset += soft_line_height
                        
                        # Recalculate X positions for current word on new line
                        new_x = 0.0
                        for word_k, word_char in current_word_chars:
                            anchor_x_pos[word_k] = text.pos_x + new_x
                            anchor_pos[word_k] = ypos + current_soft_offset
                            anchor_soft_offset[word_k] = current_soft_offset
                            new_x += fonts.get_char_width_screen(word_char, p.style.value)
                        
                        cumulative_x = new_x
                        current_word_start_x = 0.0
                    
                    # Add this character
                    anchor_x_pos[k] = text.pos_x + cumulative_x
                    anchor_soft_offset[k] = current_soft_offset
                    current_word_chars.append((k, char))
                    cumulative_x += char_width
        
        # Finalize any remaining word
        for word_k, word_char in current_word_chars:
            anchor_pos[word_k] = ypos + current_soft_offset

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

            # Apply newline_offset for paragraph boundary anchors
            if item.anchor_id.value in newline_offsets:
                # For type 1 (TEXT_CHAR) anchors at paragraph starts, check if the paragraph has content
                # Empty paragraphs should NOT have newline_offset applied for type 1 anchors
                # because the stroke is likely meant to align with content below, not above
                should_apply_newline_offset = True
                
                if item.anchor_type is not None and item.anchor_type.value == 1:
                    # Check if this paragraph has content by looking for character positions
                    # near the anchor ID in anchor_x_pos
                    anchor_part1 = item.anchor_id.value.part1
                    anchor_part2 = item.anchor_id.value.part2
                    has_content = any(
                        CrdtId(anchor_part1, anchor_part2 + offset) in anchor_x_pos
                        for offset in range(1, 15)
                    )
                    if not has_content:
                        should_apply_newline_offset = False
                        _logger.debug("TEXT_CHAR anchor at empty para: %s -> y=%.1f (no newline shift)",
                                      item.anchor_id.value, anchor_y)
                
                if should_apply_newline_offset:
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
