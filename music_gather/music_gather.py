#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import datetime
import logging
import os
import re
import shutil
import sys
from pathlib import Path

from mutagen import File as MutagenFile

from artist_guess import guess_artist_from_path
from search_path_helper import search_alternative_src
from title_helpers import sanitize_name, title_from_filename, normalize_component, remove_leading_artist_from_title, normalize_separators_inside_title

# ---------------------------
# Logging setup
# ---------------------------
def setup_logger():
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    logfile = logs_dir / f"log-{ts}.txt"

    logger = logging.getLogger("music_renamer")
    logger.setLevel(logging.INFO)

    # File handler
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.INFO)
    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger, logfile


# ---------------------------
# Helpers
# ---------------------------

def get_tag(audio, *keys):
    """Try multiple keys across formats; return first non-empty scalar string or None."""
    if not audio:
        return None
    tags = getattr(audio, "tags", None)
    if not tags:
        return None

    # Some tag objects behave like dicts but with different value types (lists/text frames)
    for k in keys:
        try:
            if k in tags:
                v = tags[k]
                # mutagen can return frames or lists depending on format
                if isinstance(v, (list, tuple)):
                    v = v[0] if v else None
                # ID3 frames: .text
                if hasattr(v, "text"):
                    txt = v.text
                    if isinstance(txt, (list, tuple)):
                        v = txt[0] if txt else None
                    else:
                        v = txt
                if v is not None:
                    s = str(v).strip()
                    if s:
                        return s
        except Exception:
            continue
    return None

def read_artist_and_title(path: Path, logger: logging.Logger):
    """Return (artist, title, artist_source, title_source) where *_source is 'tag' or 'filename' or 'guessed'."""
    audio = None
    try:
        audio = MutagenFile(str(path))
    except Exception as e:
        logger.warning(f"Failed to open metadata with mutagen: {path} ({e})")

    # Artist priority:
    # ID3: TPE1 (artist), TPE2 (album artist) as fallback
    # Vorbis/FLAC: 'artist', 'albumartist'
    artist = (
        get_tag(audio, "TPE1", "artist", "ALBUMARTIST", "albumartist", "TPE2")
    )
    artist_source = "tag" if artist else None

    # Title
    tag_title = get_tag(audio, "TIT2", "title")
    fname_title = title_from_filename(path.stem)

    # Special rule: if tag title exists and starts with a number, prefer tag title to avoid nuking e.g., "21 Guns"
    # Otherwise, default to filename-stripped; if filename-stripped is empty, fall back to tag title.
    if tag_title and re.match(r"^\s*\d", tag_title):
        title = tag_title.strip()
        title_source = "tag"
    else:
        title = fname_title or (tag_title.strip() if tag_title else "")
        title_source = "filename" if title == fname_title else ("tag" if tag_title else "filename")

    # If artist missing: try guesser
    guessed_used = False
    if not artist:
        guess = guess_artist_from_path(str(path))
        if isinstance(guess, dict):
            artist = guess.get("artist")
        elif isinstance(guess, str):
            artist = guess
        if artist:
            artist_source = "guessed"
            guessed_used = True
        else:
            artist_source = None

    if not artist:
        logger.warning(f"No artist tag and guess failed for {path}")

    return artist, title, artist_source or "unknown", title_source, (audio if guessed_used else None)

def write_artist_if_guessed(dest_path: Path, artist: str, logger: logging.Logger):
    """Attempt to write artist into metadata if it was guessed (best-effort)."""
    if not artist:
        return
    try:
        audio = MutagenFile(str(dest_path))
        if not audio:
            return
        # Prefer easy mappings when available
        if audio.tags is None:
            audio.add_tags()

        # Many formats accept 'artist'
        updated = False
        try:
            # Try generic
            audio["artist"] = artist
            updated = True
        except Exception:
            pass

        # For MP3/ID3 specifically
        try:
            from mutagen.easyid3 import EasyID3
            ed = EasyID3(str(dest_path))
            ed["artist"] = artist
            ed.save()
            updated = True
        except Exception:
            pass

        # For FLAC
        try:
            from mutagen.flac import FLAC
            fl = FLAC(str(dest_path))
            fl["artist"] = artist
            fl.save()
            updated = True
        except Exception:
            pass

        # For OGG Vorbis
        try:
            from mutagen.oggvorbis import OggVorbis
            ov = OggVorbis(str(dest_path))
            ov["artist"] = artist
            ov.save()
            updated = True
        except Exception:
            pass

        # As a last attempt, save the generic audio
        try:
            audio.save()
            updated = True
        except Exception:
            pass

        if updated:
            logger.info(f"Inserted guessed artist into metadata: {dest_path} -> '{artist}'")
        else:
            logger.warning(f"Failed to insert guessed artist into metadata: {dest_path}")

    except Exception as e:
        logger.warning(f"Metadata write error ({dest_path}): {e}")

