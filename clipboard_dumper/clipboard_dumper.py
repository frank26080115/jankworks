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
    Try to convert clipboard data into an OpenCV image.
    Returns (image or None)
    """

    # --- PNG/JPEG raw bytes ---
    if isinstance(data, bytes):
        try:
            img = Image.open(io.BytesIO(data))
            return pil_to_cv(img)
        except:
            pass

    # --- CF_DIB / CF_DIBV5 ---
    if fmt_name in ["CF_DIB", "CF_DIBV5"] and isinstance(data, bytes):
        try:
            # DIB → BMP by adding header
            bmp_header = b'BM'
            size = len(data) + 14
            header = bmp_header + size.to_bytes(4, 'little') + b'\x00\x00\x00\x00' + (14 + 40).to_bytes(4, 'little')
            bmp_data = header + data

            img = Image.open(io.BytesIO(bmp_data))
            return pil_to_cv(img)
        except Exception as e:
            print(f"⚠️ Failed to parse DIB: {e}")

    # --- CF_BITMAP (handle-based, annoying one) ---
    if fmt_name == "CF_BITMAP":
        try:
            import win32gui
            import win32ui

            hbitmap = data

            bmp = win32ui.CreateBitmapFromHandle(hbitmap)
            bmpinfo = bmp.GetInfo()
            bmpstr = bmp.GetBitmapBits(True)

            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)

            # BGRA → BGR
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return img

        except Exception as e:
            print(f"⚠️ Failed to parse CF_BITMAP: {e}")

    return None

# --- MAIN INSPECTOR ---

def inspect_clipboard(view=False):
    results = {}
    found_image = None

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

            # Try to parse image if viewing enabled
            if view and found_image is None:
                img = try_parse_image(name, data)
                if img is not None:
                    print(f"\n✅ Selected image source: {name}")
                    found_image = img

    finally:
        win32clipboard.CloseClipboard()

    print("\n=== CLIPBOARD CONTENTS ===\n")
    pprint.pprint(results, width=120)

    if view:
        if found_image is not None:
            show_image(found_image)
        else:
            print("\n❌ No usable image format found in clipboard.")

# --- ENTRY POINT ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clipboard inspector with optional image viewer")
    parser.add_argument("--view", action="store_true", help="Attempt to decode and display image from clipboard")

    args = parser.parse_args()

    inspect_clipboard(view=args.view)
