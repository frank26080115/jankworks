from logger_setup import logger
import os, time, pickle
from datetime import datetime, timedelta
from dateutil import parser
import re
from typing import Dict, TypeVar, Tuple, Dict
from rapidfuzz import fuzz

def unshorten_id(short_id: str) -> str:
    """
    Adds hyphens back to a Notion-style ID from a browser URL.

    Args:
        short_id (str): A 32-character string without hyphens

    Returns:
        str: A UUID in standard Notion format with hyphens
    """
    return f"{short_id[0:8]}-{short_id[8:12]}-{short_id[12:16]}-{short_id[16:20]}-{short_id[20:]}"

def shorten_id(uuid: str) -> str:
    """
    Removes hyphens from a standard Notion UUID.

    Args:
        uuid (str): A Notion UUID in the format 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'

    Returns:
        str: The shortened ID with hyphens removed
    """
    return uuid.replace("-", "")

K = TypeVar('K')
V = TypeVar('V')

def invert_dict(d: Dict[K, V]) -> Dict[V, K]:
    """
    Inverts a dictionary by swapping keys and values.

    Args:
        d (Dict[K, V]): The input dictionary.

    Returns:
        Dict[V, K]: A new dictionary with keys and values swapped.

    Raises:
        ValueError: If the original dictionary contains duplicate values.
    """
    if len(set(d.values())) != len(d):
        raise ValueError("Cannot invert dictionary with duplicate values.")
    return {v: k for k, v in d.items()}

def fuzzy_match_tag(needle: str, uid_to_tag: Dict[str, str], min_score: int = 85) -> Tuple[str | None, str | None]:
    """
    Finds the best fuzzy match for a potentially misspelled tag.

    Args:
        needle (str): The input string to match (possibly misspelled).
        uid_to_tag (Dict[str, str]): A dictionary mapping UID to tag.
        min_score (int): Minimum acceptable match score (0–100).

    Returns:
        Tuple[str | None, str | None]: The UID and tag of the best match, or (None, None) if below threshold.
    """
    best_score = -1
    best_uid = None
    best_tag = None

    for uid, tag in uid_to_tag.items():
        score = fuzz.ratio(needle.lower(), tag.lower())
        if score > best_score:
            best_score = score
            best_uid = uid
            best_tag = tag

    if best_score >= min_score:
        return best_uid, best_tag

    return None, None

def parse_fuzzy_date(text: str) -> datetime:
    """
    Parses a fuzzy human-readable date from a heading string.
    If a 4-digit year is found, truncates the string just after it before parsing.

    Args:
        text (str): Input string (e.g., "Sept 3 - 2025 NHRL Finals")

    Returns:
        datetime: Parsed date (fallback is today)
    """
    try:
        return parser.parse(text.strip(), dayfirst=False)
    except Exception:
        try:
            match = re.search(r"\b(\d{4})\b", text)
            if match:
                year_end = match.end()
                date_part = text[:year_end]
            else:
                date_part = text

            return parser.parse(date_part.strip(), dayfirst=False)
        except Exception as e:
            logger.warning(f"Could not parse date from heading: '{text}'. Using today. Error: {e}")
            return datetime.today()

def truncate_preview(text: str, max_length: int = 64) -> str:
    """
    Truncates text to a preview-friendly length with ellipsis if needed.

    Args:
        text (str): The input string.
        max_length (int): Max length before truncation.

    Returns:
        str: Truncated string with "..." if it was too long.
    """
    return text if len(text) <= max_length else text[:max_length - 3].rstrip() + "..."

def format_notion_date_heading(date_obj):
    return f"{date_obj.strftime('%b')} {date_obj.day} - {date_obj.year}"

def is_nonempty_block(block):
    if block.get("has_children"):
        return True

    block_type = block.get("type")
    if block_type.startswith("heading_"):
        return False

    block_data = block.get(block_type, {})
    rich_text = block_data.get("rich_text", [])
    if not rich_text:
        return False

    # Check if any content has non-whitespace characters
    return any(
        t.get("type") == "text" and t.get("text", {}).get("content", "").strip()
        for t in rich_text
    )

def is_recent_block(block, months=2):
    created_time_str = block.get("created_time")
    if not created_time_str:
        return False
    created_time = datetime.fromisoformat(created_time_str.rstrip("Z"))
    return created_time >= datetime.now() - timedelta(days=30 * months)

def has_real_content(under_blocks):
    return any(is_nonempty_block(b) for b in under_blocks)

def get_rich_text_content(block: dict) -> str:
    """
    Extract and concatenate all rich_text fragments from a Notion block.
    Includes fallback handling for mentions and equations.
    """
    block_type = block.get("type")
    data = block.get(block_type, {})
    rich_text = data.get("rich_text", [])

    parts = []

    for span in rich_text:
        t = span.get("type")
        if t == "text":
            text = span["text"]["content"].strip()
            if len(text.strip()) > 0:
                annotations = span.get("annotations", {})
                if annotations.get("strikethrough"):
                    text = f"~~{text}~~"
            parts.append(text)
        elif t == "mention":
            m = span["mention"]
            if "user" in m:
                parts.append(f"@{m['user'].get('name', 'user')}")
            elif "page" in m:
                parts.append("[page mention]")
            elif "date" in m:
                parts.append(m["date"].get("start", "[date]"))
            else:
                parts.append("[mention]")
        elif t == "equation":
            m = span["equation"]
            parts.append(m["equation"].get("expression", "[equation]"))
        else:
            parts.append(f"[{t}]")

    return ("".join(parts)).strip()

def load_cache_set(path):
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return pickle.load(f)
    return set()

def load_cache_dict(path):
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return pickle.load(f)
    return dict()

def get_last_edited_datetime(block: dict) -> datetime:
    """
    Extracts the 'last_edited_time' from a Notion block object and returns it as a Python datetime object.
    Assumes the timestamp is in ISO 8601 format with 'Z' for UTC (e.g., "2025-07-25T17:04:11.000Z").
    """
    iso_string = block.get("last_edited_time")
    if not iso_string:
        return None

    # Replace 'Z' with '+00:00' for proper ISO 8601 parsing in Python
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))

def get_created_time_datetime(block: dict) -> datetime:
    """
    Extracts the 'created_time' from a Notion block object and returns it as a Python datetime object.
    Assumes the timestamp is in ISO 8601 format with 'Z' for UTC (e.g., "2025-07-25T17:04:11.000Z").
    """
    iso_string = block.get("created_time")
    if not iso_string:
        return None

    # Replace 'Z' with '+00:00' for proper ISO 8601 parsing in Python
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))

def normalize_checkboxes(text: str, empty_box: str = "☐", checked_box: str = "☑", checkmark: str = "✓") -> str:
    # Known variants
    empty_box_variants = [
        "☐", "□", "[ ]", "🟦", "🔲"
    ]
    checked_box_variants = [
        "☑", "☒", "[x]", "[X]", "🗹", "🗷", "✅"
    ]
    checkmark_variants = [
        "✓", "✔", "✔️", "🗸"
    ]

    # Do replacements
    for symbol in empty_box_variants:
        text = text.replace(symbol, empty_box)

    for symbol in checked_box_variants:
        text = text.replace(symbol, checked_box)

    for symbol in checkmark_variants:
        text = text.replace(symbol, checkmark)

    return text

def find_last_url_in_block(block: dict) -> str | None:
    """
    Recursively search a Notion block object for any URLs and return the last one found.
    Returns None if no URL is found.
    """
    url_pattern = re.compile(
        r'https?://[^\s\'",)}\]]+'
    )
    last_url = None

    def search(obj):
        nonlocal last_url
        if isinstance(obj, dict):
            for value in obj.values():
                search(value)
        elif isinstance(obj, list):
            for item in obj:
                search(item)
        elif isinstance(obj, str):
            matches = url_pattern.findall(obj)
            if matches:
                last_url = matches[-1]  # Update to most recent found

    search(block)
    return last_url

def format_uuid_for_notion(uuid_str: str) -> str:
    # Ensure it's the right length and all lowercase
    s = uuid_str.lower().replace('-', '')
    if len(s) != 32:
        raise ValueError("UUID must be 32 characters long without hyphens")
    return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"

def normalize_uuid(s: str) -> str | None:
    """
    Extracts and normalizes a UUID from a string.
    Strips URLs, removes dashes, and converts to lowercase.
    Returns None if no 32-character hex string is found.
    """
    if not isinstance(s, str):
        return None

    # Match a UUID (with or without dashes)
    match = re.search(r'[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', s)
    if not match:
        return None

    raw = match.group(0).replace("-", "").lower()
    return raw if len(raw) == 32 else None

def uuids_equal(a: str, b: str) -> bool:
    """
    Compares two strings that may represent UUIDs in various formats.
    Returns True if they are equivalent UUIDs.
    """
    norm_a = normalize_uuid(a)
    norm_b = normalize_uuid(b)
    return norm_a == norm_b
