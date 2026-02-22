"""Device profiles and coordinate scaling for reMarkable devices."""

import logging
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)

@dataclass
class SvgRenderConfig:
    """Configuration for SVG rendering - device dimensions and coordinate scaling."""

    # Device configuration, this is the RMPP screen size
    screen_width = 1620
    screen_height = 2160
    screen_dpi = 229

    # Computed scaling factors
    scale: float = field(init=False)
    page_width_pt: float = field(init=False)
    page_height_pt: float = field(init=False)
    x_shift: float = field(init=False)

    def __init__(self):
        """Compute derived values after initialization."""
        self.scale = 72.0 / self.screen_dpi
        self.page_width_pt = self.screen_width * self.scale
        self.page_height_pt = self.screen_height * self.scale
        self.x_shift = self.page_width_pt // 2

    def xx(self, screen_units: float) -> float:
        """Convert screen units to PDF points (x-axis)."""
        return screen_units * self.scale

    def yy(self, screen_units: float) -> float:
        """Convert screen units to PDF points (y-axis)."""
        return screen_units * self.scale


# Global render config instance
rmc_config = SvgRenderConfig()
