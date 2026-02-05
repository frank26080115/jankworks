import argparse
import os
from PIL import Image, ImageOps, ImageChops
import sys


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


def invert_and_cleanup(img):
    """
    Invert image, then remove enclosed black regions
    not touching white pixels (background cleanup).
    """
    img = img.convert("L")
    pixels = img.load()
    w, h = img.size

    # Invert
    for y in range(h):
        for x in range(w):
            pixels[x, y] = 255 - pixels[x, y]

    # Remove black pixels fully surrounded by black
    to_white = []

    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if pixels[x, y] == 0:
                neighbors = [
                    pixels[x - 1, y], pixels[x + 1, y],
                    pixels[x, y - 1], pixels[x, y + 1],
                ]
                if all(n == 0 for n in neighbors):
                    to_white.append((x, y))

    for x, y in to_white:
        pixels[x, y] = 255

    return img


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
