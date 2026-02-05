import argparse
from PIL import Image, ImageOps, ImageChops
import numpy as np


def crop_to_content_square_(img, white_threshold=245):
    """
    Crop image to the tightest square around non-white content.
    white_threshold: 0–255, higher = more aggressive whitespace removal
    """
    # Convert to numpy for analysis
    arr = np.array(img)

    # Identify non-white pixels
    mask = arr < white_threshold

    if not mask.any():
        # Image is basically empty; return centered square
        w, h = img.size
        size = min(w, h)
        left = (w - size) // 2
        top = (h - size) // 2
        return img.crop((left, top, left + size, top + size))

    ys, xs = np.where(mask)
    top, bottom = ys.min(), ys.max()
    left, right = xs.min(), xs.max()

    # Bounding box of content
    content_w = right - left + 1
    content_h = bottom - top + 1
    size = max(content_w, content_h)

    # Center square around content
    cx = (left + right) // 2
    cy = (top + bottom) // 2

    half = size // 2
    new_left = max(0, cx - half)
    new_top = max(0, cy - half)
    new_right = new_left + size
    new_bottom = new_top + size

    # Clamp to image bounds
    w, h = img.size
    if new_right > w:
        new_left = w - size
        new_right = w
    if new_bottom > h:
        new_top = h - size
        new_bottom = h

    return img.crop((new_left, new_top, new_right, new_bottom))


def crop_to_content_square(img: Image.Image) -> Image.Image:
    """
    Crop as much outer white space as possible, then pad to square.
    Assumes white background, black foreground.
    """
    inverted = ImageOps.invert(img)
    bbox = inverted.getbbox()

    if bbox:
        img = img.crop(bbox)

    w, h = img.size
    size = max(w, h)

    square = Image.new("L", (size, size), 255)
    square.paste(img, ((size - w) // 2, (size - h) // 2))

    return square


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


def main():
    parser = argparse.ArgumentParser(description="Prepare image with outline and dithering")
    parser.add_argument("input_image", help="Input image file")
    parser.add_argument("output_image", help="Output image file")
    args = parser.parse_args()

    # Load and grayscale
    img = Image.open(args.input_image)
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img)

    # Crop to square
    img = crop_to_content_square(img)

    # Resize
    img = img.resize((150, 150), Image.LANCZOS)

    # Extract outline BEFORE dithering
    outline = extract_outline(img, threshold= 255 - 8)

    # Dither interior
    dithered = img.convert("1")

    # Combine: outline always wins (black)
    combined = ImageChops.logical_and(dithered, outline)

    # Save
    combined.save(args.output_image)
    print(f"Saved: {args.output_image}")


if __name__ == "__main__":
    main()