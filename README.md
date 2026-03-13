# svg_to_pdf / svg_to_fb2

Convert a directory of per-page SVG files into a single merged PDF or FB2 ebook.

Useful when you have a book or document that has been digitised as one SVG file
per page and you want to read it as a normal PDF or on an e-reader that supports
FB2 (PocketBook, FBReader, etc.).

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — manages all Python dependencies
  automatically; no manual `pip install` or virtualenv setup needed
- **macOS only:** the `cairo` system library via Homebrew:
  ```bash
  brew install cairo
  ```
  On Linux, install `libcairo2` with your package manager
  (`apt install libcairo2` / `dnf install cairo`).

## Scripts

### `svg_to_pdf.py` — convert to PDF

```bash
uv run svg_to_pdf.py <input_dir> [options]
```

| Argument | Description |
|---|---|
| `input_dir` | Directory containing the SVG page files (required) |
| `-o`, `--output OUTPUT_PDF` | Output PDF path. Defaults to `<input_dir_name>.pdf` in the current directory |
| `-p`, `--pattern GLOB` | Glob pattern for SVG filenames. Default: `page_*.svg` |

### `svg_to_fb2.py` — convert to FB2 ebook

```bash
uv run svg_to_fb2.py <input_dir> [options]
```

| Argument | Description |
|---|---|
| `input_dir` | Directory containing the SVG page files (required) |
| `-o`, `--output OUTPUT_FB2` | Output FB2 path. Defaults to `<input_dir_name>.fb2` in the current directory |
| `-p`, `--pattern GLOB` | Glob pattern for SVG filenames. Default: `page_*.svg` |
| `--dpi DPI` | Rasterisation resolution in DPI (default: 150). Higher = sharper but larger file |

## Examples

```bash
# PDF — output goes to ./mybook.pdf
uv run svg_to_pdf.py /path/to/mybook

# FB2 — output goes to ./mybook.fb2
uv run svg_to_fb2.py /path/to/mybook

# Explicit output path
uv run svg_to_pdf.py /path/to/mybook -o ~/Documents/mybook.pdf
uv run svg_to_fb2.py /path/to/mybook -o ~/Documents/mybook.fb2 --dpi 200

# Different filename convention (e.g. scan_001.svg, scan_002.svg, ...)
uv run svg_to_pdf.py /path/to/mybook -p "scan_*.svg"
uv run svg_to_fb2.py /path/to/mybook -p "scan_*.svg"
```

## How it works

Both scripts share common logic in `_svg_utils.py`:

1. All SVG files matching the pattern are collected from `input_dir` and
   sorted in natural order (so `page_2.svg` comes before `page_10.svg`).
2. Embedded raster images (PNG/JPEG data URIs) are pre-processed with
   [Pillow](https://python-pillow.org/) to normalise them to RGBA PNGs,
   working around a libcairo limitation with certain PNG encodings.

**PDF path** — each SVG is rendered to an in-memory PDF page by
[CairoSVG](https://cairosvg.org/), preserving all vector paths, text, and
fonts, then all pages are merged with [pypdf](https://pypdf.readthedocs.io/).

**FB2 path** — each SVG is rasterised to a PNG image by CairoSVG, then all
images are embedded as base64 binaries in a
[FictionBook 2.0](http://gribuser.ru/xml/fictionbook/index.html.en) XML
document. Each page becomes a `<section>` with a full-page `<image>`.

## Dependencies

Managed via [PEP 723](https://peps.python.org/pep-0723/) inline script
metadata — `uv run` installs them automatically into an isolated environment:

| Package | Used by |
|---|---|
| `cairosvg >= 2.7` | both |
| `pillow >= 10.0` | both |
| `pypdf >= 4.0` | `svg_to_pdf.py` only |

## License

MIT
