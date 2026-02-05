import argparse
import base64
import sys
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageOps
from openai import OpenAI

from utils import load_input_image, copy_image_to_clipboard_windows, show_image_with_cv2, crop_to_content_square

# Before starting, set the API keys
# PowerShell:
# setx OPENAI_API_KEY sk-xxxxxxxxxxxxxxxx
# verify using:
# echo $Env:OPENAI_API_KEY

client = OpenAI()

PROMPT = (
    "This image shows a piece of hardware."
    "Convert it into a clean black-and-white technical line drawing "
    "suitable for a thermal label printer. "
    "Use thick black lines, no shading, no textures, white background. "
    "Emphasize shape and functional geometry. Patent-style illustration."
)


def image_to_openai_upload(image: Image.Image) -> BytesIO:
    """Encode a PIL image into an in-memory PNG stream for OpenAI image editing."""
    upload_stream = BytesIO()
    image.convert("RGBA").save(upload_stream, format="PNG")
    upload_stream.seek(0)

    # The API uses the stream name to infer MIME type in some clients.
    upload_stream.name = "clipboard_input.png"
    return upload_stream


def image_to_line_art(input_path: str | None, output_path: str | None, additonal_prompt: str | None) -> None:
    source_image = load_input_image(input_path)
    upload_stream = image_to_openai_upload(source_image)

    p = PROMPT
    if additonal_prompt:
        p += "\n\nAdditional Hint: " + additonal_prompt

    result = client.images.edit(
        model="gpt-image-1",
        image=upload_stream,
        prompt=p,
        size="1024x1024",
    )

    # Decode returned image
    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)
    img = Image.open(BytesIO(image_bytes)).convert("L")

    # Contrast + binarize
    img = ImageOps.autocontrast(img)
    img = img.point(lambda p: 255 if p > 180 else 0)

    # Crop to content and square it
    img = crop_to_content_square(img)

    # Resize to label constraints (≤150×150 px)
    img.thumbnail((150, 150), Image.LANCZOS)

    # Binarize again
    img = img.point(lambda p: 255 if p > 180 else 0)

    if output_path:
        img.save(output_path, format="PNG", dpi=(180, 180))
        print(f"Saved label image → {output_path}")
    else:
        try:
            copy_image_to_clipboard_windows(img)
            print("Saved label image to system clipboard.")
        except Exception as ex:
            print(f"Exception while putting result into clipboard: {ex!r}")
            img.save("temp_conversion_result.png", format="PNG", dpi=(180, 180))
        show_image_with_cv2(img)

    print(f"Final size: {img.size}px @ 180 DPI")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a photo into semantic line art for label printing"
    )
    parser.add_argument(
        "input_image",
        nargs="?",
        default=None,
        help="Optional input image file (PNG/JPEG). If omitted, clipboard image is used.",
    )
    parser.add_argument(
        "output_image",
        nargs="?",
        default=None,
        help="Optional output PNG file. If omitted, result is copied to clipboard and previewed.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Optional prompt text to the AI",
    )

    args = parser.parse_args()
    image_to_line_art(args.input_image, args.output_image, args.prompt)


if __name__ == "__main__":
    main()
