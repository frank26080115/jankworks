import os, re, unicodedata
from typing import Dict, List, Tuple

DECORATION_KEYWORDS = {
    "discography", "anthology", "collection", "complete", "official",
    "greatest", "hits", "singles", "best", "deluxe", "expanded",
    "remaster", "remastered", "reissue", "box", "edition", "web",
    "unorganized"
}

FEATURE_TOKENS = (" feat. ", " ft. ", " featuring ", " with ")

YEAR_RANGE = re.compile(r"\b(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}\b")
YEAR_SINGLE = re.compile(r"\b(19|20)\d{2}\b")
TRACK_PREFIX = re.compile(r"^\s*\d{1,3}[\.\-\s_]+")
BRACKETS = re.compile(r"(\[.*?\]|\(.*?\)|\{.*?\})")
MULTISPACE = re.compile(r"\s{2,}")

def norm(s: str) -> str:
    # normalize unicode & spacing
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("_", " ").strip()
    s = BRACKETS.sub("", s)
    s = YEAR_RANGE.sub("", s)
    s = YEAR_SINGLE.sub("", s)
    s = TRACK_PREFIX.sub("", s)
    # cut features
    low = s.lower()
    cut = len(s)
    for tok in FEATURE_TOKENS:
        i = low.find(tok)
        if i >= 0:
            cut = min(cut, i)
    s = s[:cut]
    s = MULTISPACE.sub(" ", s).strip(" -–—·•.,\u00a0")
    return s

def strip_decorations_from_head(s: str) -> str:
    """
    If the string starts with 'Artist <decorations...>', strip trailing
    decoration words after the artist chunk. We stop at the first decoration keyword.
    """
    tokens = s.split()
    out = []
    for t in tokens:
        t_clean = re.sub(r"[^A-Za-z0-9'&.+-]", "", t).lower()
        if t_clean in DECORATION_KEYWORDS:
            break
        out.append(t)
    return " ".join(out).strip() or s

def split_artist_left_of_dash(s: str) -> str:
    if '-' not in s:
        return None
    # Use the first ' - ' (with spaces) or a generous pattern
    m = re.split(r"\s[-–—]\s", s, maxsplit=1)
    return m[0].strip() if len(m) > 1 else ""

def path_parts(p: str) -> List[str]:
    parts = []
    drive, tail = os.path.splitdrive(p)
    while True:
        tail, last = os.path.split(tail)
        if last:
            parts.append(last)
        else:
            if tail:
                parts.append(tail)
            break
    return list(reversed(parts))  # root -> leaf

def guess_artist_from_path(path: str) -> Dict:
    # collect candidates with reasons
    p = path
    parts = path_parts(p)
    filename = os.path.splitext(parts[-1])[0] if parts else ""
    parent = parts[-2] if len(parts) > 1 else ""
    grandparent = parts[-3] if len(parts) > 2 else ""

    cands: List[Tuple[str, str, int]] = []  # (artist, reason, score)

    # 1) From filename like "Artist - Track"
    f = norm(filename)
    a = split_artist_left_of_dash(f)
    if a:
        cands.append((a, "filename-left-of-dash", 90))

    # 2) From parent folder like "Artist - Album"
    pf = norm(parent)
    a = split_artist_left_of_dash(pf)
    if a:
        cands.append((a, "parent-left-of-dash", 80))

    # 3) From grandparent folder like "Artist/Album"
    if grandparent:
        gp = norm(grandparent)
        gp2 = strip_decorations_from_head(gp)
        if gp2 and gp2.lower() not in DECORATION_KEYWORDS and len(gp2) > 1:
            cands.append((gp2, "grandparent-artist-folder", 75))

    # 4) From parent folder head before decorations ("Green Day Complete Official Discography ...")
    if parent:
        pf2 = strip_decorations_from_head(pf)
        if pf2 and pf2 != pf:
            cands.append((pf2, "parent-head-before-decorations", 70))

    # 5) From the first folder after 'Music' (common library layout)
    for i, part in enumerate(parts):
        if part.lower() == "music" and i + 1 < len(parts):
            after = norm(parts[i + 1])
            after2 = strip_decorations_from_head(after)
            faf2 = strip_decorations_from_head(norm(filename))
            if after2 == faf2:
                continue
            if after2:
                cands.append((after2, "after-music-folder", 65))
            break

    # 6) Last-resort: parent folder raw (but cleaned)
    if pf:
        cands.append((pf, "parent-raw", 50))

    # normalize candidates, dedupe, and lightly score for “name-y-ness”
    def nameyness(x: str) -> int:
        if x.lower().endswith(".com") or x.lower().endswith(".org") or x.lower().endswith(".net"):
            return -1
        # bonus for capitalized words and presence of letters
        words = x.split()
        caps = sum(1 for w in words if w[:1].isupper())
        letters = sum(c.isalpha() for c in x)
        return caps * 3 + min(letters, 30)

    merged: Dict[str, Tuple[str, int]] = {}
    for artist, why, score in cands:
        artist = artist.strip(" -")
        if not artist or len(artist) < 2:
            continue
        thisscore = nameyness(artist)
        if thisscore >= 0:
            score += thisscore
        if artist in merged:
            prev_why, prev_score = merged[artist]
            if score > prev_score:
                merged[artist] = (why, score)
        else:
            merged[artist] = (why, score)

    if not merged:
        return {"artist": None, "confidence": 0, "reason": "no-candidates", "candidates": []}

    best_artist, (best_why, best_score) = max(merged.items(), key=lambda kv: kv[1][1])
    ranked = sorted(
        [{"artist": a, "reason": w, "score": s} for a, (w, s) in merged.items()],
        key=lambda d: d["score"],
        reverse=True,
    )
    return {"artist": best_artist, "confidence": min(100, best_score), "reason": best_why, "candidates": ranked[:5]}

# pip install mutagen rapidfuzz
from mutagen import File as MutagenFile
from rapidfuzz import process, fuzz

def refine_with_tags_and_fuzzy(path_guess: str, path: str, known_artists: List[str]) -> Tuple[str, int, str]:
    # Try tags
    try:
        audio = MutagenFile(path)
        tpe1 = None
        if audio and audio.tags:
            if "TPE1" in audio.tags:  # ID3v2
                tpe1 = getattr(audio.tags["TPE1"], "text", [None])[0]
            elif "artist" in audio.tags:  # Vorbis/FLAC
                v = audio.tags["artist"]
                tpe1 = v[0] if isinstance(v, list) and v else v
        if tpe1:
            tag_artist = str(tpe1).strip()
            return tag_artist, 95, "tags"
    except Exception:
        pass

    # Fuzzy-correct path guess if we have a roster
    if path_guess and known_artists:
        match, score, _ = process.extractOne(
            path_guess, known_artists, scorer=fuzz.WRatio
        )
        if score >= 90:
            return match, 92, "fuzzy-known-artists"

    # fallback to the path guess
    return path_guess, 70 if path_guess else 0, "path-only"
