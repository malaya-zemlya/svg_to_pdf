#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "cairosvg>=2.7",
#   "pillow>=10.0",
# ]
# ///
"""Convert a directory of per-page SVG files into a single FB2 ebook.

Each SVG page is rasterised to a PNG image and embedded as a full-page
image section inside a FictionBook 2.0 (FB2) XML file.  This format is
widely supported by Russian e-readers (PocketBook, FBReader, etc.) and
preserves all visual formatting from the original scans.

Usage:
    uv run svg_to_fb2.py <input_dir> [-o output.fb2] [-p "page_*.svg"]
    uv run svg_to_fb2.py <input_dir> [-o output.fb2] [--dpi 150]

Example:
    uv run svg_to_fb2.py /path/to/book
    uv run svg_to_fb2.py /path/to/book -o ~/Documents/book.fb2
    uv run svg_to_fb2.py /path/to/book -p "scan_*.svg" --dpi 200
"""

import argparse
import base64
import io
import logging
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from _svg_utils import (
    collect_svg_files,
    ensure_cairo_env,
    preprocess_svg,
)

ensure_cairo_env()

import cairosvg  # noqa: E402 — must come after ensure_cairo_env() re-exec

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# FB2 namespace constants
_FB2_NS = "http://www.gribuser.ru/xml/fictionbook/2.0"
_XLINK_NS = "http://www.w3.org/1999/xlink"


def svg_file_to_png_bytes(svg_path: Path, dpi: int) -> bytes:
    """Rasterise a single SVG file to PNG bytes using CairoSVG.

    Embedded PNG/JPEG images are normalised via Pillow before rendering to
    work around libcairo limitations with certain PNG encodings.

    Args:
        svg_path: Path to the SVG file.
        dpi: Output resolution in dots per inch.

    Returns:
        PNG image content as bytes.

    Raises:
        OSError: If the file cannot be read.
        Exception: If CairoSVG cannot render the SVG.
    """
    raw = svg_path.read_bytes()
    normalised = preprocess_svg(svg_bytes=raw)
    return cairosvg.svg2png(bytestring=normalised, dpi=dpi)


