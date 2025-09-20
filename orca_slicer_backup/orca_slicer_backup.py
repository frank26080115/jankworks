#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import shutil
import sys

def resolve_destination_dir(src: Path, dest_arg: str) -> Path:
    """
    If dest_arg is blank, use script/exe directory + 'backups'.
    Always return a directory that will contain a subfolder named after src.name.
    """
    if dest_arg.strip() == "":
        # Use the folder where this script/exe resides
        # When frozen by PyInstaller, sys.executable is the exe path
        base_dir = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
        dest_root = base_dir / "backups"
    else:
        dest_root = Path(dest_arg).expanduser().resolve()

    # Final destination is a folder inside dest_root named after source folder
    return dest_root / src.name

def copy_recursive_overwrite(src: Path, dst: Path) -> None:
    """
    Recursively copy src into dst, overwriting files, creating directories as needed.
    Does not delete extras at destination (no mirroring/cleanup).
    """
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Source directory not found or not a directory: {src}")

    dst.mkdir(parents=True, exist_ok=True)

    # Walk source tree, recreate directories, copy files
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        dst_dir = dst / rel
        dst_dir.mkdir(parents=True, exist_ok=True)

        for d in dirs:
            (dst_dir / d).mkdir(parents=True, exist_ok=True)

        for f in files:
            src_file = Path(root) / f
            dst_file = dst_dir / f
            # copy2 preserves metadata; overwrite unconditionally
            shutil.copy2(src_file, dst_file)

def main():
    default_src = r"C:\Users\frank\AppData\Roaming\OrcaSlicer\user"

    parser = argparse.ArgumentParser(
        description="Recursively back up OrcaSlicer 'user' folder, overwriting existing files."
    )
    parser.add_argument(
        "--src", "--source",
        dest="src",
        default=default_src,
        help=f"Source directory (default: {default_src})"
    )
    parser.add_argument(
        "--dst", "--dest", "--destination",
        dest="dst",
        default="",
        help="Destination root directory. "
             "If blank, uses '<script_folder>\\backups'. "
             "The source folder name is appended inside the destination."
    )

    args = parser.parse_args()

    src_path = Path(args.src).expanduser().resolve()
    dst_final = resolve_destination_dir(src_path, args.dst)

    print(f"[i] Source:      {src_path}")
    print(f"[i] Destination: {dst_final}  (will be created if missing)")
    try:
        copy_recursive_overwrite(src_path, dst_final)
    except Exception as e:
        print(f"[!] Backup failed: {e}")
        sys.exit(1)

    print("[✓] Backup complete (files copied/overwritten as needed).")

if __name__ == "__main__":
    main()
