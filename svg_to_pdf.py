#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "cairosvg>=2.7",
#   "pypdf>=4.0",
#   "pillow>=10.0",
# ]
# ///
"""Convert a directory of per-page SVG files into a single merged PDF.

Usage:
    uv run svg_to_pdf.py <input_dir> [-o output.pdf] [-p "page_*.svg"]

Example:
    uv run svg_to_pdf.py /path/to/book
    uv run svg_to_pdf.py /path/to/book -o my_book.pdf
    uv run svg_to_pdf.py /path/to/book -p "chapter_*.svg"
"""

import argparse
import base64
import io
import logging
import os
import re
import sys
from pathlib import Path

# [AI] cairocffi loads libcairo via dlopen at import time.  DYLD_LIBRARY_PATH
# must be set *before* the Python interpreter starts, so it cannot be patched
# inside Python after the fact.  We detect a missing DYLD hint and re-exec
# with the correct env so the user never has to set it manually.
_HOMEBREW_CAIRO = Path("/opt/homebrew/opt/cairo/lib")
_DYLD_KEY = "DYLD_LIBRARY_PATH"
_REEXEC_SENTINEL = "_SVG_PDF_REEXECED"

if (
    _HOMEBREW_CAIRO.exists()
    and str(_HOMEBREW_CAIRO) not in os.environ.get(_DYLD_KEY, "")
    and not os.environ.get(_REEXEC_SENTINEL)
):
    current = os.environ.get(_DYLD_KEY, "")
    new_env = os.environ.copy()
    new_env[_DYLD_KEY] = (
        f"{_HOMEBREW_CAIRO}:{current}" if current else str(_HOMEBREW_CAIRO)
    )
    new_env[_REEXEC_SENTINEL] = "1"
    os.execve(sys.executable, [sys.executable] + sys.argv, new_env)

import cairosvg
import pypdf
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# [AI] Pattern matching base64-encoded data URIs for PNG or JPEG images inside
# SVG xlink:href / href attributes.  We need to normalise these before passing
# to cairosvg because some PNG encodings (e.g. certain interlacing or colour
# depth combinations) are not supported by the system libcairo.
_DATA_URI_RE = re.compile(
    r'(xlink:href|href)="data:image/(png|jpeg);base64,([A-Za-z0-9+/\s]+=*)"',
    re.IGNORECASE,
)


def _normalise_embedded_image(match: re.Match) -> str:
    """Re-encode a single embedded image as a cairo-safe PNG.

    Decodes the base64 payload with Pillow, converts to RGBA (which cairo
    handles reliably), and re-encodes as PNG.  Falls back to the original data
    if anything goes wrong so we don't silently drop content.

    Args:
        match: Regex match object from _DATA_URI_RE.

    Returns:
        Replacement string with the normalised data URI.
    """
    attr, mime, b64_data = match.group(1), match.group(2), match.group(3)
    raw_bytes = base64.b64decode(b64_data.replace("\n", "").replace(" ", "") + "==")

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        # [AI] Convert to RGBA so cairo always gets 4-channel 8-bit data.
        img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        new_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f'{attr}="data:image/png;base64,{new_b64}"'
    except Exception as exc:
        logger.warning("Could not normalise embedded image (%s), keeping original: %s", mime, exc)
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


def svg_file_to_pdf_bytes(svg_path: Path) -> bytes:
    """Render a single SVG file to PDF bytes using CairoSVG.

    Embedded PNG/JPEG images are normalised via Pillow before rendering to
    work around libcairo limitations with certain PNG encodings.

    Args:
        svg_path: Path to the SVG file.

    Returns:
        PDF content as bytes.

    Raises:
        OSError: If the file cannot be read.
        Exception: If CairoSVG cannot render the SVG.
    """
    raw = svg_path.read_bytes()
    normalised = preprocess_svg(svg_bytes=raw)
    return cairosvg.svg2pdf(bytestring=normalised)


def merge_pdf_pages(pdf_bytes_list: list[bytes]) -> bytes:
    """Merge a list of single-page PDF byte strings into one multi-page PDF.

    Args:
        pdf_bytes_list: List of PDF bytes, one per page.

    Returns:
        Merged PDF content as bytes.
    """
    writer = pypdf.PdfWriter()

    for page_bytes in pdf_bytes_list:
        reader = pypdf.PdfReader(io.BytesIO(page_bytes))
        for page in reader.pages:
            writer.add_page(page)

    output_buffer = io.BytesIO()
    writer.write(output_buffer)
    return output_buffer.getvalue()


def convert_svgs_to_pdf(
    input_dir: Path,
    output_path: Path,
    pattern: str = "page_*.svg",
) -> None:
    """Convert all SVG page files in a directory into a single merged PDF.

    Args:
        input_dir: Directory containing SVG page files.
        output_path: Destination path for the output PDF.
        pattern: Glob pattern to match SVG filenames (default: 'page_*.svg').
    """
    svg_files = collect_svg_files(input_dir=input_dir, pattern=pattern)
    total = len(svg_files)
    logger.info("Found %d SVG page(s) in '%s'", total, input_dir)

    pdf_pages: list[bytes] = []
    for i, svg_path in enumerate(svg_files, start=1):
        logger.info("Rendering page %d/%d: %s", i, total, svg_path.name)
        try:
            page_pdf = svg_file_to_pdf_bytes(svg_path=svg_path)
        except Exception as exc:
            logger.error("Failed to render '%s': %s", svg_path.name, exc)
            raise

        pdf_pages.append(page_pdf)

    logger.info("Merging %d pages into '%s' ...", total, output_path)
    merged = merge_pdf_pages(pdf_bytes_list=pdf_pages)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(merged)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Done. Written %.2f MB to '%s'", size_mb, output_path)


def build_default_output_path(input_dir: Path) -> Path:
    """Derive a default output PDF path from the input directory name.

    Args:
        input_dir: The source directory.

    Returns:
        Path like ./dirname.pdf in the current working directory.
    """
    return Path.cwd() / f"{input_dir.resolve().name}.pdf"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace with input_dir, output, and pattern attributes.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Convert a directory of per-page SVG files into a single merged PDF."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run svg_to_pdf.py /path/to/book\n"
            "  uv run svg_to_pdf.py /path/to/book -o my_book.pdf\n"
            "  uv run svg_to_pdf.py /path/to/book -p 'chapter_*.svg'\n"
        ),
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing the SVG page files.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        metavar="OUTPUT_PDF",
        help=(
            "Output PDF file path. Defaults to '<input_dir_name>.pdf' "
            "in the current directory."
        ),
    )
    parser.add_argument(
        "-p", "--pattern",
        default="page_*.svg",
        metavar="GLOB",
        help=(
            "Glob pattern for SVG filenames inside input_dir. "
            "Default: 'page_*.svg'."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Optional argument list for testing.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args(argv)

    input_dir: Path = args.input_dir
    output_path: Path = args.output or build_default_output_path(input_dir)
    pattern: str = args.pattern

    try:
        convert_svgs_to_pdf(
            input_dir=input_dir,
            output_path=output_path,
            pattern=pattern,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
