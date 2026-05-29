import argparse
import pathlib
import shutil
import subprocess

import cv2
import numpy as np


# =========================
# EDIT THIS
# =========================

FFMPEG_EXE = r"C:\ProgramFiles\ffmpeg-5.1.2-full_build\bin\ffmpeg.exe"


# =========================
# HELPERS
# =========================

def run(cmd):
    print("\n>", " ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True)


def parse_time_to_seconds(value):
    parts = value.split(":")

    if len(parts) == 3:
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s

    if len(parts) == 2:
        m = float(parts[0])
        s = float(parts[1])
        return m * 60 + s

    return float(value)


def seconds_to_time(value):
    if value < 0:
        value = 0

    h = int(value // 3600)
    value -= h * 3600
    m = int(value // 60)
    s = value - m * 60

    return f"{h:02d}:{m:02d}:{s:06.3f}"


def get_output_dir(video_path):
    video_path = pathlib.Path(video_path)
    return video_path.parent / f"{video_path.stem}_output"


def get_video_fps(video_path):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    if not fps or fps <= 0:
        raise RuntimeError("Could not determine video FPS")

    return fps


def extract_frames(video_path, start_time, end_time, frames_dir):
    frames_dir.mkdir(parents=True, exist_ok=True)

    run([
        FFMPEG_EXE,
        "-y",
        "-ss", start_time,
        "-to", end_time,
        "-i", str(video_path),
        "-vsync", "0",
        str(frames_dir / "%08d.png"),
    ])


def make_radial_masks(height, width, history_count, power):
    """
    Returns a list of masks, one per temporal frame.

    index 0 = newest frame
    index history_count - 1 = oldest frame

    Center:
      newest frame weight = 1.0

    Furthest corners:
      oldest frame weight = 1.0
    """

    yy, xx = np.mgrid[0:height, 0:width]

    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0

    dx = xx - cx
    dy = yy - cy

    dist = np.sqrt(dx * dx + dy * dy)

    max_dist = np.sqrt(cx * cx + cy * cy)
    r = dist / max_dist
    r = np.clip(r, 0.0, 1.0)
    r = r ** power

    # Convert radial distance into a continuous temporal position.
    # 0.0 = newest frame
    # history_count - 1 = oldest frame
    temporal_pos = r * (history_count - 1)

    masks = []

    for i in range(history_count):
        # Triangle filter around each temporal frame index.
        mask = 1.0 - np.abs(temporal_pos - i)
        mask = np.clip(mask, 0.0, 1.0)
        masks.append(mask.astype(np.float32)[:, :, None])

    # Normalize just in case.
    total = np.sum(masks, axis=0)
    masks = [m / np.maximum(total, 1e-6) for m in masks]

    return masks


def blend_frames(frames_dir, frames_blended_dir, n_frames, power):
    frame_paths = sorted(frames_dir.glob("*.png"))

    if not frame_paths:
        raise RuntimeError(f"No PNG frames found in {frames_dir}")

    if n_frames < 1:
        raise ValueError("--frames must be at least 1")

    if len(frame_paths) <= n_frames:
        raise RuntimeError(
            f"Need more than {n_frames} extracted frames, only found {len(frame_paths)}"
        )

    frames_blended_dir.mkdir(parents=True, exist_ok=True)

    first = cv2.imread(str(frame_paths[0]))
    if first is None:
        raise RuntimeError(f"Could not read first frame: {frame_paths[0]}")

    h, w = first.shape[:2]

    # For current frame + N previous frames:
    history_count = n_frames + 1
    masks = make_radial_masks(h, w, history_count, power)

    output_index = 1

    # Starting at the N-th previous-available frame:
    # current index n_frames has exactly N frames before it.
    for current_index in range(n_frames, len(frame_paths)):
        blended = np.zeros((h, w, 3), dtype=np.float32)

        for age in range(history_count):
            source_index = current_index - age
            frame = cv2.imread(str(frame_paths[source_index]))

            if frame is None:
                raise RuntimeError(f"Could not read frame: {frame_paths[source_index]}")

            blended += frame.astype(np.float32) * masks[age]

        blended_u8 = np.clip(blended, 0, 255).astype(np.uint8)

        output_path = frames_blended_dir / f"{output_index:08d}.png"
        cv2.imwrite(str(output_path), blended_u8)

        if output_index % 100 == 0:
            print(f"Blended: {output_index}")

        output_index += 1

    print(f"Created {output_index - 1} blended frames")


def assemble_video(
    video_path,
    frames_blended_dir,
    output_mp4,
    fps,
    audio_start_time,
    end_time,
    codec,
):
    run([
        FFMPEG_EXE,
        "-y",

        "-framerate", str(fps),
        "-i", str(frames_blended_dir / "%08d.png"),

        "-ss", audio_start_time,
        "-to", end_time,
        "-i", str(video_path),

        "-map", "0:v:0",
        "-map", "1:a:0?",

        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",

        "-c:v", codec,
        "-pix_fmt", "yuv420p",

        "-c:a", "aac",
        "-b:a", "192k",

        "-shortest",
        str(output_mp4),
    ])


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create radial temporal blend dashcam effect."
    )

    parser.add_argument(
        "--video",
        required=True,
        help="Input video file",
    )

    parser.add_argument(
        "--start",
        required=True,
        help="Start time, example: 00:01:23.000",
    )

    parser.add_argument(
        "--end",
        required=True,
        help="End time, example: 00:01:45.000",
    )

    parser.add_argument(
        "--frames",
        type=int,
        required=True,
        help="Number N of previous frames to blend with the current frame",
    )

    parser.add_argument(
        "--codec",
        default="libx264",
        choices=["libx264", "libx265"],
        help="Output codec. Default: libx264",
    )

    parser.add_argument(
        "--radial-power",
        type=float,
        default=1.8,
        help="Radial falloff shaping. Higher keeps center more current. Default: 1.8",
    )

    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip extracting frames; reuse output_dir/frames",
    )

    parser.add_argument(
        "--skip-blend",
        action="store_true",
        help="Skip blending; reuse output_dir/frames_blended",
    )

    parser.add_argument(
        "--skip-assemble",
        action="store_true",
        help="Skip final video assembly",
    )

    return parser.parse_args()


# =========================
# MAIN
# =========================

def main():
    args = parse_args()

    video_path = pathlib.Path(args.video)

    if not video_path.exists():
        raise FileNotFoundError(video_path)

    if not pathlib.Path(FFMPEG_EXE).exists():
        raise FileNotFoundError(FFMPEG_EXE)

    output_dir = get_output_dir(video_path)
    frames_dir = output_dir / "frames"
    frames_blended_dir = output_dir / "frames_blended"
    final_video = output_dir / "blended.mp4"

    output_dir.mkdir(parents=True, exist_ok=True)

    fps = get_video_fps(video_path)

    start_seconds = parse_time_to_seconds(args.start)
    audio_offset_seconds = args.frames / fps
    audio_start_seconds = start_seconds + audio_offset_seconds
    audio_start_time = seconds_to_time(audio_start_seconds)

    print(f"Output directory: {output_dir}")
    print(f"Detected FPS: {fps}")
    print(f"Blend history: current frame + {args.frames} previous frames")
    print(f"Audio starts at: {audio_start_time}")

    if not args.skip_extract:
        print("\n🎞️ Extracting frames...")
        if frames_dir.exists():
            shutil.rmtree(frames_dir)

        extract_frames(
            video_path,
            args.start,
            args.end,
            frames_dir,
        )
    else:
        print("\n⏭️ Skipping frame extraction")

    if not args.skip_blend:
        print("\n🌀 Creating radial temporal blended frames...")
        if frames_blended_dir.exists():
            shutil.rmtree(frames_blended_dir)

        blend_frames(
            frames_dir,
            frames_blended_dir,
            args.frames,
            args.radial_power,
        )
    else:
        print("\n⏭️ Skipping blend stage")

    if not args.skip_assemble:
        print("\n🎬 Assembling video...")
        assemble_video(
            video_path,
            frames_blended_dir,
            final_video,
            fps,
            audio_start_time,
            args.end,
            args.codec,
        )
    else:
        print("\n⏭️ Skipping video assembly")

    print("\n✅ Done!")
    print(final_video)


if __name__ == "__main__":
    main()
