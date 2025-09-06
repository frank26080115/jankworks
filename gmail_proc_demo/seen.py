# seen.py
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import List, Set, Optional


class SeenManager:
    """
    Manages a JSON file that stores a list of message IDs, ordered oldest -> newest.

    - load(): reads file into a list (order preserved) + a set (fast lookup)
    - add(msg_id): appends if not present; marks 'dirty'; auto-saves on first real add
                  or if >= autosave_interval seconds since last real add
    - save(): writes the last up-to-5000 IDs (newest at bottom) atomically, only if dirty
    - prune(): if file size > limit, keeps the newest half and rewrites file

    The on-disk format is a JSON array of strings: ["id1","id2",...], oldest->newest.
    """

    def __init__(self, path: str = "seen.json", file_size_limit: int = 1_000_000, msg_cnt_limit: int = 5000, autosave_interval: float = 5.0) -> None:
        """
        :param path: Path to the JSON file.
        :param file_size_limit: Max allowed file size in bytes for prune() checks.
        :param autosave_interval: Seconds between add() calls before triggering an autosave.
        """
        self.path: str = path
        self.file_size_limit: int = int(file_size_limit)
        self.msg_cnt_limit: int = int(msg_cnt_limit)
        self.autosave_interval: float = float(autosave_interval)

        self._ids_list: List[str] = []
        self._ids_set: Set[str] = set()

        # Tracks timing of the last *successful (mutating)* add
        self._last_add_ts: Optional[float] = None

        # Dirty flag: set True when in-memory state differs from disk due to add()
        self._dirty: bool = False

    def get_set(self) -> set:
        return self._ids_set

    # 🌱 Load --------------------------------------------------------------

    def load(self) -> None:
        """
        Loads the JSON file into an internal list (oldest->newest) and a set.
        Starts empty if file missing or invalid. Resets dirty flag.
        """
        if not os.path.exists(self.path):
            self._ids_list = []
            self._ids_set = set()
            self._dirty = False
            self._last_add_ts = None
            return

        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            self._ids_list = []
        else:
            self._ids_list = [str(x) for x in data]

        self._ids_set = set(self._ids_list)
        self._dirty = False
        self._last_add_ts = None

    # ➕ Add ---------------------------------------------------------------

    def add(self, msg_id: str) -> bool:
        """
        Adds a new message ID to the end (newest). If already present, no-op.
        On the first *real* add or if >= autosave_interval since last *real* add, calls save().
        :return: True if added; False if it was already present.
        """
        msg_id = str(msg_id)
        if msg_id in self._ids_set:
            # No mutation -> not dirty; do not autosave.
            return False

        # Mutate
        self._ids_list.append(msg_id)
        self._ids_set.add(msg_id)
        self._dirty = True

        # Autosave policy: first real add OR interval since last real add
        now = time.monotonic()
        should_save = (self._last_add_ts is None) or ((now - self._last_add_ts) >= self.autosave_interval)
        if should_save:
            self.save()
        self._last_add_ts = now

        return True

    # 💾 Save --------------------------------------------------------------

    def save(self) -> None:
        """
        Writes IDs to disk as JSON (array of strings), keeping only the last 5000 entries.
        Atomic replace. Skips if not dirty.
        """
        if not self._dirty:
            return

        # Trim to 5000 newest (bottom is newest)
        if len(self._ids_list) > self.msg_cnt_limit:
            self._ids_list = self._ids_list[-self.msg_cnt_limit:]
            self._ids_set = set(self._ids_list)

        # Ensure directory exists
        dirpath = os.path.dirname(os.path.abspath(self.path))
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath, exist_ok=True)

        # Atomic write
        fd, tmp_path = tempfile.mkstemp(prefix=".seen_tmp_", suffix=".json", dir=dirpath or None)
        os.close(fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._ids_list, f, ensure_ascii=False)
            os.replace(tmp_path, self.path)
            self._dirty = False
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # ✂️ Prune -------------------------------------------------------------

    def prune(self) -> bool:
        """
        If on-disk file exceeds size limit, keep only the newest half and rewrite.
        Refreshes in-memory state and clears dirty (disk is now in sync).
        :return: True if pruning happened; False otherwise.
        """
        if self.file_size_limit <= 0 or not os.path.exists(self.path):
            return False

        try:
            size = os.path.getsize(self.path)
        except OSError:
            return False

        if size <= self.file_size_limit:
            return False

        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list) or not data:
            return False

        half_idx = len(data) // 2
        kept = data[half_idx:]  # newest half

        # Atomic write
        dirpath = os.path.dirname(os.path.abspath(self.path))
        fd, tmp_path = tempfile.mkstemp(prefix=".seen_prune_", suffix=".json", dir=dirpath or None)
        os.close(fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(kept, f, ensure_ascii=False)
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        # Update memory & flags
        self._ids_list = [str(x) for x in kept]
        self._ids_set = set(self._ids_list)
        self._dirty = False
        # Keep _last_add_ts unchanged (prune is not an add)
        return True

    # 🧰 Utilities ---------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self._ids_list)

    def contains(self, msg_id: str) -> bool:
        return str(msg_id) in self._ids_set

    def __contains__(self, msg_id: str) -> bool:
        return self.contains(msg_id)

if __name__ == "__main__":
    sm = SeenManager()
    sm.prune()
