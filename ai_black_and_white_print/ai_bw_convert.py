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

def image_to_line_art(input_path, output_path):
    # Open input image as a FILE (important!)
    with open(input_path, "rb") as image_file:
        result = client.images.edit(
            model="gpt-image-1",
            image=image_file,  # <-- MUST be a file-like object
            prompt=PROMPT,
            size="1024x1024",
        )

    # Decode returned image
    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)
    img = Image.open(BytesIO(image_bytes)).convert("L")

    # Improve contrast and binarize
    img = ImageOps.autocontrast(img)
    img = img.point(lambda p: 255 if p > 180 else 0)

    # Resize to label constraints (≤150×150 px)
    img.thumbnail((150, 150), Image.LANCZOS)

    # Save with explicit DPI metadata
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
