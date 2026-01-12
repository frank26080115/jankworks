import sys
import random
import string
from pathlib import Path
from io import BytesIO

import fitz  # PyMuPDF
import numpy as np
from PIL import Image


WHITE_THRESHOLD = 32


def generate_filename(img):
    """Placeholder for future parsing logic."""
    return ''.join(random.choices('0123456789ABCDEF', k=8))


def crop_non_white_simple(pil_img):
    """
    Crop away areas that are 'white'.
    A pixel is white if all RGB channels >= WHITE_THRESHOLD.
    """
    img = np.array(pil_img)

    if img.ndim == 3:
        mask = np.any(img < WHITE_THRESHOLD, axis=2)
    else:  # grayscale fallback
        mask = img < WHITE_THRESHOLD

    if not mask.any():
        return pil_img  # nothing to crop

    coords = np.argwhere(mask)
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0) + 1

    return pil_img.crop((x0, y0, x1, y1))


def crop_non_white(pil_img):
    RADIUS = 5
    MIN_NEIGHBORS = 5
    PAD = 5

    img = np.array(pil_img)
    h, w = img.shape[:2]

    # --- base black pixel mask ---
    if img.ndim == 3:
        black = np.any(img < WHITE_THRESHOLD, axis=2)
    else:
        black = img < WHITE_THRESHOLD

    if not black.any():
        return pil_img

    # --- detect dust pixels ---
    dust = np.zeros_like(black, dtype=bool)

    for y in range(h):
        y0 = max(0, y - RADIUS)
        y1 = min(h, y + RADIUS + 1)

        for x in range(w):
            if not black[y, x]:
                continue

            x0 = max(0, x - RADIUS)
            x1 = min(w, x + RADIUS + 1)

            # Count black pixels in neighborhood (excluding self)
            count = np.count_nonzero(black[y0:y1, x0:x1]) - 1

            if count < MIN_NEIGHBORS:
                dust[y, x] = True

    # --- remove dust ---
    cleaned = black & ~dust

    if not cleaned.any():
        return pil_img

    # --- compute bounding box ---
    ys, xs = np.where(cleaned)
    top, bottom = ys.min(), ys.max()
    left, right = xs.min(), xs.max()

    # --- apply padding ---
    top = max(0, top - PAD)
    left = max(0, left - PAD)
    bottom = min(h, bottom + PAD)
    right = min(w, right + PAD)

    return pil_img.crop((left, top, right + 1, bottom + 1))


def main(pdf_path):
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    output_dir = pdf_path.with_name(pdf_path.stem + "_split")
    output_dir.mkdir(exist_ok=True)

    src = fitz.open(pdf_path)

    for i, page in enumerate(src):
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        cropped = crop_non_white(img)

        filename = generate_filename(cropped)
        out_pdf = output_dir / f"{filename}.pdf"

        # Convert PIL image → PNG bytes in memory
        img_bytes = BytesIO()
        cropped.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        doc = fitz.open()
        rect = fitz.Rect(0, 0, cropped.width, cropped.height)
        page_out = doc.new_page(width=rect.width, height=rect.height)

        page_out.insert_image(rect, stream=img_bytes.read())

        doc.save(out_pdf)
        doc.close()

        print(f"[{i+1}/{len(src)}] Saved {out_pdf.name}")

    src.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python split_receipts.py <input.pdf>")
        sys.exit(1)

    main(sys.argv[1])
