import argparse
import os
import sys
import re
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from dateutil import parser as dateparser
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color
from reportlab.pdfbase.pdfmetrics import stringWidth
from io import BytesIO
import fitz  # PyMuPDF


def parse_money(value):
    """Parse money into Decimal, stripping symbols."""
    try:
        cleaned = re.sub(r"[^\d.\-]", "", value)
        return Decimal(cleaned)
    except Exception:
        raise ValueError(f"Invalid money value: {value}")


def parse_date_flexible(value):
    try:
        return dateparser.parse(value)
    except Exception:
        print(f"WARNING: Failed to parse date: {value}", file=sys.stderr)
        return value


def sanitize_supplier(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def is_money_related(key):
    k = key.lower()
    return (
        "amount" in k
        or "exchange rate" in k
        or "currency" in k
    )


def resolve_pdf_path(pdf_value, pdf_dir):
    p = Path(pdf_value)

    if p.is_absolute() and p.exists():
        return str(p.resolve())

    candidate = Path(pdf_dir) / pdf_value
    if candidate.exists():
        return str(candidate.resolve())

    raise FileNotFoundError(f"Missing PDF file: {pdf_value}")


def process_currency(data):
    """
    Normalize money fields.
    Returns (usd_amount_decimal)
    """
    usd_amount = None
    foreign_amount = None
    foreign_currency = None
    exchange_rate = None

    for key in list(data.keys()):
        k = key.lower()

        if k == "amount":
            usd_amount = parse_money(data[key])
            data["currency"] = "USD"

        elif k == "amount usd":
            usd_amount = parse_money(data[key])
            data["currency"] = "USD"

        elif k.startswith("amount ") and k != "amount usd":
            currency_code = key.split(" ", 1)[1].strip().upper()
            foreign_currency = currency_code
            foreign_amount = parse_money(data[key])
            data["currency"] = currency_code

        elif k == "exchange rate":
            exchange_rate = parse_money(data[key])

    # Foreign currency logic
    if foreign_currency:
        if usd_amount and not exchange_rate:
            # derive exchange rate
            exchange_rate = (usd_amount / foreign_amount).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            data["exchange rate"] = str(exchange_rate)

        elif foreign_amount and exchange_rate and not usd_amount:
            usd_amount = (foreign_amount * exchange_rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            data["amount USD"] = str(usd_amount)

        elif not ((usd_amount and exchange_rate) or (usd_amount and foreign_amount)):
            raise Exception(
                "Foreign currency requires exchange rate or amount USD."
            )

        usd_amount = usd_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if usd_amount:
        usd_amount = usd_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return usd_amount


def build_text_lines(data, usd_amount):
    non_money = []
    money = []

    for key, value in data.items():
        if is_money_related(key):
            money.append((key, value))
        else:
            non_money.append((key, value))

    lines = []

    # First batch (non-money)
    for k, v in non_money:
        if isinstance(v, datetime):
            v = v.strftime("%Y-%m-%d")
        lines.append(f"{k}: {v}")

    currency = data.get("currency", "USD").upper()

    # Second batch (money)
    if currency == "USD":
        if usd_amount:
            lines.append(f"amount (USD): {usd_amount:.2f}")
    else:
        for k, v in money:
            if k.lower().startswith("amount ") and "usd" not in k.lower():
                lines.append(f"{k}: {Decimal(v):.2f}")

        lines.append(f"currency: {currency}")

        if "exchange rate" in data:
            lines.append(
                f"exchange rate: {Decimal(data['exchange rate']):.4f}"
            )

        lines.append(f"amount (USD): {usd_amount:.2f}")

    return lines


def pad_and_rebuild_first_page_(src_page, text_lines, font_size=8):
    """
    Render first page to JPG, pad top, rebuild new page.
    """
    # Estimate text height
    line_height = font_size + 2
    text_height = len(text_lines) * line_height
    padding = text_height + 10  # +10 white pixels

    # Render original page to image
    pix = src_page.get_pixmap()
    original_width = pix.width
    original_height = pix.height

    # Create new blank page
    new_width = original_width
    new_height = original_height + padding

    doc = fitz.open()
    new_page = doc.new_page(width=new_width, height=new_height)

    # Insert white background
    new_page.draw_rect(
        fitz.Rect(0, 0, new_width, new_height),
        color=(1, 1, 1),
        fill=(1, 1, 1),
    )

    # Convert original page to JPG
    img_bytes = pix.tobytes("jpg")

    # Insert original page image shifted down
    img_rect = fitz.Rect(
        0,
        padding,
        original_width,
        padding + original_height,
    )
    new_page.insert_image(img_rect, stream=img_bytes)

    return doc, new_page, padding


def pad_and_flatten_first_page(src_page, text_lines, font_size=8, dpi=150):
    """
    Fully flatten first page to JPG, pad top, and return rebuilt page.
    """

    # Estimate text height
    line_height = font_size + 2
    text_height = len(text_lines) * line_height
    padding = text_height + 10  # extra white space

    # Render original page to raster
    pix = src_page.get_pixmap(dpi=dpi)

    # Convert to JPG in-memory
    jpg_bytes = pix.tobytes("jpg")

    # Compute new page dimensions
    original_width = pix.width
    original_height = pix.height

    new_width = original_width
    new_height = original_height + padding

    # Create temporary document
    temp_doc = fitz.open()
    new_page = temp_doc.new_page(width=new_width, height=new_height)

    # Fill white background
    new_page.draw_rect(
        fitz.Rect(0, 0, new_width, new_height),
        color=(1, 1, 1),
        fill=(1, 1, 1),
    )

    # Insert flattened JPG shifted down
    img_rect = fitz.Rect(
        0,
        padding,
        original_width,
        padding + original_height,
    )

    new_page.insert_image(img_rect, stream=jpg_bytes)

    return temp_doc, new_page, padding


def commit(data, pdf_list, output_dir):
    if not data and not pdf_list:
        return

    usd_amount = process_currency(data)

    # ----- filename generation -----
    date_value = None
    supplier_value = None

    for key, value in data.items():
        if not date_value and "date" in key.lower():
            if isinstance(value, datetime):
                date_value = value
            else:
                try:
                    date_value = dateparser.parse(str(value))
                except Exception:
                    pass

        if not supplier_value and "supplier" in key.lower():
            supplier_value = str(value)

    if not date_value:
        raise Exception("No date found for filename.")

    if not supplier_value:
        raise Exception("No supplier found for filename.")

    date_str = date_value.strftime("%Y%m%d")
    supplier_str = sanitize_supplier(supplier_value)

    if not usd_amount:
        raise Exception("USD amount missing.")

    cents = int((usd_amount * 100).to_integral_value())
    filename = f"{date_str}_{supplier_str}_{cents}.pdf"
    output_path = Path(output_dir) / filename

    # ----- build text lines -----
    text_lines = build_text_lines(data, usd_amount)

    # ----- start building output doc -----
    final_doc = fitz.open()

    for i, pdf_file in enumerate(pdf_list):
        src_doc = fitz.open(pdf_file)

        for j in range(len(src_doc)):
            src_page = src_doc[j]

            # First page special handling
            if i == 0 and j == 0:
                temp_doc, new_page, padding = pad_and_flatten_first_page(
                    src_page, text_lines
                )

                # Insert red text AFTER flattening
                y = 10
                for line in text_lines:
                    new_page.insert_text(
                        fitz.Point(10, y),
                        line,
                        fontsize=8,
                        color=(0, 0, 0),  # (0,0,0) for black, (1,0,0) for red
                    )
                    y += 10

                final_doc.insert_pdf(temp_doc)
                temp_doc.close()

            else:
                final_doc.insert_pdf(src_doc, from_page=j, to_page=j)

        src_doc.close()

    final_doc.save(output_path)
    final_doc.close()

    print(f"Saved: {output_path}")

    data.clear()
    pdf_list.clear()


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("pdf_dir")
    parser.add_argument("--output_dir", default=None)

    args = parser.parse_args()

    input_file = Path(args.input_file)
    pdf_dir = Path(args.pdf_dir)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = pdf_dir / Path(
            f"output_{datetime.now().strftime('%Y%m%d%H%M')}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    data = OrderedDict()
    pdf_list = []

    with open(input_file, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if line.startswith("-"):
                commit(data, pdf_list, output_dir)
                continue

            match = re.match(r"([^:=]+)\s*[:=]\s*(.+)", line)
            if not match:
                continue

            key = match.group(1).strip()
            value = match.group(2).strip()

            if key.lower() == "pdf":
                resolved = resolve_pdf_path(value, pdf_dir)
                pdf_list.append(resolved)
                continue

            if "date" in key.lower():
                parsed = parse_date_flexible(value)
                data[key] = parsed
            else:
                data[key] = value

    # Final commit at EOF
    commit(data, pdf_list, output_dir)


if __name__ == "__main__":
    main()
