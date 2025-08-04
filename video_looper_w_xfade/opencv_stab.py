import os
import shutil
import subprocess
import cv2
import numpy as np

def stabilize_to_first_frame(video_path, output_path="stabilized_input.mp4", frames_dir="stab_frames", ref_idx = -2):
    # Step 1: Prepare frames directory
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
    os.makedirs(frames_dir)

    print("Using OpenCV to stabilize, extracting all frames with FFmpeg")

    # Step 2: Extract all frames with FFmpeg
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-qscale:v", "2",  # good quality
        os.path.join(frames_dir, "frame_%06d.png")
    ], check=True)

    # Step 3: Load nth frame as reference
    frame_files = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
    if not frame_files:
        raise RuntimeError("No frames extracted.")

    if ref_idx < -1:
        ref_idx = len(frame_files) // 2

    ref_path = os.path.join(frames_dir, frame_files[ref_idx])
    ref_img = cv2.imread(ref_path)
    ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(1000)

    kp_ref, des_ref = orb.detectAndCompute(ref_gray, None)

    print(f"Processing frame files for motion extraction ({len(frame_files)} files)")
    i = 0

    # Step 4: Store transforms
    M_list = []
    for fname in frame_files:
        i += 1
        if (i % 10) == 0:
            print(f"{i}", end="", flush=True)
        else:
            print(f".", end="", flush=True)
        frame_path = os.path.join(frames_dir, fname)
        img = cv2.imread(frame_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        kp, des = orb.detectAndCompute(gray, None)
        if des is None or len(kp) < 10:
            M_list.append(np.eye(2, 3, dtype=np.float32))
            continue

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(des, des_ref)
        if len(matches) < 10:
            M_list.append(np.eye(2, 3, dtype=np.float32))
            continue

        matches = sorted(matches, key=lambda x: x.distance)[:100]
        src_pts = np.float32([kp[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp_ref[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

        M, _ = cv2.estimateAffinePartial2D(src_pts, dst_pts)
        if M is None:
            M = np.eye(2, 3, dtype=np.float32)

        M = remove_scaling(M)  # Keep only rotation + translation
        M_list.append(M)

    # Step 5: Smooth transforms
    print(f"\nSmoothing transforms...", end="", flush=True)
    M_list_smoothed = smooth_transforms(M_list, alpha=0.95)

    print(f"Done!\nProcessing frame files for transform application ({len(frame_files)} files)")
    i = 0

    # Step 6: Apply smoothed transforms
    for fname, M in zip(frame_files, M_list_smoothed):
        i += 1
        if (i % 10) == 0:
            print(f"{i}", end="", flush=True)
        else:
            print(f".", end="", flush=True)
        frame_path = os.path.join(frames_dir, fname)
        img = cv2.imread(frame_path)
        aligned = cv2.warpAffine(img, M, (ref_img.shape[1], ref_img.shape[0]),
                                 flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)
        cv2.imwrite(frame_path, aligned)

    # Step 5: Assemble frames back into video
    subprocess.run([
        "ffmpeg", "-y", "-framerate", "30",
        "-i", os.path.join(frames_dir, "frame_%06d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        output_path
    ], check=True)

    print(f"\n✅ Stabilized video saved to {output_path}")

def smooth_transforms(M_list, alpha=0.9):
    """Low-pass filter the affine matrices in M_list."""
    smoothed = []
    prev = None
    for M in M_list:
        if prev is None:
            prev = M.copy()
        else:
            prev = alpha * prev + (1 - alpha) * M
        smoothed.append(prev.copy())
    return smoothed

def remove_scaling(M):
    # Extract rotation-translation components
    a, b = M[0, 0], M[0, 1]
    c, d = M[1, 0], M[1, 1]
    # Compute pure rotation matrix part
    scale = np.sqrt(a*a + c*c)
    if scale != 0:
        a /= scale
        b /= scale
        c /= scale
        d /= scale
    # Put back into affine matrix
    M_no_scale = np.array([[a, b, M[0, 2]],
                           [c, d, M[1, 2]]], dtype=np.float32)
    return M_no_scale
