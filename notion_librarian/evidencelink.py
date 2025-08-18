from typing import Optional, Dict, Any, Iterable, List, Tuple
from notion_client import Client
import difflib
import re
import myutils

# ----------------------------
# Helpers: text extraction
# ----------------------------

_whitespace_re = re.compile(r"\s+")
_word_re = re.compile(r"\w+", re.UNICODE)

def _normalize(s: str) -> str:
    return _whitespace_re.sub(" ", (s or "").strip().casefold())

def _tokenize(s: str) -> List[str]:
    return _word_re.findall((s or "").casefold())

def _rich_text_to_plain(items: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for it in items or []:
        # 'plain_text' is safest cross-type
        txt = it.get("plain_text")
        if txt is None:
            # Fallback if present
            text = it.get("text") or {}
            txt = text.get("content", "")
        if txt:
            parts.append(txt)
    return "".join(parts)

def _extract_block_text(block: Dict[str, Any]) -> str:
    """Best-effort user-visible text from a Notion block."""
    t = block.get("type")
    if not t:
        return ""
    data = block.get(t, {}) or {}

    # Rich text–bearing blocks
    if t in {
        "paragraph","heading_1","heading_2","heading_3",
        "bulleted_list_item","numbered_list_item","to_do",
        "toggle","quote","callout","code"
    }:
        return _rich_text_to_plain(data.get("rich_text", []))

    # Media / link-ish blocks: include URL + caption
    if t in {"bookmark","embed","video","file","pdf","image","audio"}:
        parts: List[str] = []
        url = data.get("url")  # bookmark/embed
        if url:
            parts.append(str(url))
        caption = _rich_text_to_plain(data.get("caption", []))
        if caption:
            parts.append(caption)
        return " ".join(p for p in parts if p)

    if t == "equation":
        return str(data.get("expression") or "")

    if t == "table_row":
        # cells: List[List[rich_text]]
        cells = data.get("cells", [])
        flat = []
        for cell in cells:
            flat.append(_rich_text_to_plain(cell))
        return " | ".join(s for s in flat if s)

    if t == "child_page":
        return str(data.get("title") or "")

    # Structural containers (synced_block/table/etc) → children will be visited anyway
    # Try captions if available
    cap = _rich_text_to_plain(data.get("caption", [])) if isinstance(data, dict) else ""
    return cap

# ----------------------------
# Helpers: similarity scoring
# ----------------------------

def _similarity(evidence: str, text: str) -> Tuple[bool, float]:
    """
    Returns (is_exact_substring, score in [0,1]).
    Score blends:
      - best contiguous match coverage
      - token Jaccard
      - global ratio
    """
    ev = _normalize(evidence)
    tx = _normalize(text)
    if not ev or not tx:
        return (False, 0.0)

    # Exact substring (case-insensitive) wins instantly
    if ev in tx:
        return (True, 1.0)

    sm = difflib.SequenceMatcher(a=ev, b=tx, autojunk=False)
    m = sm.find_longest_match(0, len(ev), 0, len(tx))
    coverage = m.size / max(1, len(ev))

    # Token Jaccard
    ev_tok = set(_tokenize(ev))
    tx_tok = set(_tokenize(tx))
    if ev_tok and tx_tok:
        inter = len(ev_tok & tx_tok)
        union = len(ev_tok | tx_tok)
        jacc = inter / union if union else 0.0
    else:
        jacc = 0.0

    ratio = sm.ratio()

    score = max(
        0.85 * coverage + 0.15 * ratio,
        0.75 * jacc + 0.25 * ratio,
    )
    return (False, float(score))

# ----------------------------
# Helpers: traversal via notion-client
# ----------------------------

def _iter_children(client: Client, parent_block_id: str) -> Iterable[Dict[str, Any]]:
    """Yield direct children of a block (handles pagination, preserves order)."""
    cursor = None
    while True:
        resp = client.blocks.children.list(block_id=parent_block_id, start_cursor=cursor)
        for b in resp.get("results", []):
            yield b
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

def _dfs_blocks(client: Client, root_block_id: str) -> Iterable[Dict[str, Any]]:
    """Depth-first traversal yielding blocks in visual order (parent before descendants)."""
    stack: List[Iterable[Dict[str, Any]]] = [_iter_children(client, root_block_id)]
    while stack:
        it = stack[-1]
        try:
            blk = next(it)
        except StopIteration:
            stack.pop()
            continue
        yield blk
        if blk.get("has_children"):
            stack.append(_iter_children(client, blk["id"]))

# ----------------------------
# Main function
# ----------------------------

def find_block_by_evidence(
    notion_token: str,
    page_id: str,
    evidence: str,
    start_block_id: Optional[str] = None,
    *,
    min_score: float = 0.78,
) -> Optional[str]:
    """
    Find the Notion block within a page that most likely contains `evidence`.

    Args:
        notion_token: Notion integration token (secret_...).
        page_id: The page ID (uuid or with hyphens).
        evidence: Short string you expect to appear in some block's text.
        start_block_id: If provided, only consider matches that appear *after* this block in order.
        min_score: Minimum fuzzy threshold to accept (exact substring always accepted).

    Returns:
        Matching block_id (str) if found, else None.
        If start_block_id is provided but never encountered, returns None.
    """
    client = Client(auth=notion_token)

    after_start = start_block_id is None or not start_block_id
    best_score = 0.0
    best_block_id: Optional[str] = None

    for blk in _dfs_blocks(client, page_id):
        blk_id = blk.get("id")

        # Flip the "after" gate once we hit the start
        if start_block_id and myutils.uuids_equal(blk_id, start_block_id):
            after_start = True
            # Do NOT evaluate the start block itself; continue
            continue

        if not after_start:
            continue

        text = _extract_block_text(blk)
        exact, score = _similarity(evidence, text)

        if exact:
            return blk_id

        if score >= min_score and score > best_score:
            best_score = score
            best_block_id = blk_id

    return best_block_id
