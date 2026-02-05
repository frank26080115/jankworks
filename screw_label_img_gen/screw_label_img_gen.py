import argparse
import os
from PIL import Image, ImageDraw, ImageOps, ImageChops
import sys
import numpy as np
from collections import deque


TEMPLATES_DIR = "templates"
OUTPUT_DIR = "output"


def warn(msg):
    print(f"WARNING: {msg}", file=sys.stderr)


def parse_templates(code):
    """
    Greedy left-to-right parser.
    Tries 1, then 2, then 3 letters.
    Returns list of template filenames (full paths).
    """
    remaining = code
    found = []

    while remaining:
        matched = False

        for n in (1, 2, 3):
            if len(remaining) < n:
                continue

            candidate = remaining[:n]
            path = os.path.join(TEMPLATES_DIR, f"{candidate}.png")

            if os.path.isfile(path):
                found.append(path)
                remaining = remaining[n:]
                matched = True
                break

        if not matched:
            warn(f"Could not match template at: '{remaining}'")
            break

    return found, remaining


def extract_contour_mask(img, threshold=180):
    """
    Contour extraction via RGB flood fill:
    1. Convert to RGB
    2. Threshold to white / black
    3. Flood fill background from (0,0) with RED
    4. Everything NOT red -> white
    5. Everything NOT white -> black
    """
    # Step 1: grayscale
    gray = img.convert("L")

    # Step 2: threshold (white background, black object)
    bw = gray.point(lambda p: 255 if p >= threshold else 0)

    # Step 3: convert to RGB
    rgb = bw.convert("RGB")

    # Step 4: flood fill background with RED from (0,0)
    ImageDraw.floodfill(rgb, (0, 0), (255, 0, 0))

    arr = np.array(rgb)

    # Step 5: everything NOT red -> white
    is_red = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 0)
    arr[~is_red] = [255, 255, 255]

    # Step 6: everything NOT white -> black
    is_white = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 255) & (arr[:, :, 2] == 255)
    arr[~is_white] = [0, 0, 0]

    # Step 7: convert to binary mask
    mask = arr[:, :, 0] != 0

    return mask


def invert_and_cleanup(img, threshold=180):
    img = img.convert("L")
    arr = np.array(img)

    # Step 1: contour mask from original image
    contour_mask = extract_contour_mask(img, threshold)
    #return Image.fromarray(contour_mask)

    # Step 2: invert
    arr = 255 - arr

    h, w = arr.shape
    to_white = []

    # Step 3: cleanup background
    for y in range(1, h - 1):
        for x in range(1, w - 1):

            # Only consider black pixels
            if arr[y, x] != 0:
                continue

            # Never touch contour pixels
            if contour_mask[y, x]:
                continue

            # If touching white, it's border-adjacent → keep
            neighbors = [
                arr[y - 1, x], arr[y + 1, x],
                arr[y, x - 1], arr[y, x + 1],
            ]

            if any(n == 255 for n in neighbors):
                continue

            # True background → erase
            to_white.append((y, x))

    for y, x in to_white:
        arr[y, x] = 255

    return Image.fromarray(arr)


def main():
    parser = argparse.ArgumentParser(description="Generate screw graphic from parameter string")
    parser.add_argument("code", help="Parameter string, e.g. HBDTLSPBO")
    args = parser.parse_args()

    code = args.code.upper()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Handle black oxide suffix
    black_oxide = False
    if code.endswith("BO"):
        black_oxide = True
        code = code[:-2]

    if not code:
        warn("No parameters left after removing BO")
        return

    # Parse templates
    templates, leftover = parse_templates(code)

    if leftover:
        warn(f"Unparsed remainder: '{leftover}'")

    if not templates:
        warn("No templates matched at all")
        return

    # Load images
    images = [
        Image.open(p).convert("1")
        for p in templates
    ]

    # Determine canvas size
    max_w = max(img.width for img in images)
    max_h = max(img.height for img in images)

    # Composite
    canvas = Image.new("1", (max_w, max_h), 1)  # 1 = white

    for img in images:
        canvas = ImageChops.logical_and(canvas, img)

    # Black oxide processing
    if black_oxide:
        canvas = invert_and_cleanup(canvas)

    # Save output
    output_path = os.path.join(OUTPUT_DIR, f"{args.code}.png")
    canvas.save(output_path)

    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
