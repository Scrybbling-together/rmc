"""Paragraph style configuration classes for SVG text rendering.

This module consolidates all paragraph style-specific behavior into a class hierarchy,
eliminating scattered constants and if/elif chains from layout.py and rendering.py.
"""

import typing as tp
from abc import ABC, abstractmethod

from rmscene import scene_items as si

if tp.TYPE_CHECKING:
    from .device import SvgRenderConfig


# =============================================================================
# CONSTANTS
# =============================================================================

# Base line heights (in screen units)
BASE_LINE_HEIGHT = 69.5
SOFT_LINE_BASE = 60
SOFT_LINE_SMALL = 40

# Checkbox constants
CHECKBOX_SIZE = 12  # Size in points
CHECKBOX_TEXT_GAP = 4  # Gap between checkbox and text in points
CHECKBOX_ITEM_SPACING = 30  # Extra spacing between checkbox items in screen units
CHECKBOX2_INDENT = 12  # Indentation for nested checkbox in points

# Bullet constants
BULLET_SIZE = 4  # Bullet circle diameter in points
BULLET_INDENT = 12  # Indentation for bullet text in points
BULLET2_INDENT = 24  # Indentation for nested bullet text in points
BULLET_GAP = 6  # Gap between bullet and text in points
BULLET_ITEM_SPACING = 20  # Extra spacing between bullet items in screen units
BULLET_SECTION_GAP = 30  # Gap before bullet section starts (from non-bullet paragraph)

# Numbered list constants
NUMBERED_INDENT = 12  # Indentation for numbered list text in points
NUMBERED2_INDENT = 24  # Indentation for nested numbered list text in points
NUMBERED_GAP = 4  # Gap between number and text in points
NUMBERED2_OFFSET = 12  # Offset for nested numbered list number position

# Text wrap margin
TEXT_WRAP_MARGIN = 236  # Approximate margin in screen units

# Text positioning
TEXT_TOP_Y = -88

class ParagraphStyleConfig(ABC):
    """Abstract base class for paragraph style configurations.

    Each subclass encapsulates:
    - Layout calculations (line heights, spacing, width reductions)
    - Rendering behavior (marker drawing)
    """

    @property
    @abstractmethod
    def line_height(self) -> float:
        """Vertical spacing for paragraph (screen units)."""
        pass

    @property
    def soft_line_height(self) -> float:
        """Vertical spacing for soft line breaks (screen units)."""
        return SOFT_LINE_SMALL  # Default for list styles

    @property
    def space_after(self) -> float:
        """Extra spacing after paragraph (screen units). Only HEADING has non-zero."""
        return 0.0

    @property
    def item_spacing(self) -> float:
        """Extra spacing after list items (screen units)."""
        return 0.0

    @property
    def is_list_style(self) -> bool:
        """Whether this style is a list style (for section gap logic)."""
        return False

    @property
    def needs_counter(self) -> bool:
        """Whether this style uses a counter (for numbered lists)."""
        return False

    @property
    def counter_key(self) -> tp.Optional[str]:
        """Key for counter tracking (e.g., 'numbered', 'numbered2'). None if no counter."""
        return None

    def width_reduction(self, scale: float) -> float:
        """How much width (in screen units) the marker consumes.

        :param scale: Device scale factor (72.0 / DPI)
        :return: Width reduction in screen units
        """
        return 0.0

    def text_x_offset(self, scale: float) -> float:
        """X offset for text after marker (in screen units).

        :param scale: Device scale factor (72.0 / DPI)
        :return: X offset in screen units
        """
        return 0.0

    def draw_marker(
        self,
        xpos: float,
        ypos: float,
        output: tp.TextIO,
        rmc_config: "SvgRenderConfig",
        counter: tp.Optional[int] = None,
    ) -> None:
        """Render the marker SVG (checkbox/bullet/number).

        :param xpos: Text block X position in screen units
        :param ypos: Current line Y position in screen units
        :param output: File-like object to write SVG to
        :param rmc_config: Device configuration for coordinate conversion
        :param counter: Counter value for numbered lists (1, 2, 3...)
        """
        pass  # Default: no marker


class PlainStyleConfig(ParagraphStyleConfig):
    """Normal text style."""

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT

    @property
    def soft_line_height(self) -> float:
        return SOFT_LINE_BASE


