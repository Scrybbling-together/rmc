"""SVG export functionality for reMarkable files.

This module provides functions to convert .rm files to SVG format.
"""

# Import device module for config access
from .device import (
    SvgRenderConfig,
    rmc_config,
)

# Import rendering module functions
from .rendering import (
    rm_to_svg,
    tree_to_svg,
    SVG_HEADER,
    draw_text,
    draw_group,
)

# Import layout module functions
from .layout import (
    build_anchor_pos,
    get_bounding_box,
)

__all__ = [
    'rm_to_svg',
    'tree_to_svg',
    'build_anchor_pos',
    'get_bounding_box',
    'SvgRenderConfig',
    'rmc_config',
    'SVG_HEADER',
    'draw_text',
    'draw_group',
]
