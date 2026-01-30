import sys
import random
import string
from pathlib import Path
from io import BytesIO

import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from scipy.ndimage import rotate

from ocr import ocr_image_chunks, extract_receipt_signature

WHITE_THRESHOLD = 32


def generate_filename(img):
    """Placeholder for future parsing logic."""
    try:
        lines = ocr_image_chunks(img)
        #print(lines)
        s = extract_receipt_signature(lines)
        if s:
            return s
    except Exception as ex:
        print(f"OCR failed: {ex!r}")
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


def _white_fill_for_mode(img: Image.Image):
    """
    Return a white fillcolor appropriate for the image mode.
    """
    if img.mode == "L":
        return 255
    if img.mode == "RGB":
        return (255, 255, 255)
    if img.mode == "RGBA":
        return (255, 255, 255, 255)
    if img.mode == "LA":
        return (255, 255)
    # fallback: try max value per channel
    bands = img.getbands()
    return tuple(255 for _ in bands)


def estimate_skew_angle(pil_img, max_angle=5.0, step=0.25):
    """
    Estimate skew angle using projection-profile variance.
    Operates in grayscale regardless of input mode.
    """
    gray = np.array(pil_img.convert("L"))
    binary = gray < 128  # text = True

    best_angle = 0.0
    best_score = -1.0

    for angle in np.arange(-max_angle, max_angle + step, step):
        rotated = rotate(binary, angle, reshape=False, order=0)
        profile = np.sum(rotated, axis=1)
        score = np.var(profile)

        if score > best_score:
            best_score = score
            best_angle = angle

    return best_angle


def deskew(pil_img):
    """
    Deskew image while preserving color mode and using correct white fill.
    """
    angle = estimate_skew_angle(pil_img)
    fill = _white_fill_for_mode(pil_img)

    return pil_img.rotate(
        angle,
        expand=True,
        fillcolor=fill,
        resample=Image.BICUBIC
    )


def image_to_pdf_page(img: Image.Image) -> fitz.Document:
    """
    Convert a PIL Image into a single-page PDF using JPEG compression,
    enforcing a maximum pixel dimension while preserving physical size.
    """

    MAX_PX = 2000
    JPEG_QUALITY = 85

    # ---- Normalize image mode ----
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    orig_w, orig_h = img.size

    # ---- Scale down if needed ----
    scale = min(1.0, MAX_PX / max(orig_w, orig_h))
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)

    if scale < 1.0:
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # ---- Encode as JPEG ----
    img_bytes = BytesIO()
    img.save(
        img_bytes,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True,
        progressive=True,
    )
    img_bytes.seek(0)

    # ---- Create PDF ----
    doc = fitz.open()

    # Preserve physical size:
    # Assume original image pixels map 1:1 to points unless DPI known.
    # Scaling page to original size prevents visual shrink.
    page_width = orig_w
    page_height = orig_h

    page = doc.new_page(width=page_width, height=page_height)

    # Insert scaled image but stretch to original page size
    rect = fitz.Rect(0, 0, page_width, page_height)
    page.insert_image(rect, stream=img_bytes.read())

    return doc


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

        img = crop_non_white(img)

        img = deskew(img)

        filename = f"{i}_{generate_filename(img)}"
        out_pdf = output_dir / f"{filename}.pdf"

        doc = image_to_pdf_page(img)

        doc.save(out_pdf)
        doc.close()

        print(f"[{i+1}/{len(src)}] Saved {out_pdf.name}")

    src.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python split_receipts.py <input.pdf>")
        sys.exit(1)

    main(sys.argv[1])
