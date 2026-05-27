from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


OPEN_TABS_HEADING_RE = re.compile(r"^\s*##\s+Open tabs:\s*$")
SECTION_HEADING_RE = re.compile(r"^\s*##\s+\S")


def text_from_history_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return None


def history_value_from_text(text: str) -> str | list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in normalized:
        return normalized
    return normalized.splitlines()


def strip_open_tabs_sections(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    result: list[str] = []
    changed = False
    index = 0

    while index < len(lines):
        line = lines[index]
        if not OPEN_TABS_HEADING_RE.match(line):
            result.append(line)
            index += 1
            continue

        end = index + 1
        while end < len(lines) and not SECTION_HEADING_RE.match(lines[end]):
            end += 1

        if end >= len(lines):
            result.append(line)
            index += 1
            continue

        if result and result[-1] and lines[end].strip():
            result.append("")
        index = end
        changed = True

    return "\n".join(result) if changed else text


def read_history_file(path: Path) -> list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError(f"{path} does not contain a JSON array")

    return data


def write_json_array_atomic(path: Path, items: list[Any]) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=os.fspath(path.parent),
        text=True,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(items, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def clean_history_file(path: Path) -> bool:
    items = read_history_file(path)
    changed = False

    for item in items:
        if not isinstance(item, dict) or "user_prompt" not in item:
            continue

        original_text = text_from_history_value(item["user_prompt"])
        if original_text is None:
            continue

        cleaned_text = strip_open_tabs_sections(original_text)
        if cleaned_text == original_text:
            continue

        item["user_prompt"] = history_value_from_text(cleaned_text)
        changed = True

    if changed:
        write_json_array_atomic(path, items)

    return changed


def iter_history_files(history_root: Path) -> list[Path]:
    return sorted(history_root.rglob("*.codexhist.json"), key=lambda path: os.fspath(path))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove IDE Open tabs sections from Codex history user_prompt fields."
    )
    parser.add_argument("project_root", help="Project root containing the .codex_history directory.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).expanduser().resolve(strict=False)
    if not project_root.is_dir():
        parser.error(f"project root does not exist or is not a directory: {project_root}")

    history_root = project_root / ".codex_history"
    if not history_root.is_dir():
        parser.error(f"history directory does not exist: {history_root}")

    scanned = 0
    cleaned = 0
    skipped = 0

    for history_file in iter_history_files(history_root):
        scanned += 1
        try:
            if clean_history_file(history_file):
                cleaned += 1
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            skipped += 1
            print(f"warning: skipped {history_file}: {exc}", file=sys.stderr)

    print(f"Scanned {scanned} history file(s).")
    print(f"Cleaned {cleaned} history file(s), skipped {skipped}.")
    print(f"History root: {history_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
