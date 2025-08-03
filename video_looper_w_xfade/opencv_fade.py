import os
import shutil
import cv2
import numpy as np
import subprocess

def clear_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)

def extract_frames(video_path, out_dir, label):
    clear_dir(out_dir)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-an",  # mute
        f"{out_dir}/{label}_%04d.png"
    ]
    subprocess.run(cmd, check=True)

def align_and_blend_frames(start_dir, end_dir, out_dir):
    clear_dir(out_dir)

    start_files = sorted([f for f in os.listdir(start_dir) if f.endswith('.png')])
    end_files = sorted([f for f in os.listdir(end_dir) if f.endswith('.png')])

    pair_count = min(len(start_files), len(end_files))
    total_frames = pair_count

    print(f"using OpenCV to blend ({pair_count})...", end="", flush=True)

    for i in range(pair_count):
        alpha = i / (total_frames - 1) if total_frames > 1 else 1

        s_path = os.path.join(start_dir, start_files[i])
        e_path = os.path.join(end_dir, end_files[i])

        start_img = cv2.imread(s_path)
        end_img = cv2.imread(e_path)

        # Warp the end frame to align with the start
        warped_end = align_image(end_img, start_img, alpha)

        # Blend: start fades in over warped end
        blended = cv2.addWeighted(warped_end, 1 - alpha, start_img, alpha, 0)

        j = i + 1

        out_path = os.path.join(out_dir, f"xfade_{j:04d}.png")
        cv2.imwrite(out_path, blended)
        print(f".", end="", flush=True)

    print(f".", flush=True)

    # Handle extra frame if start has one more than end
    if len(start_files) > len(end_files):
        last_frame = cv2.imread(os.path.join(start_dir, start_files[-1]))
        out_path = os.path.join(out_dir, f"xfade_{pair_count:04d}.png")
        cv2.imwrite(out_path, last_frame)

def align_image(src, dst, alpha):
    src_gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    dst_gray = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(500)
    kp1, des1 = orb.detectAndCompute(src_gray, None)
    kp2, des2 = orb.detectAndCompute(dst_gray, None)

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    matches = sorted(matches, key=lambda x: x.distance)[:50]

    if len(matches) < 10:
        return src

    src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

    M, _ = cv2.estimateAffinePartial2D(src_pts, dst_pts)
    if M is None:
        return src

    # Interpolate between identity and full transform
    M_interp = np.array([[1 - alpha, 0, 0],
                         [0, 1 - alpha, 0]], dtype=np.float32) + alpha * M

    aligned = cv2.warpAffine(src, M_interp, (dst.shape[1], dst.shape[0]),
                             flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
    return aligned

import subprocess

def assemble_crossfade(frames_dir="xfade_frames", output="crossfade.mp4", framerate=30):
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(framerate),
        "-i", f"{frames_dir}/xfade_%04d.png",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        output
    ]
    subprocess.run(cmd, check=True)
    print(f"✅ Crossfade video saved to {output}")


# Example usage
if __name__ == "__main__":
    extract_frames("start_1s.mp4", "start_frames", "start")
    extract_frames("end_1s.mp4", "end_frames", "end")
    align_and_blend_frames("start_frames", "end_frames", "xfade_frames")
    assemble_crossfade()
