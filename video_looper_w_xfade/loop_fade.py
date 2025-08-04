import argparse
import subprocess
import os
import pathlib
import opencv_fade

def run_ffmpeg(cmd):
    print("Running:", ' '.join(cmd))
    subprocess.run(cmd, check=True)

def stabilize_video(input_file, stabilized_file, locked = False):
    print(f"Performing stabilization, analyzing motion...")
    tf_file = "transforms.trf"
    if os.path.exists(tf_file):
        os.remove(tf_file)
    # Generate transform file
    run_ffmpeg([
        "ffmpeg", "-y", "-i", input_file,
        "-vf", f"vidstabdetect=shakiness=10:accuracy=15:result={tf_file}",
        "-f", "null", "-"
    ])
    print(f"Performing stabilization, applying transformation...")
    # Apply transforms
    run_ffmpeg([
        "ffmpeg", "-y", "-i", input_file,
        "-vf",
        f"vidstabtransform=input={tf_file}:smoothing=100:maxshift=40:maxangle=2:zoom=0.98:optzoom=1:interpol=bicubic" if not locked else
        f"vidstabtransform=input={tf_file}:smoothing=0:maxshift=400:maxangle=3:zoom=1:optzoom=0:tripod=1:interpol=bicubic",
        "-c:a", "copy", stabilized_file
    ])
    print(f"Stabilization Complete")

def extract_segments(input_file, start_time, end_time, loop_len, mute=False):
    for f in ["start_1s.mp4", "middle.mp4", "end_1s.mp4", "crossfade.mp4"]:
        if os.path.exists(f):
            os.remove(f)

    def audio_flags():
        return ["-an"] if mute else ["-c", "copy"]

    loop_len = float(time_to_seconds(loop_len))

    run_ffmpeg([
        "ffmpeg", "-y", "-ss", start_time, "-t", f"{loop_len}",
        "-i", input_file, *audio_flags(), "start_1s.mp4"
    ])

    t2 = time_to_seconds(end_time) - loop_len

    run_ffmpeg([
        "ffmpeg", "-y", "-ss", f"{t2}", "-i", input_file, "-t", f"{loop_len}",
        *audio_flags(), "end_1s.mp4"
    ])
    middle_start = str(float(time_to_seconds(start_time)) + loop_len)
    middle_duration = str(float(time_to_seconds(end_time)) - float(time_to_seconds(start_time)) - (2*loop_len))
    run_ffmpeg([
        "ffmpeg", "-y", "-ss", middle_start, "-t", middle_duration,
        "-i", input_file, *audio_flags(), "middle.mp4"
    ])

def crossfade_chunks(duration, size=None, framerate=None, bitrate=None, mute=False):
    vf_filters = []
    if size:
        vf_filters.append(f"scale={size}")
    if framerate:
        vf_filters.append(f"fps={framerate}")

    vf_filter_str = f"xfade=transition=fade:duration={duration}:offset=0"
    if vf_filters:
        vf_filter_str += "," + ",".join(vf_filters)
    vf_filter_str += ",format=yuv420p"

    if mute:
        # Only process video
        cmd = [
            "ffmpeg", "-y",
            "-i", "end_1s.mp4", "-i", "start_1s.mp4",
            "-filter_complex", f"[0:v][1:v]{vf_filter_str}[v]",
            "-map", "[v]",
            "crossfade.mp4"
        ]
    else:
        # Process video and audio separately
        cmd = [
            "ffmpeg", "-y",
            "-i", "end_1s.mp4", "-i", "start_1s.mp4",
            "-filter_complex",
            f"[0:v][1:v]{vf_filter_str}[v];"
            f"[0:a][1:a]acrossfade=d=1:c1=tri:c2=tri[a]",
            "-map", "[v]", "-map", "[a]",
            "crossfade.mp4"
        ]

    if bitrate:
        cmd.insert(-1, bitrate)
        cmd.insert(-1, "-b:v")

    run_ffmpeg(cmd)

def concat_chunks_mp4(output_file):
    with open("concat_list.txt", "w") as f:
        for name in ["middle.mp4", "crossfade.mp4"]:
            f.write(f"file '{name}'\n")

    run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "concat_list.txt", "-c", "copy", output_file
    ])
    os.remove("concat_list.txt")

