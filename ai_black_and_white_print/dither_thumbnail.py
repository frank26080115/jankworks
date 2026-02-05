import argparse
import ctypes
import sys
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageGrab, ImageOps

from utils import load_input_image, copy_image_to_clipboard_windows, show_image_with_cv2, crop_to_content_square


def extract_outline(gray_img, threshold=180):
    """
    Produce a 1-bit image containing only the contour.
    """
    arr = np.array(gray_img)

    # Binary mask: object = True, background = False
    obj = arr < threshold

    outline = np.zeros_like(obj, dtype=np.uint8)

    # 4-connected edge detection
    outline[1:, :] |= obj[1:, :] & ~obj[:-1, :]
    outline[:-1, :] |= obj[:-1, :] & ~obj[1:, :]
    outline[:, 1:] |= obj[:, 1:] & ~obj[:, :-1]
    outline[:, :-1] |= obj[:, :-1] & ~obj[:, 1:]

    # Convert to PIL image (black lines on white)
    outline_img = Image.fromarray(255 - outline * 255).convert("1")
    return outline_img


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare image with outline and dithering")
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
    parser.add_argument(
        "--outline",
        action='store_true',
        help="Add an outline around the object",
    )
    args = parser.parse_args()

    input_path = args.input_image
    output_path = args.output_image

    dither_convert(input_path, output_path, args.outline)

def dither_convert(input_path, output_path, add_outline=True):

    # Load and grayscale
    img = load_input_image(input_path)
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img)

    # Crop to square
    img = crop_to_content_square(img)

    # Resize
    img = img.resize((150, 150), Image.LANCZOS)

    # Extract outline BEFORE dithering
    outline = extract_outline(img, threshold=255 - 8)

    # Dither interior
    dithered = img.convert("1")

    if add_outline:
        # Combine: outline always wins (black)
        combined = ImageChops.logical_and(dithered, outline)
    else:
        combined = dithered

    if output_path:
        combined.save(args.output_image)
        print(f"Saved: {args.output_image}")
    else:
        copy_image_to_clipboard_windows(combined.convert("L"))
        print("Saved result to system clipboard.")
        show_image_with_cv2(combined.convert("L"))

    return output_path


if __name__ == "__main__":
    main()