def build_fb2(
    page_png_list: list[tuple[str, bytes]],
    title: str,
) -> bytes:
    """Assemble a FictionBook 2.0 XML document from a list of PNG pages.

    Each page becomes a <section> containing a single full-page <image>,
    with the PNG data stored as base64 in a <binary> element.

    Args:
        page_png_list: List of (image_id, png_bytes) tuples, one per page.
        title: Book title used in the FB2 <title-info> metadata.

    Returns:
        Encoded UTF-8 bytes of the complete FB2 XML document.
    """
    # [AI] register_namespace makes ElementTree emit xmlns declarations
    # automatically.  Do NOT also pass them as attrib= — that causes
    # duplicate attribute errors in strict XML parsers and some FB2 readers.
    ET.register_namespace("", _FB2_NS)
    ET.register_namespace("l", _XLINK_NS)

    root = ET.Element(f"{{{_FB2_NS}}}FictionBook")

    # --- <description> ---
    description = ET.SubElement(root, f"{{{_FB2_NS}}}description")
    title_info = ET.SubElement(description, f"{{{_FB2_NS}}}title-info")
    genre_el = ET.SubElement(title_info, f"{{{_FB2_NS}}}genre")
    genre_el.text = "nonfiction"
    author_el = ET.SubElement(title_info, f"{{{_FB2_NS}}}author")
    nickname_el = ET.SubElement(author_el, f"{{{_FB2_NS}}}nickname")
    nickname_el.text = "unknown"
    book_title_el = ET.SubElement(title_info, f"{{{_FB2_NS}}}book-title")
    book_title_el.text = title
    lang_el = ET.SubElement(title_info, f"{{{_FB2_NS}}}lang")
    lang_el.text = "en"

    doc_info = ET.SubElement(description, f"{{{_FB2_NS}}}document-info")
    doc_author = ET.SubElement(doc_info, f"{{{_FB2_NS}}}author")
    doc_nickname = ET.SubElement(doc_author, f"{{{_FB2_NS}}}nickname")
    doc_nickname.text = "svg_to_fb2"
    doc_id = ET.SubElement(doc_info, f"{{{_FB2_NS}}}id")
    doc_id.text = str(uuid.uuid4())
    doc_version = ET.SubElement(doc_info, f"{{{_FB2_NS}}}version")
    doc_version.text = "1.0"

    # --- <body> ---
    body = ET.SubElement(root, f"{{{_FB2_NS}}}body")

    # [AI] Put all pages in one section rather than one section per page.
    # Some FB2 readers (FBReader, PocketBook) render each <section> as a
    # separate TOC/chapter entry with a bullet, making image-only books look
    # like an empty list.  A single section avoids that.
    section = ET.SubElement(body, f"{{{_FB2_NS}}}section")
    for image_id, _ in page_png_list:
        p_el = ET.SubElement(section, f"{{{_FB2_NS}}}p")
        img_el = ET.SubElement(p_el, f"{{{_FB2_NS}}}image")
        img_el.set(f"{{{_XLINK_NS}}}href", f"#{image_id}")

    # --- <binary> elements ---
    for image_id, png_bytes in page_png_list:
        binary = ET.SubElement(root, f"{{{_FB2_NS}}}binary")
        binary.set("id", image_id)
        binary.set("content-type", "image/png")
        binary.text = base64.b64encode(png_bytes).decode("ascii")

    tree = ET.ElementTree(root)
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def convert_svgs_to_fb2(
    input_dir: Path,
    output_path: Path,
    pattern: str = "page_*.svg",
    dpi: int = 150,
) -> None:
    """Convert all SVG page files in a directory into a single FB2 ebook.

    Args:
        input_dir: Directory containing SVG page files.
        output_path: Destination path for the output FB2 file.
        pattern: Glob pattern to match SVG filenames (default: 'page_*.svg').
        dpi: Rasterisation resolution in DPI (default: 150).
    """
    svg_files = collect_svg_files(input_dir=input_dir, pattern=pattern)
    total = len(svg_files)
    logger.info("Found %d SVG page(s) in '%s'", total, input_dir)

    title = input_dir.resolve().name

    page_png_list: list[tuple[str, bytes]] = []
    for i, svg_path in enumerate(svg_files, start=1):
        logger.info("Rasterising page %d/%d: %s", i, total, svg_path.name)
        try:
            png_bytes = svg_file_to_png_bytes(svg_path=svg_path, dpi=dpi)
        except Exception as exc:
            logger.error("Failed to rasterise '%s': %s", svg_path.name, exc)
            raise

        # [AI] Use a stable image ID derived from position so the FB2 XML is
        # deterministic across runs.
        image_id = f"page_{i:04d}.png"
        page_png_list.append((image_id, png_bytes))

    logger.info("Assembling FB2 document '%s' ...", output_path)
    fb2_bytes = build_fb2(page_png_list=page_png_list, title=title)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(fb2_bytes)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Done. Written %.2f MB to '%s'", size_mb, output_path)


def build_default_output_path(input_dir: Path) -> Path:
    """Derive a default output FB2 path from the input directory name.

    Args:
        input_dir: The source directory.

    Returns:
        Path like ./dirname.fb2 in the current working directory.
    """
    return Path.cwd() / f"{input_dir.resolve().name}.fb2"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace with input_dir, output, pattern, and dpi attributes.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Convert a directory of per-page SVG files into a single FB2 ebook."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run svg_to_fb2.py /path/to/book\n"
            "  uv run svg_to_fb2.py /path/to/book -o my_book.fb2\n"
            "  uv run svg_to_fb2.py /path/to/book -p 'scan_*.svg' --dpi 200\n"
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
        metavar="OUTPUT_FB2",
        help=(
            "Output FB2 file path. Defaults to '<input_dir_name>.fb2' "
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
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        metavar="DPI",
        help=(
            "Rasterisation resolution for PNG images (default: 150). "
            "Higher values give sharper images but larger files."
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
    dpi: int = args.dpi

    try:
        convert_svgs_to_fb2(
            input_dir=input_dir,
            output_path=output_path,
            pattern=pattern,
            dpi=dpi,
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
