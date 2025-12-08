#!/usr/bin/env python3
import argparse
import csv
import os
from pathlib import Path

LETTER_WIDTH_IN = 11.0
LETTER_HEIGHT_IN = 8.5
MM_PER_IN = 25.4

PAGE_SIZES = {
    "letter": (LETTER_WIDTH_IN * MM_PER_IN, LETTER_HEIGHT_IN * MM_PER_IN),
    "a4": (297.0, 210.0),  # A4 landscape in mm (width x height)
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate SVG name tags from a CSV file."
    )
    parser.add_argument(
        "csv_file",
        help="Input CSV file. Column 1 = desk number, Column 2 = name.",
    )
    parser.add_argument(
        "--tag-width-mm",
        type=float,
        default=203.0,
        help="Width of the tag content area in mm (default: 203).",
    )
    parser.add_argument(
        "--tag-height-mm",
        type=float,
        default=41.0,
        help="Height of the tag content area in mm (default: 41).",
    )
    parser.add_argument(
        "--border-margin-mm",
        type=float,
        default=1.0,
        help=(
            "Margin outside the tag for the light gray cut border, in mm "
            "(default: 1)."
        ),
    )
    parser.add_argument(
        "--name-font",
        default="Arial",
        help="Font family for the name line (default: Arial).",
    )
    parser.add_argument(
        "--desk-font",
        default="Arial",
        help="Font family for the desk number line (default: Arial).",
    )
    parser.add_argument(
        "--name-font-size",
        type=float,
        default=18.0,
        help="Font size for the name text (default: 18).",
    )
    parser.add_argument(
        "--desk-font-size",
        type=float,
        default=9.0,
        help="Font size for the desk number text (default: 9).",
    )
    parser.add_argument(
        "--name-y-factor",
        type=float,
        default=0.5,
        help=(
            "Vertical position of the name text within the tag height, "
            "0=top, 1=bottom (default: 0.5)."
        ),
    )
    parser.add_argument(
        "--desk-y-factor",
        type=float,
        default=0.82,
        help=(
            "Vertical position of the desk text within the tag height, "
            "0=top, 1=bottom (default: 0.82)."
        ),
    )
    parser.add_argument(
        "--text-x-offset-mm",
        type=float,
        default=20.0,
        help=(
            "Horizontal offset in mm from the LEFT edge of the tag content "
            "area for both text lines (default: 20)."
        ),
    )
    parser.add_argument(
        "--page-size",
        choices=["letter", "a4"],
        default="letter",
        help="Page size in landscape orientation (default: letter).",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to place generated SVG files (default: output).",
    )
    return parser.parse_args()


def read_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                continue
            desk = row[0].strip()
            name = row[1].strip()
            if not desk and not name:
                continue
            rows.append((desk, name))
    return rows


def generate_svg_page(
    entries,
    page_width_mm,
    page_height_mm,
    tag_width_mm,
    tag_height_mm,
    border_margin_mm,
    name_font,
    desk_font,
    name_font_size,
    desk_font_size,
    name_y_factor,
    desk_y_factor,
    text_x_offset_mm,
):
    """
    entries: list of (desk, name), length 1..3
    Returns SVG string.
    """

    # We draw using a viewBox in mm coordinates
    tag_total_height = tag_height_mm + 2 * border_margin_mm

    # Even vertical spacing: 4 gaps (top, between 1-2, between 2-3, bottom)
    gaps = 4
    gap_mm = (page_height_mm - 3 * tag_total_height) / gaps

    # Content area: horizontally centered
    x_content_left = (page_width_mm - tag_width_mm) / 2.0

    # Text X position (left aligned)
    x_text = x_content_left + text_x_offset_mm

    svg_parts = []

    svg_header = f'''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg
  xmlns="http://www.w3.org/2000/svg"
  width="{page_width_mm}mm"
  height="{page_height_mm}mm"
  viewBox="0 0 {page_width_mm} {page_height_mm}">
  <rect x="0" y="0" width="{page_width_mm}" height="{page_width_mm}"
        fill="white" />'''
    # Oops, fix height in the rect:
    svg_header = f'''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg
  xmlns="http://www.w3.org/2000/svg"
  width="{page_width_mm}mm"
  height="{page_height_mm}mm"
  viewBox="0 0 {page_width_mm} {page_height_mm}">
  <rect x="0" y="0" width="{page_width_mm}" height="{page_height_mm}"
        fill="white" />'''
    svg_parts.append(svg_header)

    for idx in range(3):
        # Compute vertical position for each of the 3 slots,
        # even if we don't have an entry (so "empty" tags remain blank).
        y_content_top = gap_mm * (idx + 1) + tag_total_height * idx + border_margin_mm

        if idx < len(entries):
            desk, name = entries[idx]
        else:
            desk, name = None, None

        # Draw cut border outside the tag area
        border_x = x_content_left - border_margin_mm
        border_y = y_content_top - border_margin_mm
        border_width = tag_width_mm + 2 * border_margin_mm
        border_height = tag_height_mm + 2 * border_margin_mm

        svg_parts.append(
            f'''  <rect x="{border_x}" y="{border_y}"
        width="{border_width}" height="{border_height}"
        fill="none" stroke="#cccccc" stroke-width="0.2" />'''
        )

        if desk is None and name is None:
            continue  # leave blank tag

        # Text positions within the tag
        name_y = y_content_top + name_y_factor * tag_height_mm
        desk_y = y_content_top + desk_y_factor * tag_height_mm

        # Name text (left aligned)
        svg_parts.append(
            f'''  <text x="{x_text}" y="{name_y}"
        text-anchor="start"
        font-family="{name_font}"
        font-size="{name_font_size}"
        font-weight="bold"
        fill="black">{escape_xml(name)}</text>'''
        )

        # Desk text (left aligned)
        svg_parts.append(
            f'''  <text x="{x_text}" y="{desk_y}"
        text-anchor="start"
        font-family="{desk_font}"
        font-size="{desk_font_size}"
        fill="black">{escape_xml(desk)}</text>'''
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def escape_xml(text: str) -> str:
    """Minimal XML escaping for text content."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def main():
    args = parse_args()

    entries = read_csv(args.csv_file)
    if not entries:
        print("No valid rows found in CSV; nothing to do.")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pick page size (landscape)
    page_width_mm, page_height_mm = PAGE_SIZES[args.page_size]

    # Process in chunks of 3 per page
    for i in range(0, len(entries), 3):
        page_entries = entries[i : i + 3]
        first_desk = page_entries[0][0] if page_entries else f"page_{i//3+1}"

        svg_content = generate_svg_page(
            page_entries,
            page_width_mm,
            page_height_mm,
            args.tag_width_mm,
            args.tag_height_mm,
            args.border_margin_mm,
            args.name_font,
            args.desk_font,
            args.name_font_size,
            args.desk_font_size,
            args.name_y_factor,
            args.desk_y_factor,
            args.text_x_offset_mm,
        )

        filename = f"{first_desk}.svg"
        out_path = output_dir / filename
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(svg_content)
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