class BoldStyleConfig(ParagraphStyleConfig):
    """Bold text style."""

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT

    @property
    def soft_line_height(self) -> float:
        return SOFT_LINE_SMALL


class HeadingStyleConfig(ParagraphStyleConfig):
    """Heading style with large serif text and extra space after."""

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT * 2

    @property
    def soft_line_height(self) -> float:
        return SOFT_LINE_BASE

    @property
    def space_after(self) -> float:
        return BASE_LINE_HEIGHT * 0.3


class Bullet1StyleConfig(ParagraphStyleConfig):
    """First-level bullet list item (circle marker)."""

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT / 2

    @property
    def item_spacing(self) -> float:
        return BULLET_ITEM_SPACING

    @property
    def is_list_style(self) -> bool:
        return True

    def width_reduction(self, scale: float) -> float:
        return BULLET_INDENT / scale

    def text_x_offset(self, scale: float) -> float:
        return BULLET_INDENT / scale

    def draw_marker(self, xpos, ypos, output, rmc_config, counter=None):
        bullet_x = rmc_config.xx(xpos) + BULLET_INDENT - BULLET_SIZE - BULLET_GAP
        bullet_y = rmc_config.yy(ypos) - BULLET_SIZE / 2 - 1
        output.write(
            f'\t\t\t<use href="#bullet" x="{bullet_x}" y="{bullet_y}" '
            f'width="{BULLET_SIZE}" height="{BULLET_SIZE}"/>\n'
        )


class Bullet2StyleConfig(ParagraphStyleConfig):
    """Second-level bullet list item (dash marker)."""

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT / 2

    @property
    def item_spacing(self) -> float:
        return BULLET_ITEM_SPACING

    @property
    def is_list_style(self) -> bool:
        return True

    def width_reduction(self, scale: float) -> float:
        return BULLET2_INDENT / scale

    def text_x_offset(self, scale: float) -> float:
        return BULLET2_INDENT / scale

    def draw_marker(self, xpos, ypos, output, rmc_config, counter=None):
        bullet_x = rmc_config.xx(xpos) + BULLET2_INDENT - BULLET_SIZE - BULLET_GAP
        bullet_y = rmc_config.yy(ypos) - BULLET_SIZE / 2 - 1
        output.write(
            f'\t\t\t<use href="#bullet2" x="{bullet_x}" y="{bullet_y}" '
            f'width="{BULLET_SIZE}" height="{BULLET_SIZE}"/>\n'
        )


