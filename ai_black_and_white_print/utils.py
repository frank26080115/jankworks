import ctypes
from io import BytesIO
from ctypes import wintypes
import sys, os, tempfile
import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageOps, ImageChops, ImageDraw


def load_input_image(input_path: str | None) -> Image.Image:
    """Load an image either from a file path or from the system clipboard."""
    if input_path:
        return Image.open(input_path)

    clipboard_value = ImageGrab.grabclipboard()

    # Pillow may return an Image object directly, or it may return a list of file paths.
    if isinstance(clipboard_value, Image.Image):
        return clipboard_value

    if isinstance(clipboard_value, list) and clipboard_value:
        return Image.open(clipboard_value[0])

    raise ValueError("No input path was provided and no image was found in the system clipboard.")


def copy_image_to_clipboard_windows(image: Image.Image) -> None:
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    # GlobalAlloc
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL

    # GlobalLock
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p

    # GlobalUnlock
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    # GlobalFree
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    # Clipboard functions
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL

    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL

    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL

    """Copy an image to the Windows clipboard in CF_DIB format."""
    if sys.platform != "win32":
        raise RuntimeError("Clipboard image output without a file path is currently supported on Windows only.")

    bmp_stream = BytesIO()

    # CF_DIB requires BMP bytes without the 14-byte BMP file header.
    image.convert("RGB").save(bmp_stream, format="BMP")
    dib_data = bmp_stream.getvalue()[14:]

    GHND = 0x0042
    CF_DIB = 8

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    handle = kernel32.GlobalAlloc(GHND, len(dib_data))
    if not handle:
        raise RuntimeError("GlobalAlloc failed while preparing clipboard image data.")

    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise RuntimeError("GlobalLock failed while preparing clipboard image data.")

    ctypes.memmove(pointer, dib_data, len(dib_data))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        raise RuntimeError("OpenClipboard failed.")

    try:
        if not user32.EmptyClipboard():
            kernel32.GlobalFree(handle)
            raise RuntimeError("EmptyClipboard failed.")

        if not user32.SetClipboardData(CF_DIB, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("SetClipboardData failed.")

        # Ownership is transferred to the clipboard after SetClipboardData succeeds.
        handle = None
    finally:
        user32.CloseClipboard()

    if handle:
        kernel32.GlobalFree(handle)


def show_image_with_cv2(image: Image.Image) -> None:
    """Display an image and wait for any key so the user can inspect the result."""
    gray_image = image.convert("L")
    image_array = np.array(gray_image)
    cv2.imshow("Black and White Result", image_array)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def crop_to_content_square_old(img: Image.Image) -> Image.Image:
    """
    Crop as much outer white space as possible, then pad to square.
    Assumes white background, black foreground.
    """
    # Invert so content becomes white for bbox detection
    inverted = ImageOps.invert(img)
    bbox = inverted.getbbox()

    if bbox:
        img = img.crop(bbox)

    # Pad to square
    w, h = img.size
    size = max(w, h)

    square = Image.new("L", (size, size), 255)
    square.paste(img, ((size - w) // 2, (size - h) // 2))

    return square


def crop_to_content_square(
    img: Image.Image,
    target_ratio: float = 1.5,
    auto_rotate_threshold: float = 0.9
) -> Image.Image:
    """
    Crop outer white space, enforce target aspect ratio,
    optionally rotate tall content, then pad to square.

    target_ratio: desired width / height of content
    auto_rotate_threshold: if detected w/h < this, rotate 90° CW
    """

    # Ensure grayscale
    if img.mode != "L":
        img = img.convert("L")

    # Invert so content becomes white for bbox detection
    inverted = ImageOps.invert(img)
    bbox = inverted.getbbox()

    if bbox:
        img = img.crop(bbox)

    w, h = img.size
    if h == 0 or w == 0:
        return img  # avoid division errors

    current_ratio = w / h

    # 🔄 Auto-rotate tall/narrow parts
    if current_ratio < auto_rotate_threshold:
        img = img.rotate(-90, expand=True)  # clockwise
        w, h = img.size
        current_ratio = w / h

    # 📏 Enforce target aspect ratio (width / height)
    if current_ratio < target_ratio:
        # Too tall — need to expand width
        new_w = int(h * target_ratio)
        padded = Image.new("L", (new_w, h), 255)
        padded.paste(img, ((new_w - w) // 2, 0))
        img = padded

    elif current_ratio > target_ratio:
        # Too wide — need to expand height
        new_h = int(w / target_ratio)
        padded = Image.new("L", (w, new_h), 255)
        padded.paste(img, (0, (new_h - h) // 2))
        img = padded

    # ⬜ Pad to square
    w, h = img.size
    size = max(w, h)

    square = Image.new("L", (size, size), 255)
    square.paste(img, ((size - w) // 2, (size - h) // 2))

    return square


def crop_png_to_content_square(file_path: str) -> None:
    """
    Open a PNG file, run crop_to_content_square on it,
    ensure final image is square, and overwrite the file safely.
    """

    if not file_path.lower().endswith(".png"):
        raise ValueError("File must be a PNG.")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"{file_path} does not exist.")

    # Open image
    with Image.open(file_path) as img:
        img = img.convert("L")  # ensure grayscale

        processed = crop_to_content_square(img)

        # 🔒 Absolute guarantee it's square
        w, h = processed.size
        if w != h:
            size = max(w, h)
            square = Image.new("L", (size, size), 255)
            square.paste(processed, ((size - w) // 2, (size - h) // 2))
            processed = square

        # Write to temporary file first (safer than direct overwrite)
        dir_name = os.path.dirname(file_path)
        with tempfile.NamedTemporaryFile(delete=False, dir=dir_name, suffix=".png") as tmp:
            temp_path = tmp.name
            processed.save(temp_path, format="PNG")

    # Replace original file atomically
    os.replace(temp_path, file_path)
