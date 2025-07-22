from logger_setup import logger

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

from typing import Dict, TypeVar

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

from typing import Tuple, Dict
from rapidfuzz import fuzz

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
        return (best_uid, best_tag)

    return (None, None)

from dateutil import parser
from datetime import datetime
import re

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
    except Exception as e1:
        try:
            match = re.search(r"\b(\d{4})\b", text)
            if match:
                year_end = match.end()
                date_part = text[:year_end]
            else:
                date_part = text

            return parser.parse(date_part.strip(), dayfirst=False)
        except Exception as e2:
            logger.warning(f"Could not parse date from heading: '{text}'. Using today. Error: {e2}")
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

def has_real_content(under_blocks):
    return any(is_nonempty_block(b) for b in under_blocks)
