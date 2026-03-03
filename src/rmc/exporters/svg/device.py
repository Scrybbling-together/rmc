"""Device profiles and coordinate scaling for reMarkable devices."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)

# Device profiles with screen dimensions
DEVICE_PROFILES = {
    "RM2": {"width": 1404, "height": 1872, "dpi": 226},
    "RMPP": {"width": 1620, "height": 2160, "dpi": 229},
}


@dataclass
class SvgRenderConfig:
    """Configuration for SVG rendering - device dimensions and coordinate scaling."""

    # Primary device configuration
    screen_width: int          # Device screen width in pixels
    screen_height: int         # Device screen height in pixels
    screen_dpi: int            # Device DPI (dots per inch)
    device_name: str = "CUSTOM"  # "RM2", "RMPP", or "CUSTOM"

    # Optional external fonts directory (checked before bundled fonts)
    fonts_dir: Optional[Path] = None

    # Computed scaling factors (auto-calculated in __post_init__)
    scale: float = field(init=False)           # 72.0 / DPI
    page_width_pt: float = field(init=False)   # screen_width * scale
    page_height_pt: float = field(init=False)  # screen_height * scale
    x_shift: float = field(init=False)         # page_width_pt // 2

    def __post_init__(self):
        """Compute derived values after initialization."""
        self._recompute_derived_fields()

    def _recompute_derived_fields(self) -> None:
        """Recompute scale, page_width_pt, page_height_pt, x_shift after config changes."""
        self.scale = 72.0 / self.screen_dpi
        self.page_width_pt = self.screen_width * self.scale
        self.page_height_pt = self.screen_height * self.scale
        self.x_shift = self.page_width_pt // 2

    @classmethod
    def from_device_profile(cls, device: str) -> "SvgRenderConfig":
        """Create config from device profile name ('RM2' or 'RMPP')."""
        config = cls.__new__(cls)
        config.update_from_device_profile(device)
        return config

    @classmethod
    def from_pdf_size(cls, width_pt: float, height_pt: float, dpi: int = 226) -> "SvgRenderConfig":
        """Create config from PDF dimensions in points."""
        config = cls.__new__(cls)
        config.update_from_pdf_size(width_pt, height_pt, dpi)
        return config

    def update_from_device_profile(self, device: str) -> None:
        """Update this config in-place from a device profile."""
        if device not in DEVICE_PROFILES:
            raise ValueError(f"Unknown device: {device}. Valid options: {list(DEVICE_PROFILES.keys())}")
        profile = DEVICE_PROFILES[device]
        self.screen_width = profile["width"]
        self.screen_height = profile["height"]
        self.screen_dpi = profile["dpi"]
        self.device_name = device
        self._recompute_derived_fields()

    def update_from_pdf_size(self, width_pt: float, height_pt: float, dpi: int = 226) -> None:
        """Update this config in-place from PDF dimensions."""
        scale = 72.0 / dpi
        self.screen_width = int(round(width_pt / scale))
        self.screen_height = int(round(height_pt / scale))
        self.screen_dpi = dpi
        self.device_name = "CUSTOM"
        self._recompute_derived_fields()

    def xx(self, screen_units: float) -> float:
        """Convert screen units to PDF points (x-axis)."""
        return screen_units * self.scale

    def yy(self, screen_units: float) -> float:
        """Convert screen units to PDF points (y-axis)."""
        return screen_units * self.scale


# Global render config instance
# Default to RMPP
rmc_config = SvgRenderConfig.from_device_profile("RMPP")


def set_device(device: str) -> None:
    """Set the current device profile. Valid values: 'RM2', 'RMPP'"""
    rmc_config.update_from_device_profile(device)
    _logger.debug(f"Set device to {device}: {rmc_config.screen_width}x{rmc_config.screen_height} @ {rmc_config.screen_dpi} DPI")


def get_device() -> str:
    """Get the current device profile name."""
    return rmc_config.device_name


def set_dimensions_for_pdf(width_pt: float, height_pt: float, dpi: int = 226) -> None:
    """Set dimensions to match a PDF page size.

    Converts PDF points to screen coordinates and sets custom dimensions.
    This ensures the generated SVG matches the PDF exactly.

    :param width_pt: PDF page width in points
    :param height_pt: PDF page height in points
    :param dpi: DPI to use for conversion (default 226, same as RM2)
    """
    rmc_config.update_from_pdf_size(width_pt, height_pt, dpi)


def set_fonts_dir(path: Path) -> None:
    """Set an external fonts directory to check before bundled fonts.

    :param path: Path to directory containing font files
    """
    rmc_config.fonts_dir = Path(path)
    _logger.debug(f"Set external fonts directory: {rmc_config.fonts_dir}")