def convert_to_webm(source_mp4, output_file):
    run_ffmpeg([
        "ffmpeg", "-y", "-i", source_mp4,
        "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30",
        "-an", output_file
    ])
    os.remove(source_mp4)

def convert_to_apng(source_mp4, output_file):
    os.makedirs("frames_apng", exist_ok=True)
    run_ffmpeg(["ffmpeg", "-y", "-i", source_mp4, "frames_apng/frame_%04d.png"])
    run_ffmpeg(["ffmpeg", "-y", "-framerate", "30", "-i", "frames_apng/frame_%04d.png", output_file])
    for f in pathlib.Path("frames_apng").glob("*.png"):
        f.unlink()
    os.rmdir("frames_apng")
    os.remove(source_mp4)

def enforce_extension(path: str, ext: str) -> str:
    ext = ext.lower()
    path = pathlib.Path(path)
    return str(path.with_suffix(f".{ext}"))

def time_to_seconds(tstr):
    if isinstance(tstr, (int, float)):
        return float(tstr)

    parts = tstr.strip().split(":")
    parts = [float(p) for p in parts]

    if len(parts) == 1:
        return parts[0]  # seconds
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]  # MM:SS
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]  # HH:MM:SS
    else:
        raise ValueError(f"Unrecognized time format: {tstr}")

def main():
    parser = argparse.ArgumentParser(description="Create a seamless video loop with crossfade")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("--start", default="0", help="Start time (seconds or HH:MM:SS)")
    parser.add_argument("--end", required=True, help="End time (seconds or HH:MM:SS)")
    parser.add_argument("--looplen", default="1", help="Loop length (seconds)")
    parser.add_argument("--output", default="output.mp4", help="Output filename")
    parser.add_argument("--bitrate", help="Target bitrate (e.g. 2000k)")
    parser.add_argument("--size", help="Output resolution (e.g. 1280x720)")
    parser.add_argument("--framerate", help="Output framerate (e.g. 30)")
    #parser.add_argument("--mute", action="store_true", help="Remove audio from final output")
    parser.add_argument("--format", choices=["mp4", "webm", "apng"], default="mp4",
                        help="Final output format (default: mp4)")
    parser.add_argument("--stabilize", action="store_true", help="Stabilize the input video before processing (loose)")
    parser.add_argument("--stabilize_locked", action="store_true", help="Stabilize the input video before processing (locked)")
    parser.add_argument("--opencv_stab", action="store_true", help="Stabilize the input video, with OpenCV, before processing (locked)")

    args = parser.parse_args()
    output_file = enforce_extension(args.output, args.format)

    working_input = args.input
    if args.stabilize or args.stabilize_locked or args.opencv_stab:
        stabilized_file = "stabilized_input.mp4"
        if os.path.exists(stabilized_file):
            os.remove(stabilized_file)
        if not args.opencv_stab:
            stabilize_video(args.input, stabilized_file, locked = args.stabilize_locked)
        else:
            import opencv_stab
            stabilized_file_2 = "ocv_stab.mp4"
            if os.path.exists(stabilized_file_2):
                os.remove(stabilized_file_2)
            opencv_stab.stabilize_to_first_frame(working_input, stabilized_file_2)
            stabilize_video(stabilized_file_2, stabilized_file, locked = False)
        working_input = stabilized_file

    extract_segments(working_input, args.start, args.end, args.looplen, mute=True)
    #crossfade_chunks(args.looplen, size=args.size, framerate=args.framerate,
    #                 bitrate=args.bitrate, mute=True)

    opencv_fade.extract_frames("start_1s.mp4", "start_frames", "start")
    opencv_fade.extract_frames("end_1s.mp4", "end_frames", "end")
    opencv_fade.align_and_blend_frames("start_frames", "end_frames", "xfade_frames")
    opencv_fade.assemble_crossfade("xfade_frames", "crossfade.mp4")

    temp_file = "temp_final.mp4"
    concat_chunks_mp4(temp_file)

    if args.format == "mp4":
        if os.path.exists(output_file):
            os.remove(output_file)
        os.rename(temp_file, output_file)
    elif args.format == "webm":
        convert_to_webm(temp_file, output_file)
    elif args.format == "apng":
        convert_to_apng(temp_file, output_file)

    print(f"✅ Done. Output saved to {output_file}")

if __name__ == "__main__":
    main()
