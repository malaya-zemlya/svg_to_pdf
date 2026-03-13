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
import io
import logging
import sys
from pathlib import Path

from _svg_utils import (
    collect_svg_files,
    ensure_cairo_env,
    preprocess_svg,
)

ensure_cairo_env()

import cairosvg  # noqa: E402 — must come after ensure_cairo_env() re-exec
import pypdf  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


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
