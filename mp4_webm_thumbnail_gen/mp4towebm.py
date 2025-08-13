#!/usr/bin/env python3
import argparse
import subprocess
from pathlib import Path
import shutil
import sys

def require_ffmpeg():
    if shutil.which("ffmpeg") is None:
        sys.exit("Error: ffmpeg not found in PATH.")

def make_webm_thumb(src: Path, out: Path, crf=32, fps=15, box=320, duration=5.0):
    out.parent.mkdir(parents=True, exist_ok=True)
    # Scale to fit inside 320x320 preserving aspect, then pad to square
    vf = (
        f"fps={fps},"
        f"scale={box}:{box}:force_original_aspect_ratio=decrease,"
        f"pad={box}:{box}:(ow-iw)/2:(oh-ih)/2:color=black"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", "0", "-t", str(duration),
        "-i", str(src),
        "-an",                                 # no audio
        "-vf", vf,
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuv420p",
        "-b:v", "0",
        "-crf", str(crf),
        "-speed", "4",
        "-row-mt", "1",
        "-tile-columns", "2",
        "-frame-parallel", "1",
        str(out)
    ]
    subprocess.run(cmd, check=True)

def main():
    p = argparse.ArgumentParser(description="Make 5s 320x320 15FPS WebM thumbnails from MP4s.")
    p.add_argument("input", help="An .mp4 file or a directory containing .mp4 files")
    p.add_argument("--out", default="thumbnails", help="Output directory (default: thumbnails)")
    p.add_argument("--fps", type=int, default=15, help="Output frames per second (default: 15)")
    p.add_argument("--box", type=int, default=320, help="Box size (default: 320)")
    p.add_argument("--dur", type=float, default=5.0, help="Clip duration seconds (default: 5.0)")
    p.add_argument("--crf", type=int, default=32, help="VP9 CRF (default: 32; 28 is higher quality)")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip files if output .webm already exists")
    args = p.parse_args()

    require_ffmpeg()
    out_dir = Path(args.out)
    src_path = Path(args.input)

    if src_path.is_dir():
        targets = sorted(src_path.rglob("*.mp4"))
    elif src_path.suffix.lower() == ".mp4":
        targets = [src_path]
    else:
        sys.exit("Input must be an .mp4 file or a directory containing .mp4 files.")

    if not targets:
        print("No .mp4 files found.")
        return

    for i, mp4 in enumerate(targets, 1):
        out_file = out_dir / (mp4.stem + ".webm")
        if args.skip_existing and out_file.exists():
            print(f"[{i}/{len(targets)}] Skipping existing: {out_file}")
            continue

        try:
            print(f"[{i}/{len(targets)}] {mp4} → {out_file}")
            make_webm_thumb(mp4, out_file, crf=args.crf, fps=args.fps,
                            box=args.box, duration=args.dur)
        except subprocess.CalledProcessError as e:
            print(f"✖ ffmpeg failed for {mp4}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
