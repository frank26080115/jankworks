import win32clipboard
import win32con
import pprint
import argparse
import io

import numpy as np
import cv2
from PIL import Image

# Known standard formats
STANDARD_FORMATS = {
    win32con.CF_TEXT: "CF_TEXT",
    win32con.CF_BITMAP: "CF_BITMAP",
    win32con.CF_UNICODETEXT: "CF_UNICODETEXT",
    win32con.CF_DIB: "CF_DIB",
    win32con.CF_DIBV5: "CF_DIBV5",
    win32con.CF_HDROP: "CF_HDROP",
}

def get_format_name(fmt):
    if fmt in STANDARD_FORMATS:
        return STANDARD_FORMATS[fmt]

    try:
        return win32clipboard.GetClipboardFormatName(fmt)
    except:
        return f"UNKNOWN_FORMAT_{fmt}"

def try_decode(data):
    if isinstance(data, bytes):
        for enc in ["utf-8", "utf-16", "latin-1"]:
            try:
                return data.decode(enc)
            except:
                continue
    return data

# --- IMAGE DECODERS ---

def pil_to_cv(img):
    """Convert PIL → OpenCV"""
    img = np.array(img)
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    return img


def show_image(img, title="Clipboard Image"):
    h, w = img.shape[:2]
    channels = img.shape[2] if img.ndim == 3 else 1
    bit_depth = img.dtype

    print(f"\n🖼️ Image Info:")
    print(f"  Resolution: {w} x {h}")
    print(f"  Channels: {channels}")
    print(f"  Bit depth: {bit_depth}")

    cv2.imshow(title, img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def try_parse_image(fmt_name, data):
    """
    Convert clipboard data into OpenCV image (no PIL).
    """

    # --- PNG / JPG / raw encoded formats ---
    if isinstance(data, bytes):
        try:
            np_arr = np.frombuffer(data, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)
            if img is not None:
                return img
        except:
            pass

    # --- CF_DIB / CF_DIBV5 ---
    if fmt_name in ["CF_DIB", "CF_DIBV5"] and isinstance(data, bytes):
        try:
            # Build BMP header
            header_size = 14
            dib_header_size = int.from_bytes(data[0:4], 'little')

            file_size = len(data) + header_size
            offset = header_size + dib_header_size

            bmp_header = (
                b'BM' +
                file_size.to_bytes(4, 'little') +
                b'\x00\x00\x00\x00' +
                offset.to_bytes(4, 'little')
            )

            bmp_data = bmp_header + data

            np_arr = np.frombuffer(bmp_data, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)
            return img

        except Exception as e:
            print(f"⚠️ Failed to parse DIB: {e}")

    # --- CF_BITMAP ---
    if fmt_name == "CF_BITMAP":
        try:
            import win32gui
            import win32ui

            hbitmap = data
            bmp = win32ui.CreateBitmapFromHandle(hbitmap)

            bmpinfo = bmp.GetInfo()
            bmpstr = bmp.GetBitmapBits(True)

            img = np.frombuffer(bmpstr, dtype=np.uint8)

            # Usually BGRA
            img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)

            return img  # keep BGRA, don't drop alpha

        except Exception as e:
            print(f"⚠️ Failed to parse CF_BITMAP: {e}")

    return None


def score_image(img):
    """
    Score image quality:
    - prioritize resolution
    - then bit depth
    - bonus for alpha channel
    """
    h, w = img.shape[:2]
    pixels = w * h

    channels = img.shape[2] if img.ndim == 3 else 1
    dtype_bits = img.dtype.itemsize * 8
    bit_depth = channels * dtype_bits

    alpha_bonus = 1 if (img.ndim == 3 and channels == 4) else 0

    return (pixels, bit_depth, alpha_bonus)


