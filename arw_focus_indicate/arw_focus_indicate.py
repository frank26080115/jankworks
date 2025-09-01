#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sony A1 Mark II focus overlays (v10)

- Uses TWO exiftool calls:
    * Numeric (-j -n): ImageWidth, ImageHeight, FocusLocation, FocusLocation2,
                       FlexibleSpotPosition, FocusFrameSize
    * Text    (-j   ): AFAreaMode, AFAreaModeSetting, AFTracking,
                       AFPointsUsed, AFPointSelected, SceneMode

- AI keyword rule (case-insensitive):
    human, animal, bird, insect, car, train, plane, airplane
  If any appears in the text fields → treat as AI used and center the rectangle on FocusLocation.
  Else → center on FlexibleSpotPosition.

- Overlays:
    * FocusLocation/2: YELLOW circle (radius=25 px) at scaled (cx,cy) from (imgW,imgH,cx,cy)
    * Rectangle size from FocusFrameSize (FULL-RES px) scaled to preview via (pw/full_w, ph/full_h)
    * Rectangle center chosen per AI rule (FocusLocation if AI, else FlexibleSpotPosition)

- Footer: +200 px black strip with ~20 pt white debug lines.

Requirements:
  - Windows with `exiftool-nopause.exe` in PATH
  - Python 3.9+
  - Pillow:  pip install pillow

Usage:
  python focus_indicate.py "C:\\path\\to\\folder"
