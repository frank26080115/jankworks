#!/usr/bin/env python3
import os
import sys
import subprocess
import argparse
import datetime
import shutil

# Default path for par2j.exe on Windows
DEFAULT_PAR2EXE = r"C:\ProgramFiles\MultiPar\par2j.exe"
BAR_WIDTH = 30

def show_progress(processed, total, BAR_WIDTH=BAR_WIDTH):
    """Print a progress bar based on processed and total bytes."""
    ratio = processed / total if total > 0 else 0
    ratio = min(ratio, 1.0)
    filled = int(BAR_WIDTH * ratio)
    bar = '#' * filled + '-' * (BAR_WIDTH - filled)
    percent = ratio * 100
    print(f"PROG: |{bar}| {percent:5.1f}%")


def log_message(log_file, level, message):
    timestamp = datetime.datetime.now().isoformat()
    log_file.write(f"{timestamp} {level}: {message}\n")
    log_file.flush()


def make_par2_for_dir(par2exe, dirpath, files, mode, log_file, processed_bytes, total_bytes):
    par2_dir = os.path.join(dirpath, "par2")
    os.makedirs(par2_dir, exist_ok=True)
    processed = set()
    for fname in files:
        src = os.path.join(dirpath, fname)
        if not os.path.isfile(src) or src.lower().endswith(".par2"):
            continue
        # progress update for source file
        try:
            size = os.path.getsize(src)
        except OSError:
            size = 0
        processed_bytes[0] += size
        show_progress(processed_bytes[0], total_bytes)

        dest = os.path.join(par2_dir, fname + ".par2")
        processed.add(fname)
        exists = os.path.exists(dest)
        if mode == "create-skip":
            if not exists:
                try:
                    subprocess.run([par2exe, "create", "/rr10", dest, src], check=True)
                    print(f"[CREATED ] \"{src}\" → \"{dest}\"")
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR   ] Creation failed for \"{src}\": {e}")
                    log_message(log_file, "ERROR", f"Creation failed for \"{src}\": {e}")
        elif mode == "create-recreate":
            if exists:
                try:
                    os.remove(dest)
                    print(f"[REMOVED ] Old \"{dest}\"")
                except Exception as e:
                    print(f"[ERROR   ] Could not remove \"{dest}\": {e}")
                    log_message(log_file, "ERROR", f"Could not remove \"{dest}\": {e}")
            try:
                subprocess.run([par2exe, "create", "/rr10", dest, src], check=True)
                print(f"[CREATED ] \"{src}\" → \"{dest}\"")
            except subprocess.CalledProcessError as e:
                print(f"[ERROR   ] Creation failed for \"{src}\": {e}")
                log_message(log_file, "ERROR", f"Creation failed for \"{src}\": {e}")
        elif mode == "verify-create":
            if exists:
                try:
                    subprocess.run([par2exe, "verify", dest], check=True)
                    print(f"[VERIFIED] \"{dest}\"")
                except subprocess.CalledProcessError as e:
                    print(f"[FAILURE] Verification failed for \"{dest}\": {e}")
                    log_message(log_file, "ERROR", f"Verification failed for \"{dest}\": {e}")
            else:
                try:
                    subprocess.run([par2exe, "create", "/rr10", dest, src], check=True)
                    print(f"[CREATED ] \"{src}\" → \"{dest}\"")
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR   ] Creation failed for \"{src}\": {e}")
                    log_message(log_file, "ERROR", f"Creation failed for \"{src}\": {e}")
    # orphan detection
    for entry in os.listdir(par2_dir):
        if not entry.lower().endswith('.par2') or '.vol' in entry.lower():
            continue
        name = entry[:-5]
        if name not in processed:
            orphan = os.path.join(par2_dir, entry)
            print(f"[WARNING] PAR2 exists but source missing: \"{orphan}\"")
            log_message(log_file, "ERROR", f"PAR2 exists but source missing: \"{orphan}\"")


