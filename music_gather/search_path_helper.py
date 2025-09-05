import os
from pathlib import Path

def search_alternative_src(src: Path, possibilities: list = [
    r"\\Nassy",
    r"G:\Music",
    r"E:\Music",
    r"D:\LargeDownloads",
]) -> Path:
    right_side = path_after_music(src)
    for i in possibilities:
        p = Path(i) / right_side
        if os.path.exists(right_side):
            return p
    return src

def path_after_music(p: Path, k: str = "Music") -> Path:
    parts = p.parts
    # Find the index of "Music" (case-insensitive)
    for i, part in enumerate(parts):
        if part.lower() == k.lower():
            # return everything *after* Music
            return Path(*parts[i + 1:])
    return Path(p)  # if no "Music" found, return the whole path
