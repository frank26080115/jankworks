import argparse
import subprocess
import pathlib
import shutil
import cv2
import numpy as np

# =========================
# ARGPARSE
# =========================

parser = argparse.ArgumentParser(
    description="Generate optical-flow steering indicator video."
)

parser.add_argument(
    "--ffmpeg",
    default=r"C:\ProgramFiles\ffmpeg-5.1.2-full_build\bin\ffmpeg.exe",
    help="Path to ffmpeg.exe",
)

parser.add_argument(
    "--video",
    required=True,
    help="Input video file",
)

parser.add_argument(
    "--start",
    required=True,
    help="Start time (example: 00:01:23.000)",
)

parser.add_argument(
    "--end",
    required=True,
    help="End time (example: 00:01:45.000)",
)

parser.add_argument(
    "--codec",
    default="libx264",
    choices=["libx264", "libx265"],
    help="Output codec",
)

parser.add_argument(
    "--skip-extract",
    action="store_true",
    help="Skip extracting frames; reuse output_dir/frames",
)

parser.add_argument(
    "--skip-flow",
    action="store_true",
    help="Skip optical flow calculation; reuse .txt files in output_dir/frames",
)

parser.add_argument(
    "--skip-indicator",
    action="store_true",
    help="Skip drawing indicator frames; reuse output_dir/frames_indicator",
)

parser.add_argument(
    "--skip-assemble",
    action="store_true",
    help="Skip final video assembly",
)

parser.add_argument(
    "--marker-size-ratio",
    type=float,
    default=0.05,
    help="Marker size as fraction of frame height. Default: 0.05",
)


parser.add_argument(
    "--skip-rotate",
    action="store_true",
    help="Skip rollercoaster rotation frames; reuse output_dir/rotated",
)

parser.add_argument(
    "--skip-rollercoaster-assemble",
    action="store_true",
    help="Skip assembling output_dir/rollercoaster.mp4",
)

parser.add_argument(
    "--max-roll-degrees",
    type=float,
    default=15.0,
    help="Maximum roll angle in degrees. Default: 15",
)

parser.add_argument(
    "--roll-smoothing",
    type=float,
    default=0.08,
    help="EMA low-pass smoothing alpha for roll, 0..1. Smaller is smoother. Default: 0.08",
)


args = parser.parse_args()

FFMPEG_EXE = args.ffmpeg
VIDEO_FILE = args.video
START_TIME = args.start
END_TIME = args.end
OUTPUT_CODEC = args.codec


# =========================
# EDIT THESE
# =========================

MARKER_MAX_PIXELS = 100
MARKER_SIZE_RATIO = args.marker_size_ratio

# Farneback optical flow settings
FLOW_PYR_SCALE = 0.5
FLOW_LEVELS = 3
FLOW_WINSIZE = 25
FLOW_ITERATIONS = 3
FLOW_POLY_N = 5
FLOW_POLY_SIGMA = 1.2


# =========================
# HELPERS
# =========================

def run(cmd):
    print("\n>", " ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True)


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


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def extract_frames(video_path, frames_dir):
    frames_dir.mkdir(parents=True, exist_ok=True)

    run([
        FFMPEG_EXE,
        "-y",
        "-ss", START_TIME,
        "-to", END_TIME,
        "-i", str(video_path),
        "-vsync", "0",
        str(frames_dir / "%08d.png"),
    ])


def calculate_optical_flow(frames_dir):
    frame_paths = sorted(frames_dir.glob("*.png"))

    if not frame_paths:
        raise RuntimeError("No frames extracted")

    flows = []
    prev_gray = None
    max_abs_x = 0.0

    for index, frame_path in enumerate(frame_paths):
        frame = cv2.imread(str(frame_path))
        if frame is None:
            raise RuntimeError(f"Could not read frame: {frame_path}")

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if prev_gray is None:
            avg_x = 0.0
            avg_y = 0.0
        else:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray,
                gray,
                None,
                FLOW_PYR_SCALE,
                FLOW_LEVELS,
                FLOW_WINSIZE,
                FLOW_ITERATIONS,
                FLOW_POLY_N,
                FLOW_POLY_SIGMA,
                0,
            )

            avg_x = float(np.mean(flow[:, :, 0]))
            avg_y = float(np.mean(flow[:, :, 1]))

        max_abs_x = max(max_abs_x, abs(avg_x))
        flows.append((frame_path, avg_x, avg_y))

        txt_path = frame_path.with_suffix(".txt")
        txt_path.write_text(f"{avg_x}\n{avg_y}\n", encoding="utf-8")

        prev_gray = gray

        if index % 100 == 0:
            print(f"Flow: {index + 1}/{len(frame_paths)}")

    print(f"\nMaximum absolute X optical flow: {max_abs_x}")
    return flows, max_abs_x


