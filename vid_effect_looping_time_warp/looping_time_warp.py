#!/usr/bin/env python3
"""
Frame stacking / temporal blending video tool.

Requirements:
    - ffmpeg and ffprobe installed
    - Python 3.8+
    - pip install opencv-python pillow numpy (if not already installed)

Usage example:
    python stacker.py input.mp4 \
        --start-time 00:00:01.250 \
        --duration 5.5 \
        --crop 100,200,800,600 \
        --stack-count 5 \
        --interval 5 \
        --opacity-table 1,2,3,2,1 \
        --loop-count 2 \
        --ffmpeg /usr/bin/ffmpeg \
        --temp-input-frames temp_input_frames \
        --temp-output-frames temp_output_frames \
        --output output.mp4 \
        --ffmpeg-args "-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p"
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
import shlex

import cv2
import numpy as np


# ---------- Helpers for paths and subprocesses ----------

def derive_ffprobe_path(ffmpeg_path: str) -> str:
    """
    Try to derive ffprobe path from the ffmpeg path.
    Fallback to "ffprobe" if we can't guess.
    """
    p = Path(ffmpeg_path)
    name_lower = p.name.lower()
    if name_lower.startswith("ffmpeg"):
        # Replace "ffmpeg" with "ffprobe" in filename
        new_name = p.name.replace("ffmpeg", "ffprobe")
        return str(p.with_name(new_name))
    return "ffprobe"


def run_subprocess(cmd, **kwargs):
    """Run a subprocess and raise a helpful error on failure."""
    try:
        subprocess.run(cmd, check=True, **kwargs)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Command failed: {' '.join(map(str, cmd))}", file=sys.stderr)
        print(f"Exit code: {e.returncode}", file=sys.stderr)
        sys.exit(1)


# ---------- FFprobe metadata ----------

def get_video_metadata(ffmpeg_path: str, input_video: Path):
    ffprobe_path = derive_ffprobe_path(ffmpeg_path)
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate",
        "-of", "json",
        str(input_video)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print("[ERROR] ffprobe failed to read video metadata.", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        # Use avg_frame_rate if available, fall back to r_frame_rate
        fr_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
        fps = parse_ffmpeg_framerate(fr_str)
        return {
            "width": width,
            "height": height,
            "fps": fps,
        }
    except Exception as e:
        print("[ERROR] Failed to parse ffprobe output:", e, file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        sys.exit(1)


def parse_ffmpeg_framerate(fr_str: str) -> float:
    if fr_str is None:
        return 30.0  # fallback
    if "/" in fr_str:
        num, den = fr_str.split("/")
        den = float(den)
        if den == 0:
            return float(num)
        return float(num) / den
    else:
        return float(fr_str)


# ---------- Frame extraction with ffmpeg ----------

def extract_frames(
    ffmpeg_path: str,
    input_video: Path,
    temp_input_dir: Path,
    start_time: str | None,
    duration: str | None,
    crop: tuple[int, int, int, int] | None
):
    """
    Use ffmpeg to extract frames as PNGs into temp_input_dir.
    Filenames: frame_000000.png, frame_000001.png, ...
    """
    if temp_input_dir.exists():
        shutil.rmtree(temp_input_dir)
    temp_input_dir.mkdir(parents=True, exist_ok=True)

    frame_pattern = str(temp_input_dir / "frame_%06d.png")

    vf_filters = []
    if crop is not None:
        x, y, w, h = crop
        vf_filters.append(f"crop={w}:{h}:{x}:{y}")
    vf_str = ",".join(vf_filters) if vf_filters else None

    cmd = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
    # Time clipping
    if start_time is not None:
        cmd.extend(["-ss", str(start_time)])
    if duration is not None:
        cmd.extend(["-t", str(duration)])

    cmd.extend(["-i", str(input_video)])

    if vf_str:
        cmd.extend(["-vf", vf_str])

    cmd.extend([frame_pattern])

    run_subprocess(cmd)


# ---------- Opacity table generation ----------

def parse_opacity_table(table_str: str | None) -> list[int] | None:
    if table_str is None:
        return None
    parts = [p.strip() for p in table_str.split(",") if p.strip()]
    try:
        values = [int(p) for p in parts]
    except ValueError:
        raise ValueError("Opacity table must be a comma-separated list of integers.")
    if not values:
        raise ValueError("Opacity table cannot be empty.")
    return values


def generate_bell_curve_opacity(stack_count: int) -> list[int]:
    """
    Generate a symmetric, bell-ish integer opacity table of length stack_count.
    Values are > 0 and relative only (we normalize by sum later).
    """
    if stack_count <= 0:
        raise ValueError("stack_count must be > 0 to generate opacity table.")

    # Gaussian-ish around center
    center = (stack_count - 1) / 2.0
    # Spread: choose so curve covers the array nicely
    sigma = stack_count / 3.0 if stack_count > 1 else 1.0

    raw = []
    for i in range(stack_count):
        x = (i - center) / sigma
        w = math.exp(-0.5 * x * x)
        raw.append(w)

    # Normalize so minimum is at least ~1, then convert to ints and add 1 to avoid zeros
    min_w = min(raw) if raw else 1.0
    scaled = [w / min_w for w in raw]
    ints = [int(round(w)) + 1 for w in scaled]  # +1 to guarantee > 0

    return ints


# ---------- Frame stacking ----------

def load_input_frames(temp_input_dir: Path) -> list[np.ndarray]:
    """
    Load all PNG frames into memory as float32 arrays.
    """
    frame_files = sorted(temp_input_dir.glob("frame_*.png"))
    if not frame_files:
        raise RuntimeError(f"No frames found in {temp_input_dir}")

    frames = []
    for f in frame_files:
        img = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"Failed to read frame: {f}")
        frames.append(img.astype(np.float32))
    return frames


def stack_frames(
    frames: list[np.ndarray],
    temp_output_dir: Path,
    stack_count: int,
    interval: int,
    opacity_table: list[int],
    loop_count: int,
):
    """
    For each frame index i:
        indices = (i + k*interval) % num_frames for k in 0..stack_count-1
        composite = weighted sum using opacity_table.

    Output frames written as frame_000000.png, etc. into temp_output_dir.

    Loop behavior:
        - effective_loops = 1 if loop_count <= 1 else loop_count
        - After first pass, we just duplicate the output PNGs for additional loops.
    """
    if temp_output_dir.exists():
        shutil.rmtree(temp_output_dir)
    temp_output_dir.mkdir(parents=True, exist_ok=True)

    if stack_count <= 0:
        raise ValueError("stack_count must be > 0")
    if interval <= 0:
        raise ValueError("interval must be > 0")
    if len(opacity_table) != stack_count:
        raise ValueError(
            f"Opacity table length ({len(opacity_table)}) "
            f"does not match stack_count ({stack_count})."
        )

    num_frames = len(frames)
    if num_frames == 0:
        raise RuntimeError("No input frames to stack.")

    weights = np.array(opacity_table, dtype=np.float32)
    weight_sum = float(weights.sum())
    if weight_sum <= 0:
        raise ValueError("Sum of opacity table must be > 0.")
    norm_weights = weights / weight_sum

    # Composite one loop worth of frames
    for i in range(num_frames):
        # Indices for this composite
        indices = [(i + k * interval) % num_frames for k in range(stack_count)]

        # Start with zeros
        acc = np.zeros_like(frames[0], dtype=np.float32)

        for w, idx in zip(norm_weights, indices):
            acc += frames[idx] * w

        composite = np.clip(acc, 0, 255).astype(np.uint8)

        out_name = temp_output_dir / f"frame_{i:06d}.png"
        if not cv2.imwrite(str(out_name), composite):
            raise RuntimeError(f"Failed to write output frame: {out_name}")

    # Handle loops by duplicating the stacked frames
    # loop_count <= 1 -> effective_loops = 1 (no duplication)
    # loop_count >= 2 -> repeat sequence loop_count times total
    effective_loops = 1 if loop_count <= 1 else loop_count

    if effective_loops > 1:
        # We already produced the first sequence [0 .. num_frames-1]
        original_files = [
            temp_output_dir / f"frame_{i:06d}.png" for i in range(num_frames)
        ]
        for loop_idx in range(1, effective_loops):
            offset = loop_idx * num_frames
            for i, src in enumerate(original_files):
                dst = temp_output_dir / f"frame_{offset + i:06d}.png"
                shutil.copyfile(src, dst)


# ---------- Video encoding with ffmpeg ----------

def encode_video(
    ffmpeg_path: str,
    temp_output_dir: Path,
    output_path: Path,
    fps: float,
    ffmpeg_args: str | None,
):
    """
    Encode the stacked PNG sequence into a video file.
    Respects fps and uses user-provided ffmpeg_args for the output options.
    """
    frame_pattern = str(temp_output_dir / "frame_%06d.png")

    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-framerate", f"{fps:.6f}",
        "-i", frame_pattern,
    ]

    # Add extra args (for output) if any
    if ffmpeg_args:
        cmd.extend(shlex.split(ffmpeg_args))

    cmd.append(str(output_path))

    run_subprocess(cmd)


# ---------- Argument parsing ----------

def parse_crop(crop_str: str | None):
    """
    Parse crop string "x,y,width,height" into a tuple of ints.
    """
    if crop_str is None:
        return None
    parts = [p.strip() for p in crop_str.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("Crop must be 'x,y,width,height'")
    try:
        x, y, w, h = map(int, parts)
    except ValueError:
        raise argparse.ArgumentTypeError("Crop values must be integers.")
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("Crop width and height must be > 0.")
    return (x, y, w, h)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Temporal frame stacker / alpha blend tool."
    )
    parser.add_argument(
        "video",
        type=str,
        help="Path to input video file.",
    )
    parser.add_argument(
        "--start-time",
        type=str,
        default=None,
        help=(
            "Optional start time within the video. "
            "Accepts ffmpeg time formats (e.g. '12.5', '00:00:12.500'). "
            "Default: from beginning."
        ),
    )
    parser.add_argument(
        "--duration",
        type=str,
        default=None,
        help=(
            "Optional duration from start-time. "
            "Accepts ffmpeg time formats. Default: until end of video."
        ),
    )
    parser.add_argument(
        "--crop",
        type=parse_crop,
        default=None,
        help="Optional crop rectangle 'x,y,width,height'. Default: full frame.",
    )
    parser.add_argument(
        "--stack-count",
        type=int,
        default=5,
        help="Number of frames to stack per output frame. Default: 5.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=20,
        help="Interval (in frames) between stacked frames. Default: 5.",
    )
    parser.add_argument(
        "--opacity-table",
        type=str,
        default=None,
        help=(
            "Comma-separated list of integers, length must equal stack-count. "
            "If omitted, a bell-curve-like table is auto-generated."
        ),
    )
    parser.add_argument(
        "--loop-count",
        type=int,
        default=1,
        help=(
            "How many times to repeat the stacked sequence.\n"
            "  - 0 or 1 => play once (no duplication)\n"
            "  - 2 => play twice, 3 => thrice, etc.\n"
            "Default: 1."
        ),
    )
    parser.add_argument(
        "--ffmpeg",
        type=str,
        default="ffmpeg",
        help="Path to ffmpeg executable. Default: 'ffmpeg' (in PATH).",
    )
    parser.add_argument(
        "--temp-input-frames",
        type=str,
        default="temp_input_frames",
        help="Directory for temporary input frames. Will be deleted/recreated. Default: 'temp_input_frames'.",
    )
    parser.add_argument(
        "--temp-output-frames",
        type=str,
        default="temp_output_frames",
        help="Directory for temporary output frames. Will be deleted/recreated. Default: 'temp_output_frames'.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output.mp4",
        help="Output video file path. Extension determines container. Default: 'output.mp4'.",
    )
    parser.add_argument(
        "--ffmpeg-args",
        type=str,
        default="-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p",
        help=(
            "Extra arguments passed to ffmpeg when encoding output video. "
            "Default: H.264 (libx264), CRF 18, preset medium, yuv420p."
        ),
    )
    return parser


# ---------- Main ----------

def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    input_video = Path(args.video)
    if not input_video.is_file():
        print(f"[ERROR] Input video not found: {input_video}", file=sys.stderr)
        sys.exit(1)

    ffmpeg_path = args.ffmpeg

    # Get metadata
    meta = get_video_metadata(ffmpeg_path, input_video)
    print(f"[INFO] Video width={meta['width']}, height={meta['height']}, fps={meta['fps']:.4f}")

    # Validate crop against dimensions (optional but nice)
    if args.crop is not None:
        x, y, w, h = args.crop
        if x < 0 or y < 0 or x + w > meta["width"] or y + h > meta["height"]:
            print(
                "[ERROR] Crop rectangle is outside the video dimensions "
                f"(video {meta['width']}x{meta['height']}, crop {x},{y},{w},{h}).",
                file=sys.stderr,
            )
            sys.exit(1)

    # Extract frames
    temp_input_dir = Path(args.temp_input_frames)
    extract_frames(
        ffmpeg_path=ffmpeg_path,
        input_video=input_video,
        temp_input_dir=temp_input_dir,
        start_time=args.start_time,
        duration=args.duration,
        crop=args.crop,
    )
    print(f"[INFO] Extracted frames into: {temp_input_dir}")

    # Opacity table
    opacity_table = parse_opacity_table(args.opacity_table)
    if opacity_table is None:
        opacity_table = generate_bell_curve_opacity(args.stack_count)
        print(f"[INFO] Auto-generated opacity table: {opacity_table}")
    else:
        print(f"[INFO] Using user-provided opacity table: {opacity_table}")

    if len(opacity_table) != args.stack_count:
        print(
            f"[ERROR] Opacity table length ({len(opacity_table)}) "
            f"does not match stack-count ({args.stack_count}).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load frames and stack
    frames = load_input_frames(temp_input_dir)
    print(f"[INFO] Loaded {len(frames)} input frames.")

    temp_output_dir = Path(args.temp_output_frames)
    stack_frames(
        frames=frames,
        temp_output_dir=temp_output_dir,
        stack_count=args.stack_count,
        interval=args.interval,
        opacity_table=opacity_table,
        loop_count=args.loop_count,
    )
    # Count how many output frames we produced
    out_frames = sorted(temp_output_dir.glob("frame_*.png"))
    print(f"[INFO] Generated {len(out_frames)} stacked frames in {temp_output_dir}")

    # Encode video
    output_path = Path(args.output)
    encode_video(
        ffmpeg_path=ffmpeg_path,
        temp_output_dir=temp_output_dir,
        output_path=output_path,
        fps=meta["fps"],
        ffmpeg_args=args.ffmpeg_args,
    )
    print(f"[INFO] Wrote output video: {output_path}")


if __name__ == "__main__":
    main()