def repair_par2_for_dir(par2exe, dirpath, log_file, processed_bytes, total_bytes):
    par2_dir = os.path.join(dirpath, "par2")
    if not os.path.isdir(par2_dir):
        return
    for entry in os.listdir(par2_dir):
        if not entry.lower().endswith('.par2') or '.vol' in entry.lower():
            continue
        path = os.path.join(par2_dir, entry)
        # progress update for par2 file
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        processed_bytes[0] += size
        show_progress(processed_bytes[0], total_bytes)
        try:
            subprocess.run([par2exe, "repair", path], check=True)
            print(f"[REPAIRED] \"{path}\"")
            log_message(log_file, "SUCCESS", f"Repaired \"{path}\"")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR   ] Repair failed for \"{path}\": {e}")
            log_message(log_file, "ERROR", f"Repair failed for \"{path}\": {e}")


def prune_par2_for_dir(dirpath, log_file, processed_bytes, total_bytes):
    par2_dir = os.path.join(dirpath, "par2")
    if not os.path.isdir(par2_dir):
        return
    for entry in os.listdir(par2_dir):
        if not entry.lower().endswith('.par2'):
            continue
        full = os.path.join(par2_dir, entry)
        # progress update for prune candidate
        try:
            size = os.path.getsize(full)
        except OSError:
            size = 0
        processed_bytes[0] += size
        show_progress(processed_bytes[0], total_bytes)
        src_name = entry[:-5]
        src_path = os.path.join(dirpath, src_name)
        if not os.path.exists(src_path):
            try:
                os.remove(full)
                print(f"[PRUNED ] \"{full}\"")
                log_message(log_file, "SUCCESS", f"Pruned \"{full}\"")
            except Exception as e:
                print(f"[ERROR   ] Prune failed for \"{full}\": {e}")
                log_message(log_file, "ERROR", f"Prune failed for \"{full}\": {e}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Recursively process .par2 tasks under ROOT, skipping the drive root,",
            " any 'par2' and recycle bin directories."
        )
    )
    parser.add_argument("root", help="Root directory to scan (e.g. E:\\ or /mnt/data)")
    parser.add_argument(
        "--par2exe",
        default=DEFAULT_PAR2EXE,
        help=f"Path to par2j.exe (default: {DEFAULT_PAR2EXE})"
    )
    parser.add_argument(
        "--mode",
        choices=[
            "create-skip", "create-recreate", "verify-create",
            "repair", "prune"
        ],
        default="verify-create",
        help=(
            "Mode: 'create-skip', 'create-recreate', 'verify-create',",
            " 'repair' (repair corrupt sets), 'prune' (remove orphaned .par2)"
        )
    )
    args = parser.parse_args()

    root_abspath = os.path.abspath(args.root)
    du = shutil.disk_usage(root_abspath)
    total_bytes = du.used
    processed_bytes = [0]

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"log_{now}.txt")

    with open(log_path, "a") as log_file:
        print(f"Starting log: {log_path}")
        log_message(log_file, "INFO", f"Disk usage {total_bytes}/{du.total} bytes")

        skip_names = {"par2", "$recycle.bin", "recycle bin"}

        for dirpath, dirnames, filenames in os.walk(args.root):
            absdir = os.path.abspath(dirpath)
            basename = os.path.basename(absdir).lower()
            if basename in skip_names:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d.lower() not in skip_names]
            if absdir == root_abspath:
                continue
            if args.mode == "repair":
                repair_par2_for_dir(args.par2exe, dirpath, log_file, processed_bytes, total_bytes)
            elif args.mode == "prune":
                prune_par2_for_dir(dirpath, log_file, processed_bytes, total_bytes)
            else:
                if filenames:
                    make_par2_for_dir(
                        args.par2exe, dirpath, filenames,
                        args.mode, log_file, processed_bytes, total_bytes
                    )

if __name__ == "__main__":
    main()
