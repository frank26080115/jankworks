from pathlib import Path
from difflib import SequenceMatcher
import hashlib
from typing import List, Tuple, Optional

def _sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def _top_n_fuzzy_candidates(target_name: str, candidates: List[Path], n: int = 3) -> List[Tuple[Path, float]]:
    """Rank candidates by fuzzy similarity to target_name (case-insensitive) and return top n."""
    target = target_name.lower()
    scored = []
    for p in candidates:
        name = p.name.lower()
        score = SequenceMatcher(None, target, name).ratio()
        scored.append((p, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:n]

def exists_as_exact_match_in_dest(src_path: str, new_dest_path: str, topn: int = 3) -> Tuple[bool, Optional[str]]:
    """
    Look in the destination directory for:
      - top-N fuzzy filename matches vs. the proposed new filename
      - the single closest file-size match (by absolute byte difference)

    For the union of these candidates:
      - if file size equals the source, compare SHA-256 to confirm exact content
    Returns:
      (exact_match_found: bool, best_name: Optional[str])
        - best_name = exact-match name if found,
                      else best fuzzy name if available,
                      else closest-size name if available,
                      else None
    """
    src = Path(src_path)
    if not src.is_file():
        return False, None

    dest = Path(new_dest_path)
    dest_dir = dest.parent
    if not dest_dir.exists() or not dest_dir.is_dir():
        return False, None

    # Collect files in destination directory
    dest_files = [p for p in dest_dir.iterdir() if p.is_file()]
    if not dest_files:
        return False, None

    # --- Candidate set 1: Top N fuzzy by name
    fuzzy = _top_n_fuzzy_candidates(dest.name, dest_files, n=topn)
    fuzzy_paths = [p for p, _ in fuzzy]

    # --- Candidate set 2: Closest by size
    try:
        src_size = src.stat().st_size
    except OSError:
        return False, None

    # Find single closest-size file (min absolute diff)
    closest_size_path: Optional[Path] = None
    closest_diff: Optional[int] = None
    for p in dest_files:
        try:
            sz = p.stat().st_size
        except OSError:
            continue
        diff = abs(sz - src_size)
        if closest_diff is None or diff < closest_diff:
            closest_diff = diff
            closest_size_path = p

    # Union of candidates (preserve order preference: fuzzy first)
    candidate_order: List[Path] = []
    seen = set()
    for p in fuzzy_paths:
        if p not in seen:
            candidate_order.append(p)
            seen.add(p)
    if closest_size_path and closest_size_path not in seen:
        candidate_order.append(closest_size_path)
        seen.add(closest_size_path)

    # Preselect "best_name" fallback (prefer top fuzzy; else closest-size; else None)
    best_name: Optional[str] = None
    if fuzzy_paths:
        best_name = fuzzy_paths[0].name
    elif closest_size_path:
        best_name = closest_size_path.name

    # Now do exact-match checks: size gate -> hash
    for cand in candidate_order:
        try:
            if cand.stat().st_size != src_size:
                continue
        except OSError:
            continue
        # Size matches — verify content by hash
        try:
            if _sha256(cand) == _sha256(src):
                return True, cand.name
        except OSError:
            continue

    return False, best_name
