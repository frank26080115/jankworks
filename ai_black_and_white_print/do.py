import argparse
import shutil, os
from PIL import Image

from utils import load_input_image, copy_image_to_clipboard_windows, show_image_with_cv2, crop_to_content_square
from ai_bw_convert import image_to_line_art
from bw_enough_check import already_black_and_white_enough
from dither_thumbnail import dither_convert
from dxf_to_png_thumb import dxf_to_img

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
    parser.add_argument(
        "--prompt",
        default=None,
        help="Optional prompt text to the AI (if using AI)",
    )
    parser.add_argument(
        "--dither",
        action='store_true',
        help="Use dither instead of AI",
    )
    parser.add_argument(
        "--dither_outline",
        action='store_true',
        help="Add an outline if using dithering",
    )

    args = parser.parse_args()

    if args.input_image:
        if os.path.splittext(input_path)[1].lower() == ".dxf":
            output_path = dxf_to_img(input_path)
            if args.output_image:
                shutil.move(os.path.abspath(output_path), os.path.abspath(args.output_image))
                print(f"Image saved to `{args.output_image}`")
            else:
                img = Image.open(output_path)
                copy_image_to_clipboard_windows(img)
                print(f"Image available on clipboard")
                show_image_with_cv2(img)
            exit(0)

    result, output_path = already_black_and_white_enough(args.input_image, args.output_image)

    if result:
        print(f"Image converted to B&W without using AI")
        if output_path:
            #print(f"Result saved to: `{output_path}`")
            pass
        else:
            #print(f"Result available on clipboard")
            pass
        exit(0)

    if not args.dither:
        print("Using AI to convert image")
        image_to_line_art(args.input_image, args.output_image, args.prompt)
    else:
        print("Using dithering to convert image")
        dither_convert(args.input_image, args.output_image, args.dither_outline)

if __name__ == "__main__":
    main()
