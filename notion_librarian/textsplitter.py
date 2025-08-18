import re
import math
from typing import List, Tuple

def rough_token_estimate(text: str) -> int:
    pattern = re.compile(
        r"[A-Za-z]+|\d+|"
        r"[\u4e00-\u9fff]|"              # CJK ideographs
        r"[\u3040-\u30ff]|"              # Japanese kana
        r"[\uAC00-\uD7AF]|"              # Hangul
        r"[\U0001F300-\U0001FAFF]|"      # Emoji
        r"[^A-Za-z0-9\s]"                # punctuation/symbols
    )
    tokens = pattern.findall(text)
    return math.ceil(len(tokens) * 1.2)  # +20% for subword-ish behavior


def _split_markdown_into_blocks(md: str) -> List[str]:
    """
    Split markdown into logical blocks:
      - fenced code blocks kept intact
      - headings as separate blocks
      - paragraphs / lists separated by blank lines
    """
    lines = md.splitlines()
    blocks: List[str] = []
    buf: List[str] = []
    in_fence = False
    fence_delim = None

    def flush():
        if buf:
            # collapse leading/trailing blank lines in a block
            # but keep internal newlines intact
            start = 0
            end = len(buf)
            while start < end and not buf[start].strip():
                start += 1
            while end > start and not buf[end-1].strip():
                end -= 1
            if start < end:
                blocks.append("\n".join(buf[start:end]))
            buf.clear()

    i = 0
    while i < len(lines):
        ln = lines[i]

        # Detect start/end of fenced code blocks (``` or ~~~)
        fence_match = re.match(r"^(\s*)(`{3,}|~{3,})(.*)$", ln)
        if fence_match:
            # Start or end of a fence
            if not in_fence:
                # entering fence
                flush()
                in_fence = True
                fence_delim = fence_match.group(2)
                buf.append(ln)
            else:
                # leaving fence — only if delimiter matches length/type
                buf.append(ln)
                in_fence = False
                fence_delim = None
                flush()
            i += 1
            continue

        if in_fence:
            buf.append(ln)
            i += 1
            continue

        # Headings start a new block
        if re.match(r"^\s*#{1,6}\s+\S", ln):
            flush()
            blocks.append(ln.rstrip())
            i += 1
            continue

        # Blank line = block boundary (paragraph/list breaker)
        if not ln.strip():
            buf.append(ln)
            flush()
            i += 1
            continue

        # Otherwise, accumulate normal text/list lines
        buf.append(ln)
        i += 1

    flush()
    return blocks


def _accumulate_blocks_to_limit(
    blocks: List[str], start_idx: int, token_limit: int
) -> Tuple[int, str]:
    """
    From start_idx, pack as many whole blocks as possible within token_limit.
    If the very first block doesn't fit, fall back to line-splitting that block.
    Returns (end_idx_exclusive, chunk_text).
    """
    total = 0
    i = start_idx
    packed: List[str] = []

    while i < len(blocks):
        blk = blocks[i]
        t = rough_token_estimate(blk)
        if total + t <= token_limit or not packed:
            if total + t <= token_limit:
                packed.append(blk)
                total += t
                i += 1
            else:
                # First block alone exceeds limit -> split by lines
                sub = _split_block_by_lines_to_limit(blk, token_limit)
                packed.append(sub)
                i = i  # remain on same block; caller decides next start via overlap
                break
        else:
            break

    chunk = "\n\n".join(packed).strip()
    return i, chunk


def _split_block_by_lines_to_limit(block: str, token_limit: int) -> str:
    """
    Fallback when a single block is too large: take as many lines as fit.
    """
    lines = block.splitlines()
    acc: List[str] = []
    total = 0
    for ln in lines:
        t = rough_token_estimate(ln + "\n")
        if total + t > token_limit:
            break
        acc.append(ln)
        total += t
    # If even one line doesn't fit, hard truncate characters
    if not acc:
        text = block
        # binary shrink by characters
        lo, hi = 1, max(1, len(text))
        best = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            cand = text[:mid]
            if rough_token_estimate(cand) <= token_limit:
                best = cand
                lo = mid + 1
            else:
                hi = mid - 1
        return best
    return "\n".join(acc)


def windowed_markdown_chunks(md: str, token_limit: int = 6000, overlap_ratio: float = 0.5) -> List[str]:
    """
    If md fits within token_limit -> [md].
    Otherwise, split into ~token_limit windows with ~overlap_ratio overlap (default 50%).

    Returns a list of chunk strings (markdown).
    """
    assert 0.0 < overlap_ratio < 1.0, "overlap_ratio must be in (0,1)"
    total_tokens = rough_token_estimate(md)
    if total_tokens <= token_limit:
        return [md]

    # 1) Split into structure-aware blocks
    blocks = _split_markdown_into_blocks(md)
    if not blocks:
        return []

    # Precompute token counts and prefix sums
    tok = [rough_token_estimate(b) for b in blocks]
    prefix = [0]
    for t in tok:
        prefix.append(prefix[-1] + t)

    # stride in tokens = (1 - overlap) * limit
    stride_tokens = max(1, int(round(token_limit * (1.0 - overlap_ratio))))

    chunks: List[str] = []
    start_token = 0
    n = len(blocks)

    def idx_from_token(tokpos: int) -> int:
        # earliest block index whose prefix >= tokpos
        # linear scan is fine for modest block counts; could binary-search if needed
        for i in range(len(prefix)):
            if prefix[i] >= tokpos:
                return max(0, i - 1)
        return n - 1

    start_idx = 0
    while start_idx < n:
        # Pack from start_idx up to limit
        end_idx_excl, chunk = _accumulate_blocks_to_limit(blocks, start_idx, token_limit)
        if not chunk:
            break
        chunks.append(chunk)

        # Compute next start by tokens: end_token - overlap_window
        # Determine the token span of the produced chunk:
        start_tok_span = prefix[start_idx]
        end_tok_span = prefix[end_idx_excl] if end_idx_excl > start_idx else min(prefix[start_idx] + rough_token_estimate(chunk), prefix[-1])
        next_start_token = max(0, end_tok_span - int(round(token_limit * overlap_ratio)))
        start_idx = idx_from_token(next_start_token)

        # Avoid infinite loops if we didn't advance and can't split more
        if chunks and len(chunks) > 1:
            # ensure we progress by at least one block
            prev_start_idx = idx_from_token(max(0, end_tok_span - int(round(token_limit * overlap_ratio))))
            if prev_start_idx == start_idx and end_idx_excl == start_idx:
                start_idx += 1

        # If we didn't consume any blocks (e.g., block too huge and we only line-split),
        # advance token start by stride
        if end_idx_excl == start_idx:
            start_token = end_tok_span - int(round(token_limit * overlap_ratio))
            start_token = max(0, min(start_token + stride_tokens, prefix[-1] - 1))
            start_idx = idx_from_token(start_token)

        # If we are at the last block and it's already packed, exit
        if end_idx_excl >= n:
            break
        # Safety: if window did not advance in blocks, nudge one forward
        if end_idx_excl == start_idx:
            start_idx = min(n - 1, start_idx + 1)

        # If we're going to produce a duplicate tail (tiny remainder), stop
        if start_idx >= n:
            break

    # Deduplicate near-duplicates at the tail if any
    deduped: List[str] = []
    seen = set()
    for c in chunks:
        key = (len(c), c[:64], c[-64:])
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped
