import re

# Sequences we consider "separator soup" (two or more of dot/hyphen with optional spaces)
SEP_RUN = re.compile(r'(?:\s*[-\.]\s*){2,}', flags=re.IGNORECASE)

def normalize_component(s: str) -> str:
    """Trim, collapse internal whitespace, and strip leading/trailing sep chars on a single component."""
    if not s:
        return s
    s = re.sub(r'\s+', ' ', s).strip()
    # Drop leading/trailing soup-y separators, but keep internal single chars (e.g., "Mr. Brightside")
    s = re.sub(r'^[\s\.-]+', '', s)
    s = re.sub(r'[\s\.-]+$', '', s)
    return s

def remove_leading_artist_from_title(artist: str, title: str) -> str:
    """
    If title begins with the artist (case-insensitive) followed by any separator(s),
    remove that prefix to avoid duplicates like 'Artist - Artist - Song'.
    """
    if not artist or not title:
        return title
    pat = re.compile(rf'^\s*{re.escape(artist)}\s*(?:[-\.]\s*)+', flags=re.IGNORECASE)
    new_title = pat.sub('', title).strip()
    return new_title or title  # don't erase a title completely

def normalize_separators_inside_title(title: str) -> str:
    """
    Inside the title, squash any *consecutive* separator soup (e.g., ' - - ', ' .- ')
    down to a single ' - '. Single hyphens/dots within words are preserved.
    """
    if not title:
        return title
    # First collapse multi-sep runs to a single ' - '
    title = SEP_RUN.sub(' - ', title)
    # Remove accidental leading/trailing separator again
    title = re.sub(r'^[\s\.-]+', '', title)
    title = re.sub(r'[\s\.-]+$', '', title)
    # Finally collapse *consecutive* " - " occurrences (never allow ' -  - ')
    title = re.sub(r'(?:\s-\s){2,}', ' - ', title)
    return title

INVALID_FS_CHARS = r'<>:"/\\|?*\x00'  # conservative; Windows-safe
INVALID_FS_PATTERN = re.compile(r'[<>:"/\\|?*\x00]')

# strip leading track numbers and separators from filename-title
LEADING_TRACK_PATTERN = re.compile(
    r"""^\s*                # start
        (\d{1,3})           # one to three digits (track)
        (\s*[\.\-_\s]+)?    # common separators: dot, dash, underscore, spaces
        """,
    re.VERBOSE,
)

def sanitize_name(s: str) -> str:
    # Replace invalid FS chars with a space, collapse whitespace/dots
    s = INVALID_FS_PATTERN.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    # Avoid trailing dots/spaces (Windows)
    return s.rstrip(" .")

def title_from_filename(fname_stem: str) -> str:
    # Remove leading track numbers like "01 -", "1.", "07_"
    cleaned = LEADING_TRACK_PATTERN.sub("", fname_stem).strip()
    # Collapse extra spaces/hyphens left behind
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(" -_.")
    return cleaned or fname_stem
