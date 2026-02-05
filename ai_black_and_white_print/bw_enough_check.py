import argparse
import ctypes
import sys
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageOps

from utils import load_input_image, copy_image_to_clipboard_windows, show_image_with_cv2, crop_to_content_square


def already_black_and_white_enough(input_path: str | None, output_path: str | None) -> bool:
    # Load and grayscale immediately
    img = load_input_image(input_path).convert("L")
    total_pixels = img.size[0] * img.size[1]

    # Autocontrast
    img = ImageOps.autocontrast(img)

    # Histogram (256 bins)
    hist = img.histogram()

    # Subtract baseline noise floor
    baseline = max(2, int(0.001 * total_pixels))
    hist = [max(0, h - baseline) for h in hist]

    # Define 10%–90% gray range
    low = int(0.10 * 255)
    high = int(0.90 * 255)

    # Check for non-zero bins in mid-tones
    for i in range(low, high + 1):
        if hist[i] > 0:
            print(f"Failed at {i} = {hist[i]}")
            return False  # NOT black & white enough

    # If we reach here, it's effectively binary already
    img = img.point(lambda p: 255 if p > 180 else 0)

    # Crop and square
    img = crop_to_content_square(img)

    # Resize to label constraints
    img = img.resize((150, 150), Image.LANCZOS)

    # Convert to pure black & white
    img = img.point(lambda p: 255 if p > 180 else 0)

    if output_path:
        img.save(output_path, format="PNG", dpi=(180, 180))
        print(f"Saved output image → {output_path}")
    else:
        copy_image_to_clipboard_windows(img)
        print("Saved output image to system clipboard.")
        show_image_with_cv2(img)

    return True, output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check if image is already black & white enough for label printing"
    )
    parser.add_argument(
        "input_image",
        nargs="?",
        default=None,
        help="Optional input image file. If omitted, clipboard image is used.",
    )
    parser.add_argument(
        "output_image",
        nargs="?",
        default=None,
        help="Optional output image file. If omitted, result is copied to clipboard and previewed.",
    )

    args = parser.parse_args()

    result, _ = already_black_and_white_enough(args.input_image, args.output_image)

    print(result)
    # Optional: use exit code for scripting
    # True  -> 0
    # False -> 1
    exit(0 if result else 1)


if __name__ == "__main__":
    main()