def put_image_on_clipboard(img):
    """
    Put image onto clipboard as:
    - CF_DIBV5 (alpha-compatible bitmap)
    - PNG (lossless original-style format)
    """

    import struct

    # --- Ensure BGRA ---
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    elif img.shape[2] != 4:
        raise ValueError("Unsupported image format")

    height, width = img.shape[:2]

    # --- PNG encoding (lossless, keeps alpha) ---
    success, png_data = cv2.imencode(".png", img)
    if not success:
        raise RuntimeError("Failed to encode PNG")

    png_bytes = png_data.tobytes()

    # --- Flip for DIB ---
    flipped = np.flipud(img)

    bV5Endpoints = bytes(36)

    values = (
        124,                    # bV5Size
        int(width),             # bV5Width (SIGNED)
        int(height),            # bV5Height (SIGNED)
        1,                      # bV5Planes
        32,                     # bV5BitCount
        3,                      # BI_BITFIELDS
        width * height * 4,     # bV5SizeImage
        0,                      # bV5XPelsPerMeter
        0,                      # bV5YPelsPerMeter
        0,                      # bV5ClrUsed
        0,                      # bV5ClrImportant
        0x00FF0000,             # R mask
        0x0000FF00,             # G mask
        0x000000FF,             # B mask
        0xFF000000,             # A mask
        0x73524742,             # 'sRGB'
        bV5Endpoints,           # MUST be bytes
        0,                      # Gamma R
        0,                      # Gamma G
        0,                      # Gamma B
        0,                      # Intent
        0,                      # ProfileData
        0,                      # ProfileSize
        0                       # Reserved
    )

    fmt = '<IiiHHIIiiIIIIIII36sIIIIIII'

    # 🔥 CRITICAL DEBUG LINE
    #print(f"Format expects {fmt.count('I') + fmt.count('i') + fmt.count('H') + fmt.count('s')} fields, we have {len(values)}")

    header = struct.pack(fmt, *values)

    dib_data = header + flipped.tobytes()

    # --- Register PNG format ---
    png_format = win32clipboard.RegisterClipboardFormat("PNG")

    # --- Write to clipboard ---
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()

        # Modern apps prefer this
        win32clipboard.SetClipboardData(png_format, png_bytes)

        # Fallback for everything else
        win32clipboard.SetClipboardData(win32con.CF_DIBV5, dib_data)

    finally:
        win32clipboard.CloseClipboard()


# --- MAIN INSPECTOR ---

def inspect_clipboard(view=False, clean=False):
    results = {}
    found_image = None
    best_image = None
    best_score = None
    best_source = None

    win32clipboard.OpenClipboard()
    try:
        fmt = 0
        while True:
            fmt = win32clipboard.EnumClipboardFormats(fmt)
            if fmt == 0:
                break

            name = get_format_name(fmt)

            try:
                data = win32clipboard.GetClipboardData(fmt)
            except Exception as e:
                data = f"<ERROR: {e}>"

            decoded = try_decode(data)

            results[name] = {
                "format_id": fmt,
                "type": str(type(data)),
                "preview": str(decoded)[:500],
                "raw_length": len(data) if hasattr(data, "__len__") else "N/A"
            }

            # Try to parse image
            if (view or clean):
                img = try_parse_image(name, data)
                if img is not None:
                    score = score_image(img)

                    print(f"\n🔍 Candidate image from {name}:")
                    print(f"   shape={img.shape}, dtype={img.dtype}, score={score}")

                    if best_image is None or score > best_score:
                        best_image = img
                        best_score = score
                        best_source = name

    finally:
        win32clipboard.CloseClipboard()

    found_image = best_image

    print("\n=== CLIPBOARD CONTENTS ===\n")
    pprint.pprint(results, width=120)

    if view or clean:
        if found_image is not None:
            print(f"\n🏆 Selected BEST image source: {best_source} with score {best_score}")

            if view:
                show_image(found_image)

            if clean:
                print("\n🧼 Cleaning clipboard... (removing metadata, keeping only image)")
                put_image_on_clipboard(found_image)
                print("✅ Clipboard now contains ONLY raw image (CF_DIB)")
        else:
            print("\n❌ No usable image format found in clipboard.")

# --- ENTRY POINT ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clipboard inspector with image tools")
    parser.add_argument("--view", action="store_true", help="Display image from clipboard")
    parser.add_argument("--clean", action="store_true", help="Replace clipboard with clean image only")

    args = parser.parse_args()

    inspect_clipboard(view=args.view, clean=args.clean)
