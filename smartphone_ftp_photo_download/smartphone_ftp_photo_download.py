#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as dt
import os
from pathlib import Path
from ftplib import FTP, error_perm
import time
import sys

# ---------- helpers ----------

def log(msg):
    print(msg, flush=True)

def today_str():
    return dt.datetime.now().strftime("%Y-%m-%d")

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def ftp_connect(host, port, user, password, passive=True, tries=3, delay=2.0):
    last_exc = None
    for i in range(1, tries+1):
        try:
            ftp = FTP()
            ftp.connect(host, port, timeout=20)
            ftp.login(user=user, passwd=password)
            ftp.set_pasv(passive)
            return ftp
        except Exception as e:
            last_exc = e
            log(f"[retry {i}/{tries}] FTP connect failed: {e}")
            time.sleep(delay)
    raise last_exc

def ftp_supports_mlsd(ftp: FTP) -> bool:
    try:
        features = []
        ftp.sendcmd("FEAT")
        # If FEAT works, try MLSD quickly
        cwd = ftp.pwd()
        try:
            list(ftp.mlsd())
            ftp.cwd(cwd)
            return True
        except Exception:
            ftp.cwd(cwd)
            return False
    except Exception:
        return False

def list_dir(ftp: FTP, path: str, use_mlsd: bool):
    """
    Returns list of (name, is_dir, size) for entries directly under path.
    """
    entries = []

    def parse_list_line(line: str):
        # crude LIST parser fallback (best-effort)
        # e.g. "-rw-r--r--   1 owner   group     12345 Jan 01 12:34 IMG_0001.JPG"
        parts = line.split(maxsplit=8)
        if len(parts) < 9:
            return None
        flags = parts[0]
        name = parts[-1]
        is_dir = flags.startswith('d')
        size = None
        if not is_dir:
            try:
                size = int(parts[4])
            except Exception:
                size = None
        return (name, is_dir, size)

    cwd = ftp.pwd()
    ftp.cwd(path)
    if use_mlsd:
        for name, facts in ftp.mlsd():
            if name in ('.', '..'):
                continue
            typ = facts.get('type', '')
            is_dir = typ.lower() == 'dir'
            size = None
            if not is_dir:
                try:
                    size = int(facts.get('size', '0'))
                except Exception:
                    size = None
            entries.append((name, is_dir, size))
    else:
        lines = []
        ftp.retrlines('LIST', lines.append)
        for line in lines:
            parsed = parse_list_line(line)
            if parsed:
                entries.append(parsed)

    ftp.cwd(cwd)
    return entries

def remote_exists(ftp: FTP, path: str) -> bool:
    parent, name = path.rsplit('/', 1)
    try:
        for n, is_dir, _ in list_dir(ftp, parent, use_mlsd=ftp_supports_mlsd(ftp)):
            if n == name:
                return True
        return False
    except Exception:
        return False

def safe_rename(ftp: FTP, old_path: str, new_path: str, dry=False):
    if dry:
        log(f"[dry-run] would rename '{old_path}' -> '{new_path}'")
        return
    if remote_exists(ftp, new_path):
        log(f"[info] target already exists, skipping rename: {new_path}")
        return
    try:
        ftp.rename(old_path, new_path)
        log(f"[ok] renamed '{old_path}' -> '{new_path}'")
    except error_perm as e:
        # Some phone FTP servers require RNFR path without leading slash
        log(f"[warn] rename failed ({e}), attempting in-directory rename workaround")
        # Try chdir to parent then rename by names
        parent, old_name = old_path.rsplit('/', 1)
        _, new_name = new_path.rsplit('/', 1)
        cwd = ftp.pwd()
        try:
            ftp.cwd(parent)
            ftp.rename(old_name, new_name)
            ftp.cwd(cwd)
            log(f"[ok] renamed within '{parent}': {old_name} -> {new_name}")
        except Exception as e2:
            ftp.cwd(cwd)
            raise RuntimeError(f"Rename failed: {e2}") from e

def file_sizes_equal(local_path: Path, remote_size: int) -> bool:
    try:
        return local_path.stat().st_size == remote_size
    except FileNotFoundError:
        return False

