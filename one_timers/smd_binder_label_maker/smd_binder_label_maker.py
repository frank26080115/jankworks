#!/usr/bin/env python3
"""
Generate vertical SMD page labels as SVG (172mm x 24mm), 12 evenly spaced vertical texts,
then compile all SVGs (sorted by filename) into a multipage PDF.

Usage:
  python make_smd_labels.py --input path/to/txts --output path/to/out

Notes:
- Keeps rotate(-90) as requested.
- Parameter names are compatible with the existing main() call: margin_top_mm and use_textlength_fit.
- Smaller default font size; top alignment fixed via dominant-baseline.
"""

import argparse
from pathlib import Path
import sys

# Optional deps for PDF
try:
    import cairosvg  # type: ignore
except Exception:
    cairosvg = None

try:
    from pypdf import PdfWriter, PdfReader  # type: ignore
except Exception:
    PdfWriter = None
    PdfReader = None


def mm(val: float) -> str:
    return f"{val}mm"


def read_12_lines(txt_path: Path) -> list[str]:
    lines = []
    with txt_path.open("r", encoding="utf-8") as f:
        for idx, raw in enumerate(f):
            if idx >= 12:
                break
            lines.append(raw.rstrip("\r\n"))
    if len(lines) < 12:
        lines.extend([""] * (12 - len(lines)))
    return lines


def build_svg(
    lines,
    width_mm: float = 177.8, # wanted is 172, but prints smaller, scaled up a bit. print as 7.01 inch wide with 0.08 inch feed
    height_mm: float = 23.876,
    slots: int = 12,
    margin_bottom_mm: float = 5.0,        # "left" from text POV == top after rotate(-90)
    margin_left_mm: float = 0.0,
    x_offset_mm: float = 0.0,          # slide all columns left(-) / right(+)
    font_family: str = "Arial, Helvetica, sans-serif",
    base_font_size_mm: float = 2.2,    # realistic default for 24mm tape
    use_textlength_fit: bool = True    # True: spacing-only fit; False: clip (no stretching)
) -> str:
    """
    Build an SVG with 12 vertical labels rotated -90 degrees, starting at the top margin
    (from the rotated text's perspective), evenly spaced across 172mm width.
    """

    # Column centers (evenly spaced) + global offset
    slot_centers = [width_mm * (i + 0.5) / slots + x_offset_mm for i in range(slots)]

    # Vertical runway for text after rotation
    runway = max(1.0, height_mm - margin_bottom_mm)

    # Escape helper
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width_mm}mm" height="{height_mm}mm" '
        f'viewBox="0 0 {width_mm} {height_mm}">'
    )

    parts.append(
        f'<g font-family="{font_family}" font-size="{base_font_size_mm}mm" fill="#000" stroke="none">'
    )

    for i in range(slots):
        text = esc(lines[i] if i < len(lines) else "")
        x = slot_centers[i] + margin_left_mm
        y = height_mm - margin_bottom_mm

        if use_textlength_fit:
            # Keep within runway using spacing-only adjustment (no glyph squish)
            parts.append(
                f'<text x="{x}" y="{y}" '
                f'textLength="{runway}" lengthAdjust="spacing" '
                f'text-anchor="start" dominant-baseline="text-before-edge" '
                f'transform="rotate(-90 {x} {y})">{text}</text>'
            )
        else:
            # Clip approach: no stretching at all
            clip_id = f"clip{i}"
            parts.append(
                f'<clipPath id="{clip_id}">'
                f'  <rect x="{x - 6}" y="{margin_top_mm}" width="12" height="{runway}" />'
                f'</clipPath>'
            )
            parts.append(
                f'<g clip-path="url(#{clip_id})">'
                f'  <text x="{x}" y="{y}" '
                f'      text-anchor="start" dominant-baseline="text-before-edge" '
                f'      transform="rotate(-90 {x} {y})">{text}</text>'
                f'</g>'
            )

    parts.append('</g></svg>')
    return "\n".join(parts)


def write_svg(out_dir: Path, stem: str, svg: str) -> Path:
    path = out_dir / f"{stem}.svg"
    path.write_text(svg, encoding="utf-8")
    return path


def svg_to_pdf(svg_path: Path, pdf_path: Path) -> None:
    if cairosvg is None:
        raise RuntimeError("cairosvg not installed")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(url=str(svg_path), write_to=str(pdf_path))


def merge_pdfs(pdfs: list[Path], out_path: Path) -> None:
    if PdfWriter is None or PdfReader is None:
        raise RuntimeError("pypdf not installed")
    writer = PdfWriter()
    for p in pdfs:
        r = PdfReader(str(p))
        for page in r.pages:
            writer.add_page(page)
    with out_path.open("wb") as f:
        writer.write(f)


def main():
    ap = argparse.ArgumentParser(description="Make 172mm×24mm vertical labels (12 columns) from .txt files.")
    ap.add_argument("--input", "-i", required=True, help="Input directory with .txt files (12 lines each)")
    ap.add_argument("--output", "-o", required=True, help="Output directory for SVG / PDF")
    ap.add_argument("--no-fit", action="store_true",
                    help="Disable spacing fit; use clipping instead (no stretching).")
    ap.add_argument("--font-mm", type=float, default=1.6, help="Font size in mm (default: 2.2)")
    ap.add_argument("--bottom-mm", type=float, default=3.0, help="Bottom margin (from screen perspective) in mm (default: 5)")
    ap.add_argument("--left-mm", type=float, default=0, help="Left margin (from screen perspective) in mm (default: 5)")
    args = ap.parse_args()

    in_dir = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not in_dir.exists() or not in_dir.is_dir():
        print(f"ERROR: input is not a directory: {in_dir}", file=sys.stderr)
        sys.exit(1)

    txts = sorted(p for p in in_dir.iterdir() if p.suffix.lower() == ".txt" and p.is_file())
    if not txts:
        print("No .txt files found.", file=sys.stderr)
        sys.exit(0)

    svgs: list[Path] = []
    for t in txts:
        lines = read_12_lines(t)
        svg = build_svg(
            lines,
            base_font_size_mm=args.font_mm,
            margin_bottom_mm=args.bottom_mm,
            margin_left_mm=args.left_mm,
            use_textlength_fit=not args.no_fit,
        )
        svgs.append(write_svg(out_dir, t.stem, svg))

    print(f"✔ Generated {len(svgs)} SVGs in {out_dir}")

    # Per-page PDFs
    perpage = []
    if cairosvg is not None:
        for s in svgs:
            pdfp = s.with_suffix(".pdf")
            svg_to_pdf(s, pdfp)
            perpage.append(pdfp)
        print(f"✔ Converted {len(perpage)} SVGs to PDFs")
    else:
        print("ℹ cairosvg not installed; skipping per-page PDFs (pip install cairosvg)")

    # Combined multipage
    if perpage and PdfWriter is not None:
        merged = out_dir / "labels.pdf"
        merge_pdfs(sorted(perpage, key=lambda p: p.stem), merged)
        print(f"📄 Combined PDF: {merged}")
    elif perpage:
        print("ℹ pypdf not installed; skipping combined PDF (pip install pypdf)")


if __name__ == "__main__":
    main()