"""

import argparse
import io
import json
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

EXIFTOOL = "exiftool-nopause.exe"

# -------------------- ExifTool helpers --------------------

NUMERIC_TAGS = [
    "ImageWidth", "ImageHeight",
    "FocusLocation", "FocusLocation2",
    "FlexibleSpotPosition",
    "FocusFrameSize",
]

TEXT_TAGS = [
    # NOTE: no spaces here, exactly as requested
    "AFAreaMode",
    "AFAreaModeSetting",
    "AFTracking",
    "AFPointsUsed",
    "AFPointSelected",
    "SceneMode",
]

AI_KEYWORDS = ["human", "animal", "bird", "insect", "car", "train", "plane", "airplane"]

def run_exiftool_numeric(file_path: Path) -> dict:
    cmd = [EXIFTOOL, "-j", "-n"] + [f"-{t}" for t in NUMERIC_TAGS] + [str(file_path)]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"exiftool numeric failed: {file_path}\n{p.stderr.decode('utf-8','ignore')}")
    arr = json.loads(p.stdout.decode("utf-8", "replace"))
    return arr[0] if arr else {}

def run_exiftool_text(file_path: Path) -> dict:
    cmd = [EXIFTOOL, "-j"] + [f"-{t}" for t in TEXT_TAGS] + [str(file_path)]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"exiftool text failed: {file_path}\n{p.stderr.decode('utf-8','ignore')}")
    arr = json.loads(p.stdout.decode("utf-8", "replace"))
    return arr[0] if arr else {}

def extract_preview_bytes(file_path: Path) -> bytes:
    cmd = [EXIFTOOL, "-b", "-PreviewImage", str(file_path)]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"extract preview failed: {file_path}\n{p.stderr.decode('utf-8','ignore')}")
    return p.stdout

# -------------------- Parsing helpers --------------------

_num_pat = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

def parse_nums_2(val) -> Optional[Tuple[float, float]]:
    if val is None:
        return None
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return float(val[0]), float(val[1])
        except Exception:
            return None
    if isinstance(val, str):
        nums = _num_pat.findall(val)
        if len(nums) >= 2:
            return float(nums[0]), float(nums[1])
    return None

def parse_nums_4(val) -> Optional[Tuple[float, float, float, float]]:
    if val is None:
        return None
    if isinstance(val, (list, tuple)) and len(val) >= 4:
        try:
            return float(val[0]), float(val[1]), float(val[2]), float(val[3])
        except Exception:
            return None
    if isinstance(val, str):
        nums = _num_pat.findall(val)
        if len(nums) >= 4:
            return float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3])
    return None

def parse_focus_frame_size(val) -> Optional[Tuple[int, int]]:
    """Accepts 'WxH', 'W x H', or two numbers."""
    if val is None:
        return None
    if isinstance(val, str):
        m = re.match(r"\s*(\d+)\s*[xX]\s*(\d+)\s*$", val)
        if m:
            return int(m.group(1)), int(m.group(2))
        nums = _num_pat.findall(val)
        if len(nums) >= 2:
            return int(float(nums[0])), int(float(nums[1]))
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return int(float(val[0])), int(float(val[1]))
        except Exception:
            return None
    return None

# -------------------- Drawing helpers --------------------

def clamp_int(v, lo, hi):
    return max(lo, min(int(round(v)), hi))

def draw_circle(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float, color, pw: int, ph: int, width: int = 4):
    left = clamp_int(cx - radius, 0, pw - 1)
    top = clamp_int(cy - radius, 0, ph - 1)
    right = clamp_int(cx + radius, 0, pw - 1)
    bottom = clamp_int(cy + radius, 0, ph - 1)
    draw.ellipse([left, top, right, bottom], outline=color, width=width)

def draw_rect_centered(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color, pw: int, ph: int, width: int = 4):
    left   = clamp_int(cx - w/2.0, 0, pw - 1)
    top    = clamp_int(cy - h/2.0, 0, ph - 1)
    right  = clamp_int(cx + w/2.0, 0, pw - 1)
    bottom = clamp_int(cy + h/2.0, 0, ph - 1)
    draw.rectangle([left, top, right, bottom], outline=color, width=width)

def load_font(size=20) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

# -------------------- Heuristics --------------------

def scale_fsp_to_preview(x: float, y: float, pw: int, ph: int) -> Tuple[float, float, str]:
    """
    FlexibleSpotPosition scaler:
      - normalized (<=1.5) -> (x*pw, y*ph)
      - 640x480 grid       -> (x*pw/640, y*ph/480)
      - else               -> assume preview px
    """
    if 0 <= x <= 1.5 and 0 <= y <= 1.5:
        return x * pw, y * ph, "normalized→preview"
    if 0 <= x <= 640 and 0 <= y <= 480:
        return x * (pw / 640.0), y * (ph / 480.0), "640x480→preview"
    return x, y, "assume preview px"

def ai_used_from_text_tags(text_tags: dict) -> Tuple[bool, str]:
    """
    Scan only the *text* exif dict for AI/subject keywords.
    Keys are expected as no-space names like 'AFAreaMode'.
    """
    for key, val in text_tags.items():
        if val is None:
            continue
        s = str(val).lower()
        for kw in AI_KEYWORDS:
            if kw in s:
                return True, f"{key} contains '{kw}'"
    return False, "no AI keywords found"

# -------------------- Core processing --------------------

def process_arw(file_path: Path, out_dir: Path, verbose: bool = True):
    # Preview image
    jpg = extract_preview_bytes(file_path)
    preview = Image.open(io.BytesIO(jpg)).convert("RGB")
    pw, ph = preview.size
    draw = ImageDraw.Draw(preview)

    # Metadata
    num = run_exiftool_numeric(file_path)
    txt = run_exiftool_text(file_path)

    full_w = int(num.get("ImageWidth") or 0) or None
    full_h = int(num.get("ImageHeight") or 0) or None

    lines = [
        f"File: {file_path.name}",
        f"Preview: {pw}x{ph}  Full: {full_w}x{full_h}",
    ]

    # FocusLocation / 2 → yellow circles at scaled centers
    def draw_focus(tag_name: str) -> Optional[Tuple[float, float]]:
        raw = parse_nums_4(num.get(tag_name))
        if not raw:
            lines.append(f"{tag_name}: <missing>")
            return None
        imgW, imgH, cx, cy = raw
        if not imgW or not imgH or imgW <= 1 or imgH <= 1:
            imgW, imgH = (full_w or pw), (full_h or ph)
        sx, sy = pw / float(imgW), ph / float(imgH)
        px, py = cx * sx, cy * sy
        draw_circle(draw, px, py, 25, (255, 230, 0), pw, ph, width=4)
        lines.append(f"{tag_name}: img({int(imgW)}x{int(imgH)}) center=({cx:.1f},{cy:.1f}) -> ({px:.1f},{py:.1f})")
        return px, py

    focus1 = draw_focus("FocusLocation")
    focus2 = draw_focus("FocusLocation2")
    focus_center = focus1 or focus2

    # FlexibleSpotPosition center candidate
    fsp = parse_nums_2(num.get("FlexibleSpotPosition"))
    fsp_center = None
    if fsp:
        fx, fy = fsp
        fsp_cx, fsp_cy, fsp_mode = scale_fsp_to_preview(fx, fy, pw, ph)
        fsp_center = (fsp_cx, fsp_cy)
        lines.append(f"FlexibleSpotPosition: raw=({fx:.1f},{fy:.1f}) pos=({fsp_cx:.1f},{fsp_cy:.1f}) [{fsp_mode}]")
    else:
        lines.append("FlexibleSpotPosition: <missing>")

    # FocusFrameSize → rectangle size (scaled full→preview)
    rect_w = rect_h = None
    ffs = parse_focus_frame_size(num.get("FocusFrameSize"))
    if ffs and full_w and full_h:
        rw_full, rh_full = ffs
        rect_w = rw_full * (pw / float(full_w))
        rect_h = rh_full * (ph / float(full_h))
        lines.append(f"FocusFrameSize: full={rw_full}x{rh_full} -> preview={rect_w:.1f}x{rect_h:.1f}")
    else:
        lines.append("FocusFrameSize: <missing or cannot scale>")

    # AI keyword detection (from TEXT tags)
    ai_used, ai_note = ai_used_from_text_tags(txt)
    lines.append(f"AI detect: {'YES' if ai_used else 'NO'} ({ai_note})")

    # Choose center & draw rectangle
    if rect_w and rect_h:
        if ai_used and focus_center:
            cx, cy = focus_center
            center_src = "FocusLocation (AI)"
        elif fsp_center:
            cx, cy = fsp_center
            center_src = "FlexibleSpotPosition (non-AI)"
        elif focus_center:
            cx, cy = focus_center
            center_src = "FocusLocation (fallback)"
        else:
            cx, cy = pw / 2.0, ph / 2.0
            center_src = "image center (fallback)"
        draw_rect_centered(draw, cx, cy, rect_w, rect_h, (170, 170, 170), pw, ph, width=4)
        lines.append(f"Rect center: ({cx:.1f},{cy:.1f}) via {center_src}")
    else:
        lines.append("Rect: <not drawn> (missing size)")

    # Footer (200 px black, ~20 pt text)
    footer_h = 200
    out = Image.new("RGB", (pw, ph + footer_h), (0, 0, 0))
    out.paste(preview, (0, 0))
    fdraw = ImageDraw.Draw(out)
    font = load_font(20)
    y = ph + 10
    for line in lines:
        fdraw.text((10, y), line, font=font, fill=(255, 255, 255))
        y += 28

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{file_path.stem}-focusindicate.jpg"
    out.save(out_path, "JPEG", quality=95)
    if verbose:
        print("->", out_path)

# -------------------- CLI --------------------

def main():
    ap = argparse.ArgumentParser(description="Overlay Sony A1m2 focus markers on preview JPEGs (v10).")
    ap.add_argument("directory", type=str, help="Directory containing .ARW files")
    ap.add_argument("--quiet", action="store_true", help="Less logging")
    args = ap.parse_args()

    base = Path(args.directory).expanduser().resolve()
    if not base.is_dir():
        raise SystemExit(f"Not a directory: {base}")

    out_dir = base / "focusindicate"
    files = sorted(base.glob("*.ARW"))
    if not files:
        print("No .ARW files found.")
        return

    for p in files:
        try:
            process_arw(p, out_dir, verbose=not args.quiet)
        except Exception as e:
            print(f"[!] Error {p.name}: {e}")

if __name__ == "__main__":
    main()