def draw_indicator_frames(flows, max_abs_x, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, (frame_path, avg_x, avg_y) in enumerate(flows):
        frame = cv2.imread(str(frame_path))
        if frame is None:
            raise RuntimeError(f"Could not read frame: {frame_path}")

        h, w = frame.shape[:2]

        center_x = w // 2
        marker_size = max(6, int(round(h * MARKER_SIZE_RATIO)))
        marker_y = marker_size

        # Invert X because visual flow left means vehicle/camera motion right.
        if max_abs_x > 0:
            offset = int(round((-avg_x / max_abs_x) * MARKER_MAX_PIXELS))
        else:
            offset = 0

        red_x = center_x + offset

        draw_square(frame, center_x, marker_y, (0, 255, 0))
        draw_square(frame, red_x, marker_y, (0, 0, 255))

        output_path = output_dir / frame_path.name
        cv2.imwrite(str(output_path), frame)

        if index % 100 == 0:
            print(f"Indicator: {index + 1}/{len(flows)}")


def draw_square(frame, cx, cy, color_bgr):
    size = max(6, int(round(frame.shape[0] * MARKER_SIZE_RATIO)))
    half = size // 2

    x1 = max(0, cx - half)
    y1 = max(0, cy - half)
    x2 = min(frame.shape[1] - 1, cx + half - 1)
    y2 = min(frame.shape[0] - 1, cy + half - 1)

    cv2.rectangle(frame, (x1, y1), (x2, y2), color_bgr, thickness=-1)


def assemble_video(video_path, frames_indicator_dir, output_mp4, fps):
    run([
        FFMPEG_EXE,
        "-y",

        "-framerate", str(fps),
        "-i", str(frames_indicator_dir / "%08d.png"),

        "-ss", START_TIME,
        "-to", END_TIME,
        "-i", str(video_path),

        "-map", "0:v:0",
        "-map", "1:a:0?",

        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",

        "-c:v", OUTPUT_CODEC,
        "-pix_fmt", "yuv420p",

        "-c:a", "aac",
        "-b:a", "192k",

        "-shortest",
        str(output_mp4),
    ])


def load_optical_flow_from_txt(frames_dir):
    frame_paths = sorted(frames_dir.glob("*.png"))

    if not frame_paths:
        raise RuntimeError("No frames found")

    flows = []
    max_abs_x = 0.0

    for frame_path in frame_paths:
        txt_path = frame_path.with_suffix(".txt")

        if not txt_path.exists():
            raise RuntimeError(f"Missing flow file: {txt_path}")

        lines = txt_path.read_text(encoding="utf-8").splitlines()
        if len(lines) < 2:
            raise RuntimeError(f"Invalid flow file: {txt_path}")

        avg_x = float(lines[0])
        avg_y = float(lines[1])

        flows.append((frame_path, avg_x, avg_y))
        max_abs_x = max(max_abs_x, abs(avg_x))

    print(f"Loaded maximum absolute X optical flow: {max_abs_x}")
    return flows, max_abs_x


def create_rotated_frames(flows, max_abs_x, rotated_dir, max_degrees, smoothing_alpha):
    rotated_dir.mkdir(parents=True, exist_ok=True)

    smoothing_alpha = clamp(smoothing_alpha, 0.0, 1.0)

    smoothed_angle = 0.0

    for index, (frame_path, avg_x, avg_y) in enumerate(flows):
        frame = cv2.imread(str(frame_path))
        if frame is None:
            raise RuntimeError(f"Could not read frame: {frame_path}")

        h, w = frame.shape[:2]

        if max_abs_x > 0:
            normalized = avg_x / max_abs_x
        else:
            normalized = 0.0

        normalized = clamp(normalized, -1.0, 1.0)

        # Sign note:
        # Car turning right => image optical flow tends left => avg_x is negative.
        # OpenCV negative angle = clockwise visual rotation.
        # So angle = normalized * max_degrees gives clockwise roll for right turns.
        target_angle = normalized * max_degrees

        smoothed_angle = (
            smoothing_alpha * target_angle
            + (1.0 - smoothing_alpha) * smoothed_angle
        )

        center = (w / 2.0, h / 2.0)
        matrix = cv2.getRotationMatrix2D(center, smoothed_angle, 1.0)

        rotated = cv2.warpAffine(
            frame,
            matrix,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )

        output_path = rotated_dir / frame_path.name
        cv2.imwrite(str(output_path), rotated)

        # Optional debug text next to frame txt files
        roll_txt = rotated_dir / frame_path.with_suffix(".txt").name
        roll_txt.write_text(
            f"avg_x={avg_x}\n"
            f"target_angle_degrees={target_angle}\n"
            f"smoothed_angle_degrees={smoothed_angle}\n",
            encoding="utf-8",
        )

        if index % 100 == 0:
            print(
                f"Rotate: {index + 1}/{len(flows)} "
                f"target={target_angle:.2f} smooth={smoothed_angle:.2f}"
            )


# =========================
# MAIN
# =========================

def main():
    video_path = pathlib.Path(VIDEO_FILE)
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    if not pathlib.Path(FFMPEG_EXE).exists():
        raise FileNotFoundError(FFMPEG_EXE)

    output_dir = get_output_dir(video_path)
    frames_dir = output_dir / "frames"
    frames_indicator_dir = output_dir / "frames_indicator"
    final_video = output_dir / "with_indicator.mp4"
    rotated_dir = output_dir / "rotated"
    rollercoaster_video = output_dir / "rollercoaster.mp4"

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output directory: {output_dir}")

    fps = get_video_fps(video_path)
    print(f"Detected FPS: {fps}")

    if not args.skip_extract:
        print("\n🎞️ Extracting frames...")
        if frames_dir.exists():
            #shutil.rmtree(frames_dir)
            pass
        extract_frames(video_path, frames_dir)
    else:
        print("\n⏭️ Skipping frame extraction")

    if not args.skip_flow:
        print("\n🌀 Calculating optical flow...")
        flows, max_abs_x = calculate_optical_flow(frames_dir)
    else:
        print("\n⏭️ Skipping optical flow calculation")
        flows, max_abs_x = load_optical_flow_from_txt(frames_dir)

    if not args.skip_indicator:
        print("\n🟩 Drawing indicators...")
        if frames_indicator_dir.exists():
            #shutil.rmtree(frames_indicator_dir)
            pass
        draw_indicator_frames(flows, max_abs_x, frames_indicator_dir)
    else:
        print("\n⏭️ Skipping indicator drawing")

    if not args.skip_assemble:
        print("\n🎬 Reassembling video...")
        assemble_video(video_path, frames_indicator_dir, final_video, fps)
    else:
        print("\n⏭️ Skipping video assembly")

    if not args.skip_rotate:
        print("\n🎢 Creating rollercoaster rotated frames...")
        if rotated_dir.exists():
            #shutil.rmtree(rotated_dir)
            pass
        create_rotated_frames(
            flows,
            max_abs_x,
            rotated_dir,
            args.max_roll_degrees,
            args.roll_smoothing,
        )
    else:
        print("\n⏭️ Skipping rollercoaster rotation")

    if not args.skip_rollercoaster_assemble:
        print("\n🎬 Assembling rollercoaster video...")
        assemble_video(video_path, rotated_dir, rollercoaster_video, fps)
    else:
        print("\n⏭️ Skipping rollercoaster video assembly")

    print("\n✅ Done!")
    print(final_video)


if __name__ == "__main__":
    main()
