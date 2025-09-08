#!/usr/bin/env python3
import argparse
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image


def collect_images(dir_path: Path):
    exts = {".jpg", ".jpeg", ".png"}
    files = [p for p in dir_path.iterdir() if p.suffix.lower() in exts and p.is_file()]
    files.sort(key=lambda p: p.name.lower())
    return files


def build_selection(files, total, interval):
    if not files:
        raise ValueError("No JPG/PNG images found in the directory.")
    if total <= 0:
        raise ValueError("--total must be a positive integer.")

    step = interval if interval and interval > 0 else 1
    out = []
    n = len(files)
    idx = 0
    for _ in range(total):
        out.append(files[idx % n])
        idx += step
    return out


def open_as_rgb(path: Path, target_size):
    """Open image as RGB and resize to target_size if needed."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.size != target_size:
            im = im.resize(target_size, Image.BILINEAR)
        return np.array(im, dtype=np.uint8)


def save_image(canvas: np.ndarray, out_path: Path):
    out_ext = out_path.suffix.lower()
    pil_img = Image.fromarray(canvas, mode="RGB")
    try:
        if out_ext in {".jpg", ".jpeg"}:
            pil_img.save(out_path, quality=95, optimize=True)
        elif out_ext in {".png"}:
            pil_img.save(out_path, optimize=True)
        elif out_ext in {".webp"}:
            pil_img.save(out_path, quality=95, method=6)
        elif out_ext in {".bmp", ".tif", ".tiff"}:
            pil_img.save(out_path)
        else:
            # Unknown extension: try saving as-is; if that fails, fallback to PNG
            try:
                pil_img.save(out_path)
            except Exception:
                fallback = out_path.with_suffix(".png")
                pil_img.save(fallback, optimize=True)
                print(f"Unrecognized extension; saved as {fallback.name}")
                return
    except Exception as e:
        raise RuntimeError(f"Failed to save image: {e}")


def compose_axis_aligned(angle_deg, selected_paths, size_wh):
    """Fast rectangular stripes for 0, 90, 180, 270 degrees.
       90: left -> right (x increasing)
       270: right -> left (x decreasing)
       0: bottom -> top (y decreasing, since image y grows downward)
       180: top -> bottom (y increasing)
    """
    W, H = size_wh
    N = len(selected_paths)
    canvas = np.zeros((H, W, 3), dtype=np.uint8)

    # Choose orientation
    a = angle_deg % 360
    if a in (90, 270):
        per = W // N
        if per < 1:
            # Too many slices for columns; fall back to angled method outside.
            return None
        # Crop width to exact multiple to avoid leftover
        Wc = per * N
        for i, p in enumerate(selected_paths):
            img = open_as_rgb(p, (W, H))
            if a == 90:
                x0, x1 = i * per, (i + 1) * per
            else:  # 270
                x0, x1 = Wc - (i + 1) * per, Wc - i * per
            canvas[:, x0:x1, :] = img[:, x0:x1, :]
        if Wc < W:
            canvas = canvas[:, :Wc, :]
        return canvas

    elif a in (0, 180):
        per = H // N
        if per < 1:
            # Too many slices for rows; fall back to angled method outside.
            return None
        Hc = per * N
        for i, p in enumerate(selected_paths):
            img = open_as_rgb(p, (W, H))
            if a == 180:
                y0, y1 = i * per, (i + 1) * per
            else:  # 0 (bottom -> top)
                y0, y1 = Hc - (i + 1) * per, Hc - i * per
            canvas[y0:y1, :, :] = img[y0:y1, :, :]
        if Hc < H:
            canvas = canvas[:Hc, :, :]
        return canvas

    else:
        return None  # Not axis-aligned; handled by compose_angled


def compose_angled(angle_deg, selected_paths, size_wh):
    """General case: partition the image into N bands perpendicular to the direction
       of travel. This assigns every pixel to exactly one band => no gaps.
       Angle convention (matches your spec):
         - 90  -> left to right
         - 270 -> right to left
         - 0   -> bottom to top
         - 180 -> top to bottom
       Direction vector v = (sin(a), -cos(a)) in image coords (x right, y down).
    """
    W, H = size_wh
    N = len(selected_paths)

    # Build the (x,y) grid once
    X = np.tile(np.arange(W, dtype=np.float32), (H, 1))
    Y = np.tile(np.arange(H, dtype=np.float32).reshape(H, 1), (1, W))

    a = math.radians(angle_deg % 360)
    vx = math.sin(a)
    vy = -math.cos(a)

    # Project each pixel onto direction vector
    t = X * vx + Y * vy
    t_min = float(t.min())
    t_max = float(t.max())
    # Guard against degenerate delta
    delta = (t_max - t_min) / max(N, 1)
    if delta == 0:
        delta = 1.0

    # Which band (0..N-1) does each pixel belong to?
    k_map = np.floor((t - t_min) / delta).astype(np.int32)
    np.clip(k_map, 0, N - 1, out=k_map)

    canvas = np.zeros((H, W, 3), dtype=np.uint8)

    # Fill band-by-band from each chosen image
    for i, p in enumerate(selected_paths):
        mask = (k_map == i)
        if not mask.any():
            continue  # empty band (can happen if N >> pixels along projection)
        img = open_as_rgb(p, (W, H))
        canvas[mask] = img[mask]

    return canvas


def main():
    parser = argparse.ArgumentParser(
        description="Slice-and-stitch timelapse frames into a directional mosaic."
    )
    parser.add_argument("directory", type=str, help="Directory containing frames")
    parser.add_argument("--total", type=int, required=True,
                        help="Total number of frames to use in the mosaic")
    parser.add_argument("--interval", type=int, default=1,
                        help="Sampling interval: 0 or 1 = every file; 2 = every other; etc.")
    parser.add_argument("--angle", type=float, default=90.0,
                        help="Direction angle in degrees: "
                             "90=left->right, 270=right->left, 0=bottom->top, 180=top->bottom")
    parser.add_argument("--output", type=str, default="output.png",
                        help="Output file path (extension respected if possible)")

    args = parser.parse_args()

    dir_path = Path(args.directory)
    if not dir_path.exists() or not dir_path.is_dir():
        raise SystemExit("Provided directory does not exist or is not a directory.")

    files = collect_images(dir_path)
    selected = build_selection(files, args.total, args.interval)

    # Determine base size from first selected image
    with Image.open(selected[0]) as im0:
        im0 = im0.convert("RGB")
        size_wh = im0.size  # (W, H)
    W, H = size_wh

    # Try axis-aligned fast path first if appropriate
    a = args.angle % 360
    canvas = None
    if a in (0, 90, 180, 270):
        canvas = compose_axis_aligned(a, selected, size_wh)

    if canvas is None:
        # General angled method (also used if too many slices for axis pixels)
        canvas = compose_angled(args.angle, selected, size_wh)

    save_image(canvas, Path(args.output))
    print(f"Saved mosaic to: {args.output}")


if __name__ == "__main__":
    main()
