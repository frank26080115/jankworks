import os
import shutil
import subprocess
import argparse
from pathlib import Path
import json

def get_video_duration(file_path):
    """Get duration of a video file in seconds using ffprobe (fast)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "json",
        str(file_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])

def create_timelapse(input_folder, output_file, length_minutes, fps=25, trim_start=0, trim_end=0):
    input_path = Path(input_folder)
    if not input_path.exists():
        raise FileNotFoundError(f"Folder not found: {input_path}")

    # Sort video files by modification time
    video_files = sorted(
        [f for f in input_path.iterdir() if f.suffix.lower() in [".mp4", ".mov", ".avi", ".mkv"]],
        key=lambda x: x.stat().st_mtime
    )

    if not video_files:
        raise ValueError("No supported video files found in folder.")

    # Adjust durations for trim_start / trim_end
    durations = []
    for i, vf in enumerate(video_files):
        dur = get_video_duration(vf)
        if i == 0:
            dur = max(0, dur - trim_start)
        if i == len(video_files) - 1:
            dur = max(0, dur - trim_end)
        durations.append(dur)

    total_seconds = sum(durations)

    # Calculate frame interval
    total_target_frames = length_minutes * 60 * fps
    frame_interval = total_seconds / total_target_frames

    print(f"Total duration after trims: {total_seconds:.2f} sec")
    print(f"Target frames: {total_target_frames}")
    print(f"Frame interval: {frame_interval:.3f} sec")

    # Prepare frames directory (delete if exists)
    frames_dir = input_path / "frames_tmp"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir()

    # Build ffmpeg concat list with trims
    concat_file = input_path / "concat_list.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for i, vf in enumerate(video_files):
            if i == 0 and trim_start > 0:
                f.write(f"file '{vf.as_posix()}'\n")
            elif i == len(video_files) - 1 and trim_end > 0:
                f.write(f"file '{vf.as_posix()}'\n")
            else:
                f.write(f"file '{vf.as_posix()}'\n")

    # NOTE: Trimming is handled in the filter step below

    # Extract frames as PNG
    trim_start_filter = f"trim=start={trim_start}," if trim_start > 0 else ""
    trim_end_filter = f"setpts=PTS-STARTPTS," if trim_start > 0 else ""  # ensure timing reset
    # For last video trim, we can't just do in concat, so we'll use select filter
    # Simpler: apply trims via -ss and -to per file is more robust

    # Create one big intermediate file with trims applied
    tmp_merged = input_path / "merged_tmp.mp4"
    filter_complex = []
    inputs = []
    for i, vf in enumerate(video_files):
        ss = trim_start if i == 0 else 0
        to = None
        if i == len(video_files) - 1 and trim_end > 0:
            dur = get_video_duration(vf)
            to = dur - trim_end
        cmd_part = ["-ss", str(ss)] if ss > 0 else []
        if to:
            cmd_part += ["-to", str(to)]
        inputs.append((vf, cmd_part))

    # Merge videos with trims
    concat_list_path = input_path / "concat_inputs.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for vf, trim_args in inputs:
            if trim_args:
                # If trims exist, re-encode that clip into temp file
                trimmed_path = vf.with_name(f"trimmed_{vf.name}")
                subprocess.run(
                    ["ffmpeg", *trim_args, "-i", str(vf), "-c", "copy", str(trimmed_path)],
                    check=True
                )
                f.write(f"file '{trimmed_path.as_posix()}'\n")
            else:
                f.write(f"file '{vf.as_posix()}'\n")

    subprocess.run(
        ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list_path),
         "-c", "copy", str(tmp_merged)],
        check=True
    )

    # Extract frames from merged file
    subprocess.run([
        "ffmpeg", "-i", str(tmp_merged),
        "-vf", f"fps=1/{frame_interval}",
        str(frames_dir / "frame_%06d.png")
    ], check=True)

    # Assemble timelapse
    subprocess.run([
        "ffmpeg", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(output_file)
    ], check=True)

    print(f"Timelapse saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate timelapse from dash cam videos.")
    parser.add_argument("--dir", required=True, help="Directory containing dash cam videos")
    parser.add_argument("--minutes", type=int, required=True, help="Length of output timelapse in minutes")
    parser.add_argument("--trim_start", type=float, default=0, help="Seconds to trim from start of first video")
    parser.add_argument("--trim_end", type=float, default=0, help="Seconds to trim from end of last video")
    parser.add_argument("--output", default="timelapse.mp4", help="Output timelapse file path")
    args = parser.parse_args()

    create_timelapse(args.dir, args.output, args.minutes, fps=25,
                     trim_start=args.trim_start, trim_end=args.trim_end)
