import argparse
import os
from pathlib import Path
from PIL import Image

VALID_SIZES = [16, 24, 32, 48, 64, 128, 256]

def next_valid_size_below(size):
    for s in sorted(VALID_SIZES, reverse=True):
        if s <= size:
            return s
    return min(VALID_SIZES)

def make_square_rgba(img, size):
    return img.convert("RGBA").resize((size, size), Image.LANCZOS)

def process_single_png(input_path, output_path):
    img = Image.open(input_path).convert("RGBA")

    w, h = img.size
    base_size = min(w, h)

    max_valid = next_valid_size_below(base_size)

    sizes_to_generate = [s for s in VALID_SIZES if s <= max_valid]
    sizes_to_generate.sort(reverse=True)

    print(f"Input size: {w}x{h}")
    print(f"Generating sizes: {sizes_to_generate}")

    images = []
    for s in sizes_to_generate:
        resized = make_square_rgba(img, s)
        images.append(resized)

    primary = images[0]
    primary.save(output_path, format="ICO", append_images=images[1:])
    print(f"Saved ICO to {output_path}")

def process_directory(input_dir, output_path):
    input_dir = Path(input_dir)

    png_files = list(input_dir.glob("*.png"))
    if not png_files:
        raise RuntimeError("No PNG files found in directory.")

    png_files = sorted(
        png_files,
        key=lambda p: min(Image.open(p).size)
    )

    done_sizes = set()
    images = []

    # Process largest first
    for path in reversed(png_files):
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        base_size = min(w, h)

        target_size = next_valid_size_below(base_size)

        if target_size in done_sizes:
            print(f"WARNING: {path.name} maps to {target_size}px but already filled. Skipping.")
            continue

        resized = make_square_rgba(img, target_size)
        images.append((target_size, resized, path.name))
        done_sizes.add(target_size)

        print(f"{path.name} -> {target_size}px")

    if not images:
        raise RuntimeError("No valid images mapped to icon sizes.")

    # Sort largest first for primary
    images.sort(key=lambda x: x[0], reverse=True)

    primary_img = images[0][1]
    append_imgs = [x[1] for x in images[1:]]

    primary_img.save(output_path, format="ICO", append_images=append_imgs)

    print(f"Saved ICO to {output_path}")

def resolve_output_path(input_path, output_arg):
    input_path = Path(input_path)

    if output_arg:
        return Path(output_arg)

    if input_path.is_file():
        return input_path.with_suffix(".ico")

    if input_path.is_dir():
        return input_path / (input_path.name + ".ico")

    raise RuntimeError("Invalid input path.")

def main():
    parser = argparse.ArgumentParser(description="Create ICO from PNG or directory of PNGs.")
    parser.add_argument("input", help="Path to PNG file or directory of PNG files.")
    parser.add_argument("-o", "--output", help="Output ICO file path.")

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        raise RuntimeError("Input path does not exist.")

    output_path = resolve_output_path(input_path, args.output)

    if input_path.is_file():
        process_single_png(input_path, output_path)
    elif input_path.is_dir():
        process_directory(input_path, output_path)
    else:
        raise RuntimeError("Input must be PNG file or directory.")

if __name__ == "__main__":
    main()
