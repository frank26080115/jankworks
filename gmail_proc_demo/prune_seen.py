import os
import json
import tempfile
from datetime import datetime

def prune_seen(path: str = "seen.json", max_bytes: int = 1_000_000) -> bool:
    """
    If `path` (a JSON file) is > max_bytes, keep only the most recent half and rewrite the file.
    Assumes the JSON is either:
      - a LIST of message IDs in chronological *append* order (newest at the end), or
      - a DICT mapping message_id -> timestamp (ISO8601 or epoch seconds).

    Returns True if pruning occurred, else False.
    """
    if not os.path.exists(path):
        return False

    try:
        size = os.path.getsize(path)
        if size <= max_bytes:
            return False

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Decide how to keep the "most recent half"
        if isinstance(data, list):
            if not data:
                return False
            # Keep back half (assumes append order => newest at end)
            keep = data[len(data)//2 :]

        elif isinstance(data, dict):
            if not data:
                return False

            def ts_value(v):
                # Accept epoch (int/float) or ISO8601-ish strings; otherwise treat as 0
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    try:
                        # Allow 'Z' suffix by replacing with UTC offset
                        iso = v.replace("Z", "+00:00")
                        return datetime.fromisoformat(iso).timestamp()
                    except Exception:
                        try:
                            return float(v)
                        except Exception:
                            return 0.0
                return 0.0

            # Sort entries by timestamp DESC (newest first), keep half
            items = sorted(data.items(), key=lambda kv: ts_value(kv[1]), reverse=True)
            half = max(1, len(items)//2)
            keep = {k: v for k, v in items[:half]}

        else:
            # Unknown structure; bail out safely
            return False

        # Atomic write
        dirn = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(prefix=".seen_prune_", suffix=".json", dir=dirn)
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True

    except Exception:
        # Don't destroy the original file if anything goes wrong
        return False

if __name__ == "__main__":
    prune_seen()
