"""Convert blocks to pdf file.

Code originally from https://github.com/lschwetlick/maxio through
https://github.com/chemag/maxio .
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from cairosvg import svg2pdf

from .svg import rm_to_svg

_logger = logging.getLogger(__name__)

# Chrome/Chromium command names to search in PATH
CHROME_COMMANDS = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
]

# Common Chrome/Chromium installation paths
CHROME_PATHS = [
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "~/Applications/Chromium.app/Contents/MacOS/Chromium",
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/lib/chromium/chromium",
    "/usr/lib/chromium-browser/chromium-browser",
    "/snap/bin/chromium",
    "/opt/google/chrome/google-chrome",
    "/opt/google/chrome/chrome",
    # Flatpak
    "/var/lib/flatpak/exports/bin/com.google.Chrome",
    "/var/lib/flatpak/exports/bin/org.chromium.Chromium",
]


def find_chrome(chrome_loc: Optional[str] = None) -> Optional[str]:
    """
    Find Chrome/Chromium binary.

    :param chrome_loc: Optional explicit path to Chrome binary
    :return: Path to Chrome binary, or None if not found
    :raises FileNotFoundError: If chrome_loc is specified but doesn't exist
    """
    if chrome_loc:
        path = Path(chrome_loc).expanduser()
        if path.is_file():
            _logger.info(f"Using specified Chrome location: {path}")
            return str(path)
        raise FileNotFoundError(f"Chrome not found at specified location: {chrome_loc}")

    # Check PATH first
    for cmd in CHROME_COMMANDS:
        path = shutil.which(cmd)
        if path:
            _logger.info(f"Found Chrome in PATH: {path}")
            return path

    # Check common installation paths
    for path_str in CHROME_PATHS:
        path = Path(path_str).expanduser()
        if path.is_file():
            _logger.info(f"Found Chrome at: {path}")
            return str(path)

    return None


def chrome_svg_to_pdf(svg_path: str, pdf_path: str, chrome_loc: Optional[str] = None):
    """
    Convert SVG to PDF using headless Chrome.

    :param svg_path: Path to input SVG file
    :param pdf_path: Path to output PDF file
    :param chrome_loc: Optional explicit path to Chrome binary
    :raises RuntimeError: If Chrome is not found
    """
    chrome = find_chrome(chrome_loc)
    if not chrome:
        raise RuntimeError(
            "Chrome/Chromium not found. Install it, specify --chrome-loc, or use --no-chrome"
        )

    # Create HTML wrapper that sizes the page to match the SVG
    # NOTE: Deliberately omitting <!DOCTYPE html> - with DOCTYPE, Chrome renders 2 pages instead of 1
    html_content = f'''<html>
<head>
    <style>body {{ margin: 0; }}</style>
    <script>
    window.onload = function() {{
        const el = document.getElementById('targetsvg');
        const rect = el.getBoundingClientRect();
        const style = document.createElement('style');
        style.innerHTML = `@page {{margin: 0; size: ${{rect.width}}px ${{rect.height}}px}}`;
        document.head.appendChild(style);
    }};
    </script>
</head>
<body>
    <img id="targetsvg" src="{svg_path}">
</body>
</html>'''

    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = Path(tmpdir) / "temp.html"
        html_path.write_text(html_content)

        subprocess.run([
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            str(html_path)
        ], check=True)


def svg_to_pdf(svg_file, pdf_file, use_chrome: bool = True, chrome_loc: Optional[str] = None):
    """
    Convert SVG to PDF.

    :param svg_file: Input SVG file object (StringIO with .getvalue())
    :param pdf_file: Output PDF file object (with .name attribute)
    :param use_chrome: If True, use Chrome; if False, use Cairo
    :param chrome_loc: Optional explicit path to Chrome binary
    """
    if use_chrome:
        svg_str = svg_file.getvalue()
        with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False) as temp_svg:
            temp_svg.write(svg_str)
            temp_svg.flush()
            temp_svg_path = temp_svg.name
        try:
            chrome_svg_to_pdf(temp_svg_path, pdf_file.name, chrome_loc)
        finally:
            Path(temp_svg_path).unlink(missing_ok=True)
    else:
        # Use Cairo
        svg2pdf(
            bytestring=svg_file.getvalue().encode('utf-8'),
            write_to=pdf_file.name,
            dpi=72
        )


def rm_to_pdf(rm_path, pdf_path, use_chrome: bool = True, chrome_loc: Optional[str] = None):
    """
    Convert .rm file to PDF.

    :param rm_path: Path to .rm file
    :param pdf_path: Path to output PDF file
    :param use_chrome: If True, use Chrome; if False, use Cairo
    :param chrome_loc: Optional explicit path to Chrome binary
    """
    with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False) as f_temp:
        rm_to_svg(rm_path, f_temp.name)
        temp_svg_path = f_temp.name

    try:
        if use_chrome:
            chrome_svg_to_pdf(temp_svg_path, pdf_path, chrome_loc)
        else:
            # Use Cairo
            svg2pdf(url=temp_svg_path, write_to=pdf_path, dpi=72)
    finally:
        Path(temp_svg_path).unlink(missing_ok=True)
