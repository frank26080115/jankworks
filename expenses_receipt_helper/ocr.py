from typing import List
import numpy as np
from PIL import Image, ImageOps
import pytesseract


WHITE_THRESHOLD = 128
MIN_CHUNK_HEIGHT = 8


def _is_white_row(row: np.ndarray) -> bool:
    """
    Returns True if the entire row is white (> threshold)
    """
    return np.all(row > WHITE_THRESHOLD)


def split_image_into_chunks(img: Image.Image) -> List[Image.Image]:
    """
    Split an image into vertical chunks using full-width white rows.
    """
    # Convert to grayscale for thresholding
    gray = img.convert("L")
    arr = np.array(gray)

    height, width = arr.shape
    chunks = []

    start_y = 0

    for y in range(height):
        if _is_white_row(arr[y]):
            chunk_height = y - start_y
            if chunk_height >= MIN_CHUNK_HEIGHT:
                chunk = img.crop((0, start_y, width, y))
                # Pad with 2px white border
                chunk = ImageOps.expand(chunk, border=2, fill="white")
                chunks.append(chunk)
            start_y = y + 1

    # Handle final chunk
    if height - start_y >= MIN_CHUNK_HEIGHT:
        chunk = img.crop((0, start_y, width, height))
        chunks.append(chunk)

    return chunks


def ocr_image_chunks(img: Image.Image) -> List[str]:
    """
    Split the image into chunks and OCR each chunk.
    Returns a list of trimmed, non-empty strings.
    """
    pytesseract.pytesseract.tesseract_cmd = (
        r"C:\ProgramFiles\Tesseract-OCR\tesseract.exe"
    )

    chunks = split_image_into_chunks(img)
    results = []

    for chunk in chunks:
        text = pytesseract.image_to_string(chunk)
        text = text.replace("\n", " ")
        text = text.strip()
        if text:
            results.append(text)

    return results


import re
from datetime import datetime
from typing import List


def extract_receipt_signature(lines: List[str]) -> str:
    # ------------------ regexes ------------------

    DATE_REGEXES = [
        # DD/MM/YYYY, D-M-YYYY, etc
        re.compile(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})\b"),
        # YYYY/MM/DD
        re.compile(r"\b(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})\b"),
    ]

    TIME_RE = re.compile(
        r"\b(\d{1,2})\s*:\s*(\d{2})\s*(am|pm)?\b",
        re.IGNORECASE,
    )

    MONEY_RE = re.compile(r"\b\d[^0-9]{0,2}\.\d{2}\b")

    TOTAL_RE = re.compile(r"^\s*(total|sum)\s*(.*)$", re.IGNORECASE)

    # ------------------ helpers ------------------

    def sanitize(s: str) -> str:
        return "".join(c if c.isalnum() else "x" for c in s)

    def norm_year(y: str) -> int:
        y = int(y)
        return y + 2000 if y < 100 else y

    def normalize_date(parts):
        try:
            d, m, y = parts
            y = norm_year(y)
            dt = datetime(y, int(m), int(d))
            return dt.strftime("%Y%m%d")
        except Exception:
            return None

    def normalize_time(h, m, ampm):
        h = int(h)
        m = int(m)
        if ampm:
            ampm = ampm.lower()
            if ampm == "pm" and h != 12:
                h += 12
            if ampm == "am" and h == 12:
                h = 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}{m:02d}"
        return None

    # ------------------ extraction ------------------

    dates = set()
    times = set()
    money_candidates = []

    # --- dates & times ---
    for line in lines:
        for rx in DATE_REGEXES:
            for m in rx.findall(line):
                if len(m[0]) == 4:
                    # YYYY/MM/DD
                    d = normalize_date((m[2], m[1], m[0]))
                else:
                    # DD/MM/YYYY
                    d = normalize_date(m)
                if d:
                    dates.add(d)

        for m in TIME_RE.findall(line):
            t = normalize_time(*m)
            if t:
                times.add(t)

    # --- money with total/sum priority ---
    forced_money = []

    for i, line in enumerate(lines):
        m = TOTAL_RE.match(line)
        if m:
            tail = m.group(2)
            found = MONEY_RE.findall(tail)
            if found:
                forced_money.extend(found)
            elif i + 1 < len(lines):
                forced_money.extend(MONEY_RE.findall(lines[i + 1]))

    if forced_money:
        money_candidates = forced_money
    else:
        for line in lines:
            money_candidates.extend(MONEY_RE.findall(line))

        if money_candidates:
            max_len = max(len(s) for s in money_candidates)
            money_candidates = [
                s for s in money_candidates if len(s) == max_len
            ]

    # ------------------ formatting ------------------

    out = []

    for d in sorted(dates):
        out.append(f"D{d}")

    for t in sorted(times):
        out.append(f"T{t}")

    for m in money_candidates:
        cents = sanitize(m.replace(".", ""))
        out.append(f"M{cents}")

    return "_".join(out)
