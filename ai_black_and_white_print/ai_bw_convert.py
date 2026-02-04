import argparse
import base64
from io import BytesIO
from PIL import Image, ImageOps
from openai import OpenAI

# Before starting, set the API keys
# PowerShell:
# setx OPENAI_API_KEY sk-xxxxxxxxxxxxxxxx
# verify using:
# echo $Env:OPENAI_API_KEY

client = OpenAI()

PROMPT = (
    "This image shows a hardware fastener. "
    "Convert it into a clean black-and-white technical line drawing "
    "suitable for a thermal label printer. "
    "Use thick black lines, no shading, no textures, white background. "
    "Emphasize shape and functional geometry. Patent-style illustration."
)

def crop_to_content_square(img: Image.Image) -> Image.Image:
    """
    Crop as much outer white space as possible, then pad to square.
    Assumes white background, black foreground.
    """
    # Invert so content becomes white for bbox detection
    inverted = ImageOps.invert(img)
    bbox = inverted.getbbox()

    if bbox:
        img = img.crop(bbox)

    # Pad to square
    w, h = img.size
    size = max(w, h)

    square = Image.new("L", (size, size), 255)
    square.paste(img, ((size - w) // 2, (size - h) // 2))

    return square

def image_to_line_art(input_path, output_path):
    # Open input image as FILE (required for MIME)
    with open(input_path, "rb") as image_file:
        result = client.images.edit(
            model="gpt-image-1",
            image=image_file,
            prompt=PROMPT,
            size="1024x1024",
        )

    # Decode returned image
    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)
    img = Image.open(BytesIO(image_bytes)).convert("L")

    # Contrast + binarize
    img = ImageOps.autocontrast(img)
    img = img.point(lambda p: 255 if p > 180 else 0)

    # NEW: crop to content and square it
    img = crop_to_content_square(img)

    # Resize to label constraints (≤150×150 px)
    img.thumbnail((150, 150), Image.LANCZOS)

    # Binarize again
    img = img.point(lambda p: 255 if p > 180 else 0)

    # Save with DPI metadata
    img.save(output_path, format="PNG", dpi=(180, 180))

    print(f"Saved label image → {output_path}")
    print(f"Final size: {img.size}px @ 180 DPI")

def main():
    parser = argparse.ArgumentParser(
        description="Convert a photo into semantic line art for label printing"
    )
    parser.add_argument("input_image", help="Input image file (PNG/JPEG)")
    parser.add_argument("output_image", help="Output PNG file")

    args = parser.parse_args()
    image_to_line_art(args.input_image, args.output_image)

if __name__ == "__main__":
    main()
