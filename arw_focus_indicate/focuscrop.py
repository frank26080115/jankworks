import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import rawpy

def run_exiftool_focus_location(path: Path):
    """
    Returns (x, y) from FocusLocation.
    The tag has 4 numbers; only the LAST TWO are the focus spot in full-image pixel coords.
    """
    cmd = ["exiftool-nopause.exe", "-j", "-n", "-FocusLocation", str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not res.stdout.strip():
        raise RuntimeError(f"ExifTool failed or empty output:\n{res.stderr}")

    data = json.loads(res.stdout)
    if not data or "FocusLocation" not in data[0]:
        raise RuntimeError("FocusLocation not found in metadata.")

    val = data[0]["FocusLocation"]

    # Accept formats like "a b c d" string, list of numbers, or "a,b,c,d"
    if isinstance(val, str):
        tokens = val.replace(",", " ").split()
        nums = [float(t) for t in tokens if t.replace(".", "", 1).replace("-", "", 1).isdigit()]
    elif isinstance(val, (list, tuple)):
        nums = [float(x) for x in val]
    else:
        raise RuntimeError(f"Unrecognized FocusLocation format: {type(val)}")

    if len(nums) < 4:
        raise RuntimeError(f"FocusLocation has fewer than 4 numbers: {nums}")

    x = int(round(nums[-2]))
    y = int(round(nums[-1]))
    w = int(round(nums[0]))
    h = int(round(nums[1]))
    return w, h, x, y


# WARNING: not used, too slow
def demosaic_full(path: Path):
    """
    Demosaic at full size so FocusLocation (full-image coords) maps 1:1.
    """
    with rawpy.imread(str(path)) as rp:
        rgb = rp.postprocess(
            use_auto_wb=True,
            no_auto_bright=True,
            output_bps=8,
            gamma=(2.2, 4.5),
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
        )
    # rawpy returns RGB in uint8; convert to BGR for OpenCV IO
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return bgr

# WARNING: kinda works, green tint
def demosaic_aoi_bilinear(raw, x, y, w, h):
    """
    Demosaic only an Area Of Interest from a rawpy RawPy object.
    (x,y,w,h) are in the visible-raw coordinate system.
    Returns an 8-bit BGR image (NumPy array).
    """
    # Align AOI to even pixels for 2x2 CFA tiles
    x0 = max(0, (x // 2) * 2)
    y0 = max(0, (y // 2) * 2)
    x1 = min(raw.raw_image_visible.shape[1], ((x + w + 1) // 2) * 2)
    y1 = min(raw.raw_image_visible.shape[0], ((y + h + 1) // 2) * 2)

    # Extract Bayer patch
    M = raw.raw_image_visible[y0:y1, x0:x1].astype(np.float32)

    # Determine CFA pattern (0=R,1=G,2=B; raw_pattern is 2x2)
    pat = raw.raw_pattern  # shape (2,2)
    # Build channel masks
    H, W = M.shape
    yy, xx = np.indices(M.shape)
    ch_idx = pat[yy % 2, xx % 2]  # map each pixel to 0/1/2

    # Per-channel black/white levels
    black = raw.black_level_per_channel  # 4 elems typical
    # Map black level per pixel using CFA channel map
    blmap = np.choose(ch_idx, [black[0], black[1], black[2], black[3] if len(black)>3 else black[1]]).astype(np.float32)
    M -= blmap
    M = np.clip(M, 0, raw.white_level)

    # Split channels via masks
    Rm = np.where(ch_idx == 0, M, 0.0)
    Gm = np.where(ch_idx == 1, M, 0.0)
    Bm = np.where(ch_idx == 2, M, 0.0)

    # Simple bilinear interpolation using box filters
    k = np.array([[1,2,1],
                  [2,4,2],
                  [1,2,1]], dtype=np.float32)
    k /= k.sum()

    def interp_plane(plane):
        # Average from sparse samples
        num = cv2.filter2D(plane, -1, k, borderType=cv2.BORDER_REPLICATE)
        den = cv2.filter2D((plane>0).astype(np.float32), -1, k, borderType=cv2.BORDER_REPLICATE)
        den = np.maximum(den, 1e-6)
        return num / den

    R = interp_plane(Rm)
    G = interp_plane(Gm)
    B = interp_plane(Bm)

    # Pack to 8-bit BGR (sRGB-ish without a gamma; optional gamma for looks)
    # Optional simple gamma
    gamma = 1/2.2
    Wlvl = float(raw.white_level)
    rgb = np.stack([R, G, B], axis=-1) / Wlvl
    rgb = np.power(np.clip(rgb, 0, 1), gamma)
    bgr8 = (rgb[..., ::-1] * 255.0 + 0.5).astype(np.uint8)

    return bgr8, (x0, y0, x1 - x0, y1 - y0)

# WARNING: DOESN'T WORK, ALL WHITE RESULT
def demosaic_aoi_bilinear_fixed(raw, x, y, w, h, use_camera_wb=True, gamma=1/2.2):
    """
    Demosaic only an Area Of Interest from a rawpy RawPy object with
    correct per-channel black-level handling, two-green merge, and WB gains.

    (x,y,w,h) are in the visible-raw coordinate system.
    Returns an 8-bit BGR image and the actual aligned rect.
    """
    # 1) Align AOI to 2x2 CFA tiles
    x0 = max(0, (x // 2) * 2)
    y0 = max(0, (y // 2) * 2)
    x1 = min(raw.raw_image_visible.shape[1], ((x + w + 1) // 2) * 2)
    y1 = min(raw.raw_image_visible.shape[0], ((y + h + 1) // 2) * 2)

    M = raw.raw_image_visible[y0:y1, x0:x1].astype(np.float32)

    # 2) CFA pattern map (0=R,1=G,2=B,3=G) per LibRaw/RawPy
    pat = raw.raw_pattern  # shape (2,2), values in {0,1,2,3}
    H, W = M.shape
    yy, xx = np.indices(M.shape)
    ch_idx = pat[yy % 2, xx % 2]  # per-pixel channel index

    # 3) Per-channel black/white
    # black_level_per_channel typically has 4 entries (RGGB order matching pattern indices).
    blc = np.array(raw.black_level_per_channel, dtype=np.float32)
    wl = float(raw.white_level)

    # Subtract per-pixel black level
    blmap = np.choose(ch_idx, blc[:4])
    M = np.clip(M - blmap, 0, wl)

    # 4) Split sparse planes (two distinct green planes)
    Rm = np.where(ch_idx == 0, M, 0.0)
    Gm1 = np.where(ch_idx == 1, M, 0.0)  # one green site
    Gm2 = np.where(ch_idx == 3, M, 0.0)  # the other green site
    Bm = np.where(ch_idx == 2, M, 0.0)

    # 5) Bilinear interpolation via normalized box filter
    k = np.array([[1,2,1],
                  [2,4,2],
                  [1,2,1]], dtype=np.float32)
    k /= k.sum()

    def interp_plane(plane):
        num = cv2.filter2D(plane, -1, k, borderType=cv2.BORDER_REPLICATE)
        den = cv2.filter2D((plane > 0).astype(np.float32), -1, k, borderType=cv2.BORDER_REPLICATE)
        den = np.maximum(den, 1e-6)
        return num / den

    R = interp_plane(Rm)
    G1 = interp_plane(Gm1)
    G2 = interp_plane(Gm2)
    G = 0.5*(G1 + G2)  # merge the two green sites
    B = interp_plane(Bm)

    # 6) White balance gains (camera or daylight) in RGGB slots
    if use_camera_wb and hasattr(raw, "camera_whitebalance") and raw.camera_whitebalance is not None:
        wb = np.array(raw.camera_whitebalance, dtype=np.float32)  # [R,G1,B,G2] or similar order
    elif hasattr(raw, "daylight_whitebalance") and raw.daylight_whitebalance is not None:
        wb = np.array(raw.daylight_whitebalance, dtype=np.float32)
    else:
        # fallback neutral
        wb = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)

    # Map WB to channels: R uses wb[0], B uses wb[2], G uses mean of the two greens
    R *= wb[0]
    G *= 0.5*(wb[1] + (wb[3] if wb.size > 3 else wb[1]))
    B *= wb[2]

    # 7) Normalize to 0..1 using white level minus mean black (simple, stable)
    # (We already subtracted per-pixel black; this keeps overall scale consistent.)
    denom = max(wl - float(np.mean(blc[:min(4, blc.size)])), 1.0)
    rgb = np.stack([R, G, B], axis=-1) / denom
    rgb = np.clip(rgb, 0.0, 1.0)

    # 8) Optional simple gamma-to-display (not a full color transform)
    if gamma is not None:
        rgb = np.power(rgb, gamma)

    bgr8 = (rgb[..., ::-1] * 255.0 + 0.5).astype(np.uint8)
    return bgr8, (x0, y0, x1 - x0, y1 - y0)


# actually a good result
def demosaic_aoi_bilinear_safe(raw, x, y, w, h, use_camera_wb=True, apply_gamma=True):
    """
    Demosaic an AOI from a rawpy.RawPy object with sane scaling:
    - Correct CFA mapping via raw.color_desc
    - Per-channel black subtraction
    - Bilinear interpolation
    - WB gains normalized so green ≈ 1
    - Exposure scale via p99.5 to avoid whiteouts

    Returns: bgr8 (uint8), (x0,y0,w0,h0)
    """
    # --- 1) Align AOI to 2x2 tiles
    x0 = max(0, (x // 2) * 2)
    y0 = max(0, (y // 2) * 2)
    x1 = min(raw.raw_image_visible.shape[1], ((x + w + 1) // 2) * 2)
    y1 = min(raw.raw_image_visible.shape[0], ((y + h + 1) // 2) * 2)

    M = raw.raw_image_visible[y0:y1, x0:x1].astype(np.float32)
    H, W = M.shape

    # --- 2) CFA mapping (0..3 indexes into color_desc, e.g. 'RGBG' or 'GRBG')
    pat = raw.raw_pattern  # 2x2 of 0..3
    cdesc = raw.color_desc.decode() if isinstance(raw.color_desc, bytes) else raw.color_desc  # e.g. 'RGBG'
    # Make a table: index -> 'R'/'G'/'B'
    idx2ch = [cdesc[i] for i in range(len(cdesc))]  # length 3 or 4
    yy, xx = np.indices(M.shape)
    idx_map = pat[yy % 2, xx % 2]  # 0..3

    # --- 3) Black/white
    blc = np.array(raw.black_level_per_channel, dtype=np.float32)[:len(idx2ch)]
    wl  = float(raw.white_level)
    bl_per_pixel = np.take(blc, idx_map)
    M = np.clip(M - bl_per_pixel, 0, wl)

    # --- 4) Split sparse planes (respect the two distinct greens if present)
    planes = {}
    for sym in 'RGB':
        mask = np.isin(idx_map, [i for i,c in enumerate(idx2ch) if c == sym])
        planes[sym] = np.where(mask, M, 0.0)

    # If there are two greens, keep both for interpolation fairness
    g_masks = [i for i,c in enumerate(idx2ch) if c == 'G']
    G1 = np.where(idx_map == g_masks[0], M, 0.0) if len(g_masks) >= 1 else np.zeros_like(M)
    G2 = np.where(idx_map == g_masks[1], M, 0.0) if len(g_masks) >= 2 else np.zeros_like(M)

    # --- 5) Bilinear interpolation with normalization
    k = np.array([[1,2,1],[2,4,2],[1,2,1]], np.float32); k /= k.sum()

    def interp(plane):
        num = cv2.filter2D(plane, -1, k, borderType=cv2.BORDER_REPLICATE)
        den = cv2.filter2D((plane>0).astype(np.float32), -1, k, borderType=cv2.BORDER_REPLICATE)
        return num / np.maximum(den, 1e-6)

    R = interp(planes.get('R', np.zeros_like(M)))
    B = interp(planes.get('B', np.zeros_like(M)))
    if len(g_masks) >= 2:
        G = 0.5*(interp(G1) + interp(G2))
    else:
        G = interp(planes.get('G', np.zeros_like(M)))

    # --- 6) White balance (normalize so G≈1)
    # Prefer camera WB; fallback daylight; else neutral.
    if use_camera_wb and getattr(raw, "camera_whitebalance", None) is not None:
        wb_raw = np.array(raw.camera_whitebalance, dtype=np.float32)  # length 3 or 4
    elif getattr(raw, "daylight_whitebalance", None) is not None:
        wb_raw = np.array(raw.daylight_whitebalance, dtype=np.float32)
    else:
        wb_raw = np.array([1.0,1.0,1.0,1.0], dtype=np.float32)

    # Map per symbolic channel by averaging greens if there are two
    # Build R,G,B multipliers with green normalized to 1
    # Find representative greens:
    if len(g_masks) >= 2 and len(wb_raw) >= max(g_masks)+1:
        g_gain = 0.5*(wb_raw[g_masks[0]] + wb_raw[g_masks[1]])
    else:
        # best-effort: any 'G' index or default 1
        g_indices = [i for i,c in enumerate(idx2ch) if c == 'G']
        g_gain = float(np.mean(wb_raw[g_indices])) if g_indices else 1.0

    # Representative R/B gains (first matching index, else 1)
    r_idx = next((i for i,c in enumerate(idx2ch) if c == 'R'), None)
    b_idx = next((i for i,c in enumerate(idx2ch) if c == 'B'), None)
    r_gain = wb_raw[r_idx] if (r_idx is not None and r_idx < len(wb_raw)) else 1.0
    b_gain = wb_raw[b_idx] if (b_idx is not None and b_idx < len(wb_raw)) else 1.0

    # Normalize so G=1
    R *= (r_gain / g_gain)
    G *= 1.0
    B *= (b_gain / g_gain)

    # --- 7) Exposure scale using a robust percentile AFTER WB (pre-gamma)
    rgb = np.stack([R, G, B], axis=-1)

    # Avoid blowing highlights: scale so that p99.5 maps to ~0.9
    p995 = np.percentile(rgb, 99.5)
    scale = 0.9 / max(p995, 1e-6)
    rgb *= scale
    rgb = np.clip(rgb, 0.0, 1.0)

    # --- 8) Optional gamma (simple display gamma; skip for pure scoring)
    if apply_gamma:
        rgb = np.power(rgb, 1/2.2)

    bgr8 = (rgb[..., ::-1] * 255.0 + 0.5).astype(np.uint8)
    return bgr8, (x0, y0, x1 - x0, y1 - y0)


# not used because we are not demosaic'ing the whole image anymore
def clamp_crop_centered(img: np.ndarray, cx: int, cy: int, cw: int = 640, ch: int = 320):
    """
    Center a cw×ch crop at (cx, cy), clamped to image bounds.
    Always returns exactly cw×ch.
    """
    h, w = img.shape[:2]

    # Initial top-left
    x0 = cx - cw // 2
    y0 = cy - ch // 2

    # Clamp so the rectangle stays within bounds
    if x0 < 0:
        x0 = 0
    if y0 < 0:
        y0 = 0
    if x0 + cw > w:
        x0 = max(0, w - cw)
    if y0 + ch > h:
        y0 = max(0, h - ch)

    x1 = x0 + cw
    y1 = y0 + ch

    # Final safety clamp
    x0 = max(0, min(x0, w - cw))
    y0 = max(0, min(y0, h - ch))
    x1 = x0 + cw
    y1 = y0 + ch

    crop = img[y0:y1, x0:x1]
    # Ensure exact size (in rare edge cases of rounding)
    if crop.shape[1] != cw or crop.shape[0] != ch:
        crop = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_AREA)

    return crop, (x0, y0, cw, ch)

def score_sharpness_simple(crop: np.ndarray) -> float:
    """
    Return a sharpness score for the given image crop.
    Uses variance of Laplacian on grayscale.
    Higher = sharper.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return cv2.Laplacian(gray, cv2.CV_32F).var()

def score_sharpness_normalized(crop: np.ndarray) -> float:
    """
    Compute a normalized sharpness score for the given image crop.
    Returns a float between 0 and 1.
    Uses variance of Laplacian normalized by mean intensity and crop size.
    """
    # Convert to grayscale if color
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop

    # Laplacian response
    lap = cv2.Laplacian(gray, cv2.CV_32F)

    # Variance of Laplacian = raw sharpness
    var_lap = lap.var()

    # Normalization factors
    mean_intensity = np.mean(gray) + 1e-6   # avoid divide-by-zero
    num_pixels = gray.size

    # Normalize: scale by intensity and number of pixels
    norm_score = var_lap / (mean_intensity * num_pixels)

    # Clip into 0–1 for comparability
    return float(np.clip(norm_score, 0.0, 1.0))

def main():
    p = argparse.ArgumentParser(description="Make a 640x480 crop centered at Sony FocusLocation (RAW only).")
    p.add_argument("input", help="Path to RAW file (e.g., .ARW)")
    p.add_argument("--ext", default=".jpg", help="Output extension (.jpg or .png). Default: .jpg")
    args = p.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"Input not found: {in_path}")

    # 1) Read focus spot from FocusLocation (last two numbers)
    w, h, fx, fy = run_exiftool_focus_location(in_path)

    # 2) Demosaic RAW at full size
    #img = demosaic_full(in_path)
    #H, W = img.shape[:2]
    W = w
    H = h

    # Sanity clamp focus point to image
    fx = int(max(0, min(fx, W - 1)))
    fy = int(max(0, min(fy, H - 1)))

    # 3) Crop 640x320 centered on FocusLocation
    #crop, rect = clamp_crop_centered(img, fx, fy, 640, 480)
    
    # FocusLocation gives (X, Y, W_full, H_full) where only last two are the spot (full image scale).
    # Suppose you've already mapped that to (cx, cy) center in visible-raw coordinates:
    cx = fx
    cy = fy
    cw = 640
    ch = 480
    x = int(cx - cw // 2)
    y = int(cy - ch // 2)
    with rawpy.imread(str(in_path)) as raw:
        crop, rect = demosaic_aoi_bilinear_safe(raw, x, y, cw, ch)

    # 4) Build output path: sibling directory "focuscrop", filename + ".focuscrop" + ext
    out_dir = in_path.parent / "focuscrop"
    out_dir.mkdir(exist_ok=True)

    out_name = f"{in_path.stem}.focuscrop{args.ext.lower()}"
    out_path = out_dir / out_name

    # 5) Save
    # If JPEG, set decent quality; otherwise let OpenCV defaults handle PNG.
    if args.ext.lower() in [".jpg", ".jpeg"]:
        cv2.imwrite(str(out_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    else:
        cv2.imwrite(str(out_path), crop)
    print(f"saved to {str(out_path)}")

    sharpness = score_sharpness_normalized(crop)
    print(f"sharpness = {sharpness}")

if __name__ == "__main__":
    main()
