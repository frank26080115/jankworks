import os
import sys
import time
import threading
import tempfile
import msvcrt

from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

# -----------------------------
# Single instance lock
# -----------------------------
LOCKFILE_PATH = os.path.join(tempfile.gettempdir(), "my_tray_app.lock")

def acquire_lock():
    global lock_file
    try:
        lock_file = open(LOCKFILE_PATH, "w")
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("Another instance is already running.")
        sys.exit(0)

# -----------------------------
# Icon loading
# -----------------------------
def load_icon():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(script_dir, "icon.ico")
    png_path = os.path.join(script_dir, "icon.png")

    try:
        if os.path.exists(ico_path):
            return Image.open(ico_path)
        elif os.path.exists(png_path):
            return Image.open(png_path)
    except Exception:
        pass

    # Fallback: generate a simple icon
    img = Image.new("RGB", (64, 64), color=(50, 100, 200))
    d = ImageDraw.Draw(img)
    d.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
    return img

# -----------------------------
# Background thread
# -----------------------------
def background_worker():
    while True:
        print("Background thread heartbeat...")
        time.sleep(10)

# -----------------------------
# Tray actions
# -----------------------------
def do_something(icon, item):
    icon.notify("Demo action triggered!", "Tray App")

def quit_app(icon, item):
    icon.stop()
    try:
        lock_file.close()
        os.remove(LOCKFILE_PATH)
    except Exception:
        pass

# -----------------------------
# Main
# -----------------------------
def main():
    acquire_lock()

    # Start background thread
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()

    icon_image = load_icon()

    tray_icon = pystray.Icon(
        "MyTrayApp",
        icon_image,
        "My Tray App",
        menu=pystray.Menu(
            item("Do Something", do_something),
            item("Quit", quit_app)
        )
    )

    tray_icon.run()


if __name__ == "__main__":
    main()
