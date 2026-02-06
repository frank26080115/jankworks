import argparse
import os
import sys
import time
import zipfile
import tempfile
import shutil
import subprocess
from pathlib import Path

import html_css_inject


# -----------------------------
# Browser helpers
# -----------------------------

def open_url_in_browser(url: str, chrome_path: str | None):
    print(f"[INFO] Opening URL: {url}")

    if chrome_path:
        subprocess.Popen([chrome_path, url], shell=False)
    else:
        os.startfile(url)


# -----------------------------
# Download directory discovery
# -----------------------------

def guess_download_dirs(user_download_dir: str | None):
    dirs = []

    if user_download_dir:
        dirs.append(Path(user_download_dir))
        return dirs

    print("[INFO] No download directory specified, scanning user profiles")

    users_root = Path("C:/Users")
    if not users_root.exists():
        print("[WARN] C:/Users does not exist")
        return dirs

    for user_dir in users_root.iterdir():
        dl = user_dir / "Downloads"
        if dl.exists():
            dirs.append(dl)

    print("[INFO] Candidate download directories:")
    for d in dirs:
        print("  ", d)

    return dirs


# -----------------------------
# Download watcher
# -----------------------------

def find_new_downloads(download_dirs, since_timestamp):
    """
    Watch for new ZIP or HTML files created after since_timestamp.
    Returns list of Paths.
    """
    found = set()
    last_new_time = time.time()

    print("[INFO] Waiting for downloads (ZIP or HTML)...")

    while True:
        now = time.time()

        for d in download_dirs:
            try:
                for p in d.iterdir():
                    if not p.is_file():
                        continue

                    if p.suffix.lower() not in {".zip", ".html", ".htm"}:
                        continue

                    try:
                        stat = p.stat()
                    except OSError:
                        continue

                    if stat.st_size == 0:
                        continue

                    if stat.st_mtime >= since_timestamp:
                        if p not in found:
                            print(f"[FOUND] {p}")
                            found.add(p)
                            last_new_time = time.time()
            except FileNotFoundError:
                continue

        # Inactivity heuristic
        if found and (now - last_new_time) > 3:
            print("[INFO] No new files detected for 3 seconds, assuming download complete")
            break

        # Hard timeout
        if (now - since_timestamp) > 10:
            print("[WARN] Timed out after 10 seconds")
            break

        time.sleep(0.25)

    return list(found)


# -----------------------------
# Handle ZIP or HTML
# -----------------------------

def resolve_html_from_downloads(paths):
    """
    Given a list of downloaded paths:
    - If HTML exists, return it immediately
    - Otherwise extract ZIP(s) and search for HTML
    """
    # Prefer direct HTML
    for p in paths:
        if p.suffix.lower() in {".html", ".htm"}:
            print(f"[INFO] Using downloaded HTML directly: {p}")
            return p

    temp_root = Path(tempfile.mkdtemp(dir=Path.cwd(), prefix="doc_extract_"))
    print(f"[INFO] Created temp directory: {temp_root}")

    try:
        for zip_path in paths:
            if zip_path.suffix.lower() != ".zip":
                continue

            extract_dir = temp_root / zip_path.stem
            extract_dir.mkdir(parents=True, exist_ok=True)

            print(f"[INFO] Extracting {zip_path} -> {extract_dir}")

            with zipfile.ZipFile(zip_path) as z:
                z.extractall(extract_dir)

            for root, _, files in os.walk(extract_dir):
                for name in files:
                    if name.lower().endswith((".html", ".htm")):
                        html_path = Path(root) / name
                        print(f"[INFO] Found HTML in ZIP: {html_path}")
                        return html_path
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise

    print("[ERROR] No HTML file found in downloads")
    shutil.rmtree(temp_root, ignore_errors=True)
    return None


# -----------------------------
# HTML processing
# -----------------------------

def process_html_file(input_path: Path):
    base, _ = os.path.splitext(input_path)
    output_path = f"{base}_modified.html"

    print(f"[INFO] Processing HTML: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        html = f.read()

    modified_html = html_css_inject.process_html(html)

    with open(output_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(modified_html)

    print("[DONE] Wrote modified HTML to:")
    print(f"       {output_path}")

    return output_path


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download Google Doc HTML via browser and post-process it"
    )
    parser.add_argument(
        "--download-dir",
        default=None,
        help="User download directory (defaults to scanning all user Downloads)"
    )
    parser.add_argument(
        "--doc-url",
        default="https://docs.google.com/document/d/1nvR9c47jiyzYat0P5jQUmLorFteohqV7StITYCfpbgc/edit",
        help="Google Docs edit URL"
    )
    parser.add_argument(
        "--chrome-path",
        default=None,
        help="Path to Chrome executable"
    )

    args = parser.parse_args()

    # Convert edit URL → export URL
    if "/edit" in args.doc_url:
        export_url = args.doc_url.replace("/edit", "/export?format=html")
    else:
        export_url = args.doc_url.rstrip("/") + "/export?format=html"

    print(f"[INFO] Export URL: {export_url}")

    download_dirs = guess_download_dirs(args.download_dir)

    start_time = time.time()

    open_url_in_browser(export_url, args.chrome_path)

    downloaded_files = find_new_downloads(download_dirs, start_time)
    if not downloaded_files:
        print("[ERROR] No downloads detected")
        sys.exit(1)

    html_path = resolve_html_from_downloads(downloaded_files)
    if not html_path:
        sys.exit(1)

    output_path = process_html_file(html_path)

    output_path = os.path.abspath(output_path)
    print(f"[INFO] Opening output HTML: {output_path}")
    open_url_in_browser(output_path, args.chrome_path)


if __name__ == "__main__":
    main()