def determine_new_name(artist: str, title: str, ext: str) -> str:
    # 1) Basic sanitization of components
    artist = artist or "Unknown Artist"
    title  = title  or "Unknown Title"

    # 2) Remove duplicated artist prefix from title (case-insensitive)
    title = remove_leading_artist_from_title(artist, title)

    # 3) Normalize each component (trim, collapse spaces, strip stray seps)
    artist_clean = normalize_component(sanitize_name(artist))
    title_clean  = normalize_component(sanitize_name(title))

    # 4) Inside the title, prevent separator soup; allow only ' - ' as the multi-chunk separator
    title_clean = normalize_separators_inside_title(title_clean)

    # 5) Join with exactly one ' - ' between artist and title
    filename_stem = f"{artist_clean} - {title_clean}"

    # 6) Extra safety: never allow consecutive ' - ' across the whole stem
    filename_stem = re.sub(r'(?:\s-\s){2,}', ' - ', filename_stem).strip()

    return f"{filename_stem}{ext.lower()}"


def parse_tsv_line(line: str):
    # Split on tab into two columns; strip quotes around path if present
    cols = line.rstrip("\n\r").split("\t")
    if len(cols) < 2:
        return None, None
    path_raw = cols[0].strip()
    # remove optional surrounding quotes
    if len(path_raw) >= 2 and ((path_raw[0] == path_raw[-1] == '"') or (path_raw[0] == path_raw[-1] == "'")):
        path_raw = path_raw[1:-1]
    try:
        val = int(cols[1].strip())
    except ValueError:
        val = None
    return path_raw, val


# ---------------------------
# Main
# ---------------------------
def main():
    parser = argparse.ArgumentParser(description="Rename/copy music files using tags; log issues; produce a CSV mapping.")
    parser.add_argument("-i", "--input", default="data.tsv", help="Input text file (TSV with path<TAB>integer). Default: data.tsv")
    parser.add_argument("-o", "--output", default="output.csv", help="Output CSV mapping (input_path, output_path). Default: output.csv")
    parser.add_argument("-d", "--directory", default=r"G:\MusicCache", help="Destination directory for copied files. Default: music")
    args = parser.parse_args()

    dry_run = False

    logger, logfile = setup_logger()
    logger.info(f"Starting. Logfile at: {logfile}")

    input_path = Path(args.input)
    output_csv = Path(args.output)
    dest_dir = Path(args.directory)

    # Ensure destination directory exists
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Ensure output CSV directory exists
    if output_csv.parent and not output_csv.parent.exists():
        output_csv.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    rows = []
    with input_path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            path_str, val = parse_tsv_line(line)
            if path_str is None or val is None:
                logger.warning(f"Line {line_no}: unable to parse -> {line.strip()!r}")
                continue
            if val <= 0:
                continue  # keep only positive integer rows

            src = Path(path_str)
            # Validate src file
            if not src.exists():
                src = search_alternative_src(src)
            if not src.exists():
                logger.warning(f"Missing file: {src}")
                continue
            try:
                if src.stat().st_size == 0:
                    logger.warning(f"Zero-size file: {src}")
                    continue
            except Exception as e:
                logger.warning(f"Stat failed for {src}: {e}")
                continue

            # Read tags / construct new name
            artist, title, artist_source, title_source, audio_for_guess = read_artist_and_title(src, logger)

            if not artist:
                logger.warning(f"No artist available even after guess: {src}")

            if artist_source == "guessed":
                logger.warning(f"Artist guessed from path for {src} -> '{artist}'")
            if title_source == "filename" and title and re.match(r"^\s*\d", title):
                # Paranoia: if filename-derived title still starts with digit (edge case),
                # and tag_title existed but we didn't pick it, we already enforced the special rule above.
                pass

            ext = src.suffix or ""
            new_name = determine_new_name(artist or "Unknown Artist", title or "Unknown Title", ext)
            dest_path = dest_dir / new_name

            if dest_path.exists():
                logger.warning(f"Skipping copy due to overwrite: {dest_path}")
                # Still record mapping in CSV as requested
                rows.append((str(src), str(dest_path)))
                continue

            # Ensure destination directory exists (already ensured at top, but in case of nested structure)
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy
            try:
                if not dry_run:
                    shutil.copy2(src, dest_path)
                logger.info(f"Copied: {src} -> {dest_path}")
                # If we used guessed artist, try to write it into the *copied* file metadata
                if (artist_source == "guessed") and artist and not dry_run:
                    write_artist_if_guessed(dest_path, artist, logger)
            except Exception as e:
                logger.warning(f"Copy failed {src} -> {dest_path}: {e}")
                # Still write CSV to reflect intended mapping
            finally:
                rows.append((str(src), str(dest_path)))

    # Write CSV
    try:
        with output_csv.open("w", encoding="utf-8", newline="") as cf:
            cw = csv.writer(cf)
            cw.writerow(["input_path", "output_path"])
            cw.writerows(rows)
        logger.info(f"Wrote CSV mapping: {output_csv}")
    except Exception as e:
        logger.error(f"Failed to write CSV {output_csv}: {e}")
        sys.exit(1)

    logger.info("Done.")


if __name__ == "__main__":
    main()