class Checkbox1StyleConfig(ParagraphStyleConfig):
    """First-level checkbox (checked or unchecked)."""

    def __init__(self, is_checked: bool = False):
        self._is_checked = is_checked

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT / 2

    @property
    def item_spacing(self) -> float:
        return CHECKBOX_ITEM_SPACING

    @property
    def is_list_style(self) -> bool:
        return True

    @property
    def is_checked(self) -> bool:
        return self._is_checked

    def width_reduction(self, scale: float) -> float:
        return (CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / scale

    def text_x_offset(self, scale: float) -> float:
        return (CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / scale

    def draw_marker(self, xpos, ypos, output, rmc_config, counter=None):
        checkbox_id = "checkbox-checked" if self._is_checked else "checkbox-unchecked"
        checkbox_x = rmc_config.xx(xpos)
        checkbox_y = rmc_config.yy(ypos) - CHECKBOX_SIZE + 2
        output.write(
            f'\t\t\t<use href="#{checkbox_id}" x="{checkbox_x}" y="{checkbox_y}" '
            f'width="{CHECKBOX_SIZE}" height="{CHECKBOX_SIZE}"/>\n'
        )


class Checkbox2StyleConfig(ParagraphStyleConfig):
    """Second-level (nested) checkbox (checked or unchecked)."""

    def __init__(self, is_checked: bool = False):
        self._is_checked = is_checked

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT / 2

    @property
    def item_spacing(self) -> float:
        return CHECKBOX_ITEM_SPACING

    @property
    def is_list_style(self) -> bool:
        return True

    @property
    def is_checked(self) -> bool:
        return self._is_checked

    def width_reduction(self, scale: float) -> float:
        return (CHECKBOX2_INDENT + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / scale

    def text_x_offset(self, scale: float) -> float:
        return (CHECKBOX2_INDENT + CHECKBOX_SIZE + CHECKBOX_TEXT_GAP) / scale

    def draw_marker(self, xpos, ypos, output, rmc_config, counter=None):
        checkbox_id = "checkbox-checked" if self._is_checked else "checkbox-unchecked"
        checkbox_x = rmc_config.xx(xpos) + CHECKBOX2_INDENT
        checkbox_y = rmc_config.yy(ypos) - CHECKBOX_SIZE + 2
        output.write(
            f'\t\t\t<use href="#{checkbox_id}" x="{checkbox_x}" y="{checkbox_y}" '
            f'width="{CHECKBOX_SIZE}" height="{CHECKBOX_SIZE}"/>\n'
        )

class Numbered1StyleConfig(ParagraphStyleConfig):
    """First-level numbered list item."""

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT / 2

    @property
    def item_spacing(self) -> float:
        return BULLET_ITEM_SPACING

    @property
    def is_list_style(self) -> bool:
        return True

    @property
    def needs_counter(self) -> bool:
        return True

    @property
    def counter_key(self) -> str:
        return "numbered"

    def width_reduction(self, scale: float) -> float:
        return NUMBERED_INDENT / scale

    def text_x_offset(self, scale: float) -> float:
        return NUMBERED_INDENT / scale

    def draw_marker(self, xpos, ypos, output, rmc_config, counter=None):
        number_text = f"{counter}."
        number_x = rmc_config.xx(xpos)
        number_y = rmc_config.yy(ypos)
        output.write(
            f'\t\t\t<text x="{number_x}" y="{number_y}" class="numbered" '
            f'xml:space="preserve">{number_text}</text>\n'
        )


class Numbered2StyleConfig(ParagraphStyleConfig):
    """Second-level (nested) numbered list item."""

    @property
    def line_height(self) -> float:
        return BASE_LINE_HEIGHT / 2

    @property
    def item_spacing(self) -> float:
        return BULLET_ITEM_SPACING

    @property
    def is_list_style(self) -> bool:
        return True

    @property
    def needs_counter(self) -> bool:
        return True

    @property
    def counter_key(self) -> str:
        return "numbered2"

    def width_reduction(self, scale: float) -> float:
        return NUMBERED2_INDENT / scale

    def text_x_offset(self, scale: float) -> float:
        return NUMBERED2_INDENT / scale

    def draw_marker(self, xpos, ypos, output, rmc_config, counter=None):
        number_text = f"{counter}."
        number_x = rmc_config.xx(xpos) + NUMBERED2_OFFSET
        number_y = rmc_config.yy(ypos)
        output.write(
            f'\t\t\t<text x="{number_x}" y="{number_y}" class="numbered2" '
            f'xml:space="preserve">{number_text}</text>\n'
        )


# =============================================================================
# STYLE REGISTRY AND FACTORY
# =============================================================================

# Singleton instances for styles
_STYLE_INSTANCES: tp.Dict[si.ParagraphStyle, ParagraphStyleConfig] = {
    si.ParagraphStyle.PLAIN: PlainStyleConfig(),
    si.ParagraphStyle.BOLD: BoldStyleConfig(),
    si.ParagraphStyle.HEADING: HeadingStyleConfig(),
    si.ParagraphStyle.BULLET: Bullet1StyleConfig(),
    si.ParagraphStyle.BULLET2: Bullet2StyleConfig(),
    si.ParagraphStyle.CHECKBOX: Checkbox1StyleConfig(is_checked=False),
    si.ParagraphStyle.CHECKBOX_CHECKED: Checkbox1StyleConfig(is_checked=True),
    si.ParagraphStyle.CHECKBOX2: Checkbox2StyleConfig(is_checked=False),
    si.ParagraphStyle.CHECKBOX2_CHECKED: Checkbox2StyleConfig(is_checked=True),
    si.ParagraphStyle.NUMBERED: Numbered1StyleConfig(),
    si.ParagraphStyle.NUMBERED2: Numbered2StyleConfig(),
}


def get_style_config(style: si.ParagraphStyle) -> ParagraphStyleConfig:
    """Get the style configuration for a paragraph style.

    :param style: ParagraphStyle enum value
    :return: Corresponding ParagraphStyleConfig instance
    :raises KeyError: If style is not recognized
    """
    if style in _STYLE_INSTANCES:
        return _STYLE_INSTANCES[style]
    raise KeyError(f"Unknown paragraph style: {style}")
