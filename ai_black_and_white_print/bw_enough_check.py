import argparse
from PIL import Image, ImageOps


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


def already_black_and_white_enough(input_path, output_path) -> bool:
    # Load and grayscale immediately
    img = Image.open(input_path).convert("L")
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
    # Convert to pure black & white
    img = img.point(lambda p: 255 if p > 180 else 0)

    # Crop and square
    img = crop_to_content_square(img)

    # Resize to label constraints
    img = img.resize((150, 150), Image.LANCZOS)

    # Convert to pure black & white
    img = img.point(lambda p: 255 if p > 180 else 0)

    # Save output
    img.save(output_path, format="PNG", dpi=(180, 180))

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Check if image is already black & white enough for label printing"
    )
    parser.add_argument("input_image", help="Input image file")
    parser.add_argument("output_image", help="Output image file")

    args = parser.parse_args()

    result = already_black_and_white_enough(args.input_image, args.output_image)

    print(result)
    # Optional: use exit code for scripting
    # True  -> 0
    # False -> 1
    exit(0 if result else 1)


if __name__ == "__main__":
    main()
