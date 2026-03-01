"""Device profiles and coordinate scaling for reMarkable devices."""

import logging
from dataclasses import dataclass, field

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


def detect_device_from_pdf_size(width_pt: float, height_pt: float) -> str:
    """
    Detect the most likely device based on PDF page dimensions.

    :param width_pt: PDF page width in points
    :param height_pt: PDF page height in points
    :return: Device name ('RM2' or 'RMPP')
    """
    best_device = "RMPP"
    best_score = float('inf')

    for device, profile in DEVICE_PROFILES.items():
        scale = 72.0 / profile["dpi"]
        expected_w = profile["width"] * scale
        expected_h = profile["height"] * scale

        # Calculate how close this device's dimensions are to the PDF
        # Use ratio comparison to handle different aspect ratios
        w_ratio = width_pt / expected_w
        h_ratio = height_pt / expected_h

        # Score based on how close ratios are to 1.0
        score = abs(1 - w_ratio) + abs(1 - h_ratio)

        if score < best_score:
            best_score = score
            best_device = device

    _logger.debug(f"Detected device {best_device} for PDF size {width_pt}x{height_pt} pt (score={best_score:.3f})")
    return best_device


def set_device_from_pdf_size(width_pt: float, height_pt: float) -> str:
    """
    Detect and set the device profile based on PDF page dimensions.

    :param width_pt: PDF page width in points
    :param height_pt: PDF page height in points
    :return: Device name that was set
    """
    device = detect_device_from_pdf_size(width_pt, height_pt)
    set_device(device)
    return device


def set_custom_dimensions(width_screen: int, height_screen: int, dpi: int = 226) -> None:
    """Set custom screen dimensions for non-standard PDF sizes.

    This allows generating SVGs that match arbitrary PDF dimensions rather than
    being constrained to fixed device profiles (RM2 or RMPP).

    :param width_screen: Screen width in pixels
    :param height_screen: Screen height in pixels
    :param dpi: Screen DPI (default 226, same as RM2)
    """
    rmc_config.screen_width = width_screen
    rmc_config.screen_height = height_screen
    rmc_config.screen_dpi = dpi
    rmc_config.device_name = "CUSTOM"
    rmc_config._recompute_derived_fields()
    _logger.debug(f"Set custom dimensions: {rmc_config.screen_width}x{rmc_config.screen_height} @ {rmc_config.screen_dpi} DPI")


def set_dimensions_for_pdf(width_pt: float, height_pt: float, dpi: int = 226) -> None:
    """Set dimensions to match a PDF page size.

    Converts PDF points to screen coordinates and sets custom dimensions.
    This ensures the generated SVG matches the PDF exactly.

    :param width_pt: PDF page width in points
    :param height_pt: PDF page height in points
    :param dpi: DPI to use for conversion (default 226, same as RM2)
    """
    rmc_config.update_from_pdf_size(width_pt, height_pt, dpi)
