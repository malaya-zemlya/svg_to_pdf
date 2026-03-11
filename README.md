# svg_to_pdf

Convert a directory of per-page SVG files into a single merged PDF.

Useful when you have a book or document that has been digitised as one SVG file
per page and you want to read it as a normal PDF.

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

## Usage

```bash
uv run svg_to_pdf.py <input_dir> [options]
```

### Arguments

| Argument | Description |
|---|---|
| `input_dir` | Directory containing the SVG page files (required) |
| `-o`, `--output OUTPUT_PDF` | Output PDF path. Defaults to `<input_dir_name>.pdf` in the current directory |
| `-p`, `--pattern GLOB` | Glob pattern for SVG filenames. Default: `page_*.svg` |

### Examples

```bash
# Simplest — output goes to ./mybook.pdf
uv run svg_to_pdf.py /path/to/mybook

# Explicit output path
uv run svg_to_pdf.py /path/to/mybook -o ~/Documents/mybook.pdf

# Different filename convention (e.g. scan_001.svg, scan_002.svg, ...)
uv run svg_to_pdf.py /path/to/mybook -p "scan_*.svg"
```

## How it works

1. All SVG files matching the pattern are collected from `input_dir` and
   sorted in natural order (so `page_2.svg` comes before `page_10.svg`).
2. Each SVG is rendered to an in-memory PDF page by
   [CairoSVG](https://cairosvg.org/), which uses the Cairo graphics library to
   render vector paths directly to PDF — preserving text, fonts, and layout
   exactly.
3. Embedded raster images (PNG/JPEG data URIs) are pre-processed with
   [Pillow](https://python-pillow.org/) to normalise them to RGBA PNGs,
   working around a libcairo limitation with certain PNG encodings.
4. All pages are merged into a single PDF with
   [pypdf](https://pypdf.readthedocs.io/).

## Dependencies

Managed via [PEP 723](https://peps.python.org/pep-0723/) inline script
metadata — `uv run` installs them automatically into an isolated environment:

- `cairosvg >= 2.7`
- `pypdf >= 4.0`
- `pillow >= 10.0`

## License

MIT
