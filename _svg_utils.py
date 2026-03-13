"""Shared utilities for SVG conversion scripts.

Provides SVG file collection, natural sorting, and embedded-image
normalisation used by both svg_to_pdf.py and svg_to_fb2.py.
"""

import base64
import io
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# [AI] cairocffi loads libcairo via dlopen at import time.  DYLD_LIBRARY_PATH
# must be set *before* the Python interpreter starts, so it cannot be patched
# inside Python after the fact.  We detect a missing DYLD hint and re-exec
# with the correct env so the user never has to set it manually.
_HOMEBREW_CAIRO = Path("/opt/homebrew/opt/cairo/lib")
_DYLD_KEY = "DYLD_LIBRARY_PATH"
_REEXEC_SENTINEL = "_SVG_CONV_REEXECED"


def ensure_cairo_env(sentinel: str = _REEXEC_SENTINEL) -> None:
    """Re-exec the current process with DYLD_LIBRARY_PATH set if needed.

    On macOS with Homebrew, libcairo lives outside the default dyld search
    path.  Because DYLD_LIBRARY_PATH must be present before dlopen runs at
    interpreter startup, we re-exec ourselves with the correct env the first
    time we are called.

    Args:
        sentinel: Environment variable name used to detect we already re-execed,
                  preventing an infinite loop.
    """
    if (
        _HOMEBREW_CAIRO.exists()
        and str(_HOMEBREW_CAIRO) not in os.environ.get(_DYLD_KEY, "")
        and not os.environ.get(sentinel)
    ):
        current = os.environ.get(_DYLD_KEY, "")
        new_env = os.environ.copy()
        new_env[_DYLD_KEY] = (
            f"{_HOMEBREW_CAIRO}:{current}" if current else str(_HOMEBREW_CAIRO)
        )
        new_env[sentinel] = "1"
        os.execve(sys.executable, [sys.executable] + sys.argv, new_env)


# [AI] Pattern matching base64-encoded data URIs for PNG or JPEG images inside
# SVG xlink:href / href attributes.  We normalise these before passing to
# cairosvg because some PNG encodings are not supported by the system libcairo.
_DATA_URI_RE = re.compile(
    r'(xlink:href|href)="data:image/(png|jpeg);base64,([A-Za-z0-9+/\s]+=*)"',
    re.IGNORECASE,
)


def _normalise_embedded_image(match: re.Match) -> str:
    """Re-encode a single embedded image as a cairo-safe RGBA PNG.

    Decodes the base64 payload with Pillow, converts to RGBA (which cairo
    handles reliably), and re-encodes as PNG.  Falls back to the original
    data on any error so content is never silently dropped.

    Args:
        match: Regex match object from _DATA_URI_RE.

    Returns:
        Replacement string with the normalised data URI.
    """
    from PIL import Image  # imported here to avoid top-level dep at module load

    attr, mime, b64_data = match.group(1), match.group(2), match.group(3)
    raw_bytes = base64.b64decode(b64_data.replace("\n", "").replace(" ", "") + "==")

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        new_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f'{attr}="data:image/png;base64,{new_b64}"'
    except Exception as exc:
        logger.warning(
            "Could not normalise embedded image (%s), keeping original: %s",
            mime,
            exc,
        )
        return match.group(0)


def preprocess_svg(svg_bytes: bytes) -> bytes:
    """Normalise all embedded raster images in SVG bytes for cairo compatibility.

    Args:
        svg_bytes: Raw SVG file content.

    Returns:
        SVG content with embedded images re-encoded as cairo-safe RGBA PNGs.
    """
    svg_text = svg_bytes.decode("utf-8", errors="replace")
    normalised = _DATA_URI_RE.sub(_normalise_embedded_image, svg_text)
    return normalised.encode("utf-8")


def natural_sort_key(path: Path) -> list:
    """Return a sort key that orders filenames with embedded numbers naturally.

    For example: page_2.svg < page_10.svg (numeric, not lexicographic order).
    """
    parts = re.split(r"(\d+)", path.name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def collect_svg_files(input_dir: Path, pattern: str) -> list[Path]:
    """Glob and naturally sort SVG files in input_dir matching pattern.

    Args:
        input_dir: Directory to search for SVG files.
        pattern: Glob pattern for SVG filenames.

    Returns:
        Sorted list of matching SVG file paths.

    Raises:
        FileNotFoundError: If input_dir does not exist.
        NotADirectoryError: If input_dir is not a directory.
        ValueError: If no SVG files match the pattern.
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {input_dir}")

    files = sorted(input_dir.glob(pattern), key=natural_sort_key)

    if not files:
        raise ValueError(
            f"No SVG files found in '{input_dir}' matching pattern '{pattern}'"
        )

    return files