def download_file(ftp: FTP, remote_path: str, local_path: Path, remote_size: int | None, resume=True):
    ensure_dir(local_path.parent)
    mode = 'ab' if resume and local_path.exists() else 'wb'
    existing = local_path.stat().st_size if local_path.exists() else 0

    # If we know sizes and they match, skip
    if remote_size is not None and file_sizes_equal(local_path, remote_size):
        log(f"  [skip] {local_path.name} (already complete)")
        return

    # If resuming and server supports REST, continue
    rest = existing if (resume and existing > 0) else None
    with open(local_path, mode) as f:
        def _cb(chunk: bytes):
            f.write(chunk)

        cmd = f"RETR {remote_path}"
        if rest:
            try:
                ftp.voidcmd(f"TYPE I")  # binary
                ftp.sendcmd(f"REST {rest}")
                ftp.retrbinary(cmd, _cb)
            except Exception:
                # fallback: start over
                log("  [info] resume not supported, restarting")
                f.seek(0)
                f.truncate(0)
                ftp.retrbinary(cmd, _cb)
        else:
            ftp.retrbinary(cmd, _cb)

    # quick post-check
    if remote_size is not None and not file_sizes_equal(local_path, remote_size):
        log(f"  [warn] size mismatch after download: {local_path.name}")

def download_tree(ftp: FTP, remote_dir: str, local_dir: Path):
    use_mlsd = ftp_supports_mlsd(ftp)

    def _walk(cur_remote: str, cur_local: Path):
        log(f"[dir] {cur_remote}")
        ensure_dir(cur_local)
        for name, is_dir, size in list_dir(ftp, cur_remote, use_mlsd=use_mlsd):
            rpath = f"{cur_remote}/{name}"
            lpath = cur_local / name
            if is_dir:
                _walk(rpath, lpath)
            else:
                size_int = int(size) if (size is not None) else None
                log(f"  [get] {name} ({size_int if size_int is not None else '?'} bytes)")
                download_file(ftp, rpath, lpath, size_int, resume=True)

    _walk(remote_dir, local_dir)

# ---------- main flow ----------

def main():
    ap = argparse.ArgumentParser(description="Rename phone DCIM/Camera and download via FTP.")
    ap.add_argument("--host", required=True, help="Phone FTP host/IP")
    ap.add_argument("--port", type=int, default=21, help="FTP port (default 21)")
    ap.add_argument("--user", default="anonymous", help="FTP username")
    ap.add_argument("--password", default="", help="FTP password")
    ap.add_argument("--passive", action="store_true", help="Use passive mode (recommended for most phone apps)")
    ap.add_argument("--active", dest="passive", action="store_false", help="Use active mode")
    ap.set_defaults(passive=True)

    ap.add_argument("--dest", required=True, help="Local destination root (e.g. E:\\Photos\\Phone)")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--rename-today", action="store_true", help="Rename Camera -> Camera-YYYY-MM-DD (today)")
    group.add_argument("--rename-to", help="Rename Camera -> this exact name (e.g. Camera-2025-08-11)")
    ap.add_argument("--dry-run", action="store_true", help="Show actions without changing anything")
    ap.add_argument("--no-rename", action="store_true", help="Skip renaming step; just download current Camera dir")
    ap.add_argument("--remote-root", default="/DCIM", help="Remote DCIM root (default: /DCIM)")

    args = ap.parse_args()

    remote_dcim = args.remote_root.rstrip("/")
    remote_camera = f"{remote_dcim}/Camera"

    # Decide the target folder name
    if args.no_rename:
        target_remote = remote_camera
        target_name = Path(target_remote).name
    else:
        if args.rename_to:
            target_name = args.rename_to
        elif args.rename_today:
            target_name = f"Camera-{today_str()}"
        else:
            # default to today to match your habit
            target_name = f"Camera-{today_str()}"

        target_remote = f"{remote_dcim}/{target_name}"

    # Connect
    log(f"🔌 connecting to ftp://{args.host}:{args.port} (passive={args.passive}) …")
    ftp = ftp_connect(args.host, args.port, args.user, args.password, passive=args.passive)

    # Sanity check DCIM exists
    try:
        if not remote_exists(ftp, remote_dcim):
            raise RuntimeError(f"Remote path not found: {remote_dcim}")
    except Exception as e:
        log(f"[error] {e}")
        ftp.quit()
        sys.exit(2)

    # Rename if requested
    if not args.no_rename:
        if not remote_exists(ftp, remote_camera):
            log(f"[info] '{remote_camera}' not found — maybe already renamed? Proceeding with '{target_remote}'.")
        else:
            safe_rename(ftp, remote_camera, target_remote, dry=args.dry_run)

    # Local destination directory (mirror the name)
    dest_root = Path(args.dest)
    local_folder = dest_root / Path(target_remote).name
    log(f"💾 local destination: {local_folder}")
    if args.dry_run:
        log("[dry-run] stopping before download.")
        ftp.quit()
        return

    # Download tree
    if not remote_exists(ftp, target_remote):
        log(f"[error] Remote folder not found: {target_remote}")
        ftp.quit()
        sys.exit(3)

    try:
        download_tree(ftp, target_remote, local_folder)
    finally:
        try:
            ftp.quit()
        except Exception:
            pass

    log("✅ done.")

if __name__ == "__main__":
    main()
