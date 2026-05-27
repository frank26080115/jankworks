from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator


MARKDOWN_LINK_TARGET_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
OPEN_TABS_HEADING_RE = re.compile(r"^\s*##\s+Open tabs:\s*$")
FENCED_CODE_BLOCK_RE = re.compile(r"^\s{0,3}(?:```|~~~)")
FILE_REFERENCE_RE = re.compile(
    r"""
    (?:
        [A-Za-z]:[\\/][^\s`'")\]]+
      | /[A-Za-z]:[\\/][^\s`'")\]]+
      | /(?:[A-Za-z0-9_.@+-]+[\\/])+[A-Za-z0-9_.@+-]+\.[A-Za-z][A-Za-z0-9]{0,11}
      | (?:\.{1,2}[\\/])?(?:[A-Za-z0-9_.@+-]+[\\/])+[A-Za-z0-9_.@+-]+\.[A-Za-z][A-Za-z0-9]{0,11}
      | [A-Za-z_][A-Za-z0-9_.@+-]*\.[A-Za-z][A-Za-z0-9]{0,11}
    )
    """,
    re.VERBOSE,
)
COMMON_FILE_EXTENSIONS = {
    ".bat",
    ".bin",
    ".c",
    ".cc",
    ".cfg",
    ".cmd",
    ".cmake",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".cxx",
    ".gif",
    ".go",
    ".gradle",
    ".h",
    ".hpp",
    ".htm",
    ".html",
    ".hxx",
    ".ico",
    ".ini",
    ".ino",
    ".java",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".kt",
    ".kts",
    ".ld",
    ".lock",
    ".mjs",
    ".md",
    ".pdf",
    ".php",
    ".png",
    ".ps1",
    ".py",
    ".pyw",
    ".rb",
    ".rs",
    ".s",
    ".scss",
    ".sh",
    ".sql",
    ".svg",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vcxproj",
    ".webp",
    ".xml",
    ".yaml",
    ".yml",
}
COMMON_EXTENSIONLESS_FILES = {
    "Dockerfile",
    "LICENSE",
    "Makefile",
    "README",
    "VERSION",
}


@dataclass
class CodexTask:
    date: str
    user_message: str
    final_reply_message: str = ""
    files: list[str] = field(default_factory=list)
    _final_reply_keys: set[tuple[str, str]] = field(default_factory=set, repr=False)

    def add_final_reply(self, timestamp: str, text: str) -> None:
        text = text.strip()
        if not text:
            return

        key = (timestamp, text)
        if key in self._final_reply_keys:
            return

        self._final_reply_keys.add(key)
        if self.final_reply_message:
            self.final_reply_message += "\n\n" + text
        else:
            self.final_reply_message = text


@dataclass(frozen=True)
class GitCommit:
    date: str
    commit_hash: str
    message: str


@dataclass(frozen=True)
class ProjectFileReference:
    path: Path
    relative: Path
    is_bare: bool = False


def subtract_months(value: date, months: int) -> date:
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1

    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def parse_start_date(value: str) -> date:
    value = value.strip()
    if not value:
        raise ValueError("start date cannot be empty")

    if len(value) == 10:
        return date.fromisoformat(value)

    return parse_timestamp(value).date()


def parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    if "." in value:
        head, tail = value.split(".", 1)
        zone_index = max(tail.find("+"), tail.find("-"))
        if zone_index == -1:
            fractional = tail
            zone = ""
        else:
            fractional = tail[:zone_index]
            zone = tail[zone_index:]
        if len(fractional) > 6:
            value = f"{head}.{fractional[:6]}{zone}"

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: str) -> str:
    parsed = parse_timestamp(value)
    prefix = parsed.strftime("%Y-%m-%dT%H:%M:%S")
    if parsed.microsecond:
        milliseconds = parsed.microsecond // 1000
        return f"{prefix}.{milliseconds:03d}Z"
    return f"{prefix}Z"


def timestamp_sort_key(value: str) -> tuple[int, str]:
    try:
        return (0, parse_timestamp(value).isoformat())
    except (TypeError, ValueError, AttributeError):
        return (1, str(value))


def strip_open_tabs_section(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    result: list[str] = []
    in_code_block = False
    removed = False
    index = 0

    while index < len(lines):
        line = lines[index]
        if FENCED_CODE_BLOCK_RE.match(line):
            in_code_block = not in_code_block
            result.append(line)
            index += 1
            continue

        if not in_code_block and OPEN_TABS_HEADING_RE.match(line):
            end = index + 1
            section_in_code_block = False
            while end < len(lines):
                section_line = lines[end]
                if FENCED_CODE_BLOCK_RE.match(section_line):
                    section_in_code_block = not section_in_code_block
                elif not section_in_code_block and MARKDOWN_HEADING_RE.match(section_line):
                    break
                end += 1

            if end < len(lines):
                if result and result[-1] and lines[end].strip():
                    result.append("")
                index = end
                removed = True
                continue

        result.append(line)
        index += 1

    return "\n".join(result) if removed else text


def path_key(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def resolve_existing_or_future_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def normalize_markdown_path(target: str) -> str:
    target = target.strip().strip("<>").strip("`'\"")
    target = target.rstrip(".,;")
    if target.startswith("file://"):
        target = target[len("file://") :]
    if re.match(r"^/[A-Za-z]:[/\\]", target):
        target = target[1:]

    line_suffix = re.match(r"^(.+):\d+(?::\d+)?$", target)
    if line_suffix and not re.match(r"^[A-Za-z]:\\?$", target):
        target = line_suffix.group(1)

    return target


def is_plausible_file_reference(reference: str) -> bool:
    normalized = reference.replace("\\", "/")
    if "://" in normalized:
        return False

    name = Path(normalized).name
    if name in COMMON_EXTENSIONLESS_FILES:
        return True

    suffix = Path(normalized).suffix.lower()
    if suffix in COMMON_FILE_EXTENSIONS:
        return True

    is_absolute = bool(re.match(r"^(?:[A-Za-z]:|/[A-Za-z]:|/)", normalized))
    has_separator = "/" in normalized
    return bool(suffix) and (is_absolute or has_separator)


def file_references_from_text(text: str) -> list[str]:
    references: list[str] = []

    def append(reference: str) -> None:
        reference = normalize_markdown_path(reference)
        if reference and is_plausible_file_reference(reference) and reference not in references:
            references.append(reference)

    for match in MARKDOWN_LINK_TARGET_RE.finditer(text):
        append(match.group(1))

    text_without_markdown_links = MARKDOWN_LINK_TARGET_RE.sub(" ", text)
    for match in FILE_REFERENCE_RE.finditer(text_without_markdown_links):
        append(match.group(0))

    return references


def relative_to_project(candidate: Path, project_root: Path) -> Path | None:
    candidate_key = path_key(candidate)
    project_key = path_key(project_root)

    try:
        common = os.path.commonpath([candidate_key, project_key])
    except ValueError:
        return None

    if common != project_key:
        return None

    relative = os.path.relpath(os.fspath(candidate), os.fspath(project_root))
    if relative == ".":
        return None
    return Path(relative)


def has_dot_directory(relative_path: Path) -> bool:
    return any(part.startswith(".") for part in relative_path.parts[:-1])


def short_name_key(file_name: str) -> str:
    return os.path.normcase(file_name)


def is_bare_file_name(path_text: str) -> bool:
    return (
        not re.match(r"^(?:[A-Za-z]:|/[A-Za-z]:|/)", path_text)
        and "/" not in path_text
        and "\\" not in path_text
    )


def find_project_files_by_name(file_name: str, project_root: Path) -> list[Path]:
    matches: list[Path] = []
    file_name_key = os.path.normcase(file_name)

    for directory, dirnames, filenames in os.walk(project_root):
        dirnames[:] = sorted(dirname for dirname in dirnames if not dirname.startswith("."))

        directory_path = Path(directory)
        for filename in sorted(filenames):
            if os.path.normcase(filename) != file_name_key:
                continue
            matches.append(resolve_existing_or_future_path(directory_path / filename))

    return matches


def project_file_from_raw_path(raw_path: str, project_root: Path) -> ProjectFileReference | None:
    cleaned = normalize_markdown_path(raw_path)
    if not cleaned:
        return None

    is_bare = is_bare_file_name(cleaned)
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate

    candidate = resolve_existing_or_future_path(candidate)
    relative = relative_to_project(candidate, project_root)
    if relative is None or has_dot_directory(relative):
        return None

    return ProjectFileReference(candidate, relative, is_bare)


def best_project_file_by_name(file_name: str, project_root: Path) -> ProjectFileReference | None:
    best: ProjectFileReference | None = None

    for candidate in find_project_files_by_name(file_name, project_root):
        relative = relative_to_project(candidate, project_root)
        if relative is None or has_dot_directory(relative):
            continue

        reference = ProjectFileReference(candidate, relative)
        if best is None or len(reference.relative.parts) > len(best.relative.parts):
            best = reference

    return best


def remember_short_name_target(
    reference: ProjectFileReference,
    short_name_paths: dict[str, ProjectFileReference],
) -> None:
    key = short_name_key(reference.relative.name)
    existing = short_name_paths.get(key)
    if existing is None or len(reference.relative.parts) > len(existing.relative.parts):
        short_name_paths[key] = reference


def add_project_file(
    task: CodexTask,
    reference: ProjectFileReference,
    file_tasks: dict[str, list[CodexTask]],
    file_paths: dict[str, Path],
) -> None:
    relative_text = reference.relative.as_posix()
    if relative_text not in task.files:
        task.files.append(relative_text)

    key = path_key(reference.path)
    file_paths.setdefault(key, reference.path)
    tasks = file_tasks.setdefault(key, [])
    if not any(existing is task for existing in tasks):
        tasks.append(task)


def add_touched_file(
    task: CodexTask,
    raw_path: str,
    project_root: Path,
    file_tasks: dict[str, list[CodexTask]],
    file_paths: dict[str, Path],
    bare_file_tasks: dict[str, list[CodexTask]],
    bare_file_names: dict[str, str],
    short_name_paths: dict[str, ProjectFileReference],
) -> bool:
    reference = project_file_from_raw_path(raw_path, project_root)
    if reference is None:
        return False

    if reference.is_bare:
        key = short_name_key(reference.relative.name)
        bare_file_names.setdefault(key, reference.relative.name)
        tasks = bare_file_tasks.setdefault(key, [])
        if not any(existing is task for existing in tasks):
            tasks.append(task)
        return True

    add_project_file(task, reference, file_tasks, file_paths)
    remember_short_name_target(reference, short_name_paths)
    return True


def add_touched_files_from_text(
    task: CodexTask,
    text: str,
    project_root: Path,
    file_tasks: dict[str, list[CodexTask]],
    file_paths: dict[str, Path],
    bare_file_tasks: dict[str, list[CodexTask]],
    bare_file_names: dict[str, str],
    short_name_paths: dict[str, ProjectFileReference],
) -> None:
    for reference in file_references_from_text(text):
        add_touched_file(
            task,
            reference,
            project_root,
            file_tasks,
            file_paths,
            bare_file_tasks,
            bare_file_names,
            short_name_paths,
        )


def resolve_bare_file_tasks(
    project_root: Path,
    file_tasks: dict[str, list[CodexTask]],
    file_paths: dict[str, Path],
    bare_file_tasks: dict[str, list[CodexTask]],
    bare_file_names: dict[str, str],
    short_name_paths: dict[str, ProjectFileReference],
) -> None:
    for key, tasks in bare_file_tasks.items():
        file_name = bare_file_names[key]
        target = short_name_paths.get(key)

        if target is None:
            root_candidate = resolve_existing_or_future_path(project_root / file_name)
            root_relative = relative_to_project(root_candidate, project_root)
            if root_candidate.is_file() and root_relative is not None and not has_dot_directory(root_relative):
                target = ProjectFileReference(root_candidate, root_relative)

        if target is None:
            target = best_project_file_by_name(file_name, project_root)

        if target is None:
            continue

        for task in tasks:
            add_project_file(task, target, file_tasks, file_paths)


def session_date_from_path(jsonl_file: Path, sessions_dir: Path) -> date | None:
    try:
        relative = jsonl_file.relative_to(sessions_dir)
    except ValueError:
        return None

    if len(relative.parts) < 4:
        return None

    year, month, day = relative.parts[:3]
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def session_cwd_matches(jsonl_file: Path, project_root: Path) -> bool:
    try:
        with jsonl_file.open("r", encoding="utf-8-sig") as handle:
            first_line = handle.readline()
    except OSError:
        return False

    if not first_line.strip():
        return False

    try:
        first_record = json.loads(first_line)
    except json.JSONDecodeError:
        return False

    if first_record.get("type") != "session_meta":
        return False

    cwd = first_record.get("payload", {}).get("cwd")
    if not cwd:
        return False

    cwd_path = resolve_existing_or_future_path(Path(cwd))
    return path_key(cwd_path) == path_key(project_root)


def find_session_jsonl_files(project_root: Path, codex_dir: Path, start: date) -> list[Path]:
    sessions_dir = codex_dir / "sessions"
    if not sessions_dir.exists():
        return []

    jsonl_files: list[Path] = []
    for jsonl_file in sessions_dir.rglob("*.jsonl"):
        session_date = session_date_from_path(jsonl_file, sessions_dir)
        if session_date is None or session_date < start:
            continue
        if not session_cwd_matches(jsonl_file, project_root):
            continue
        jsonl_files.append(jsonl_file)

    return sorted(jsonl_files, key=lambda path: (path.stat().st_mtime, os.fspath(path)))


def iter_jsonl_records(jsonl_file: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with jsonl_file.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"warning: skipped invalid JSON in {jsonl_file}:{line_number}: {exc}", file=sys.stderr)
                continue
            if isinstance(record, dict):
                yield line_number, record


def final_answer_text(record: dict[str, Any]) -> str | None:
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("phase") != "final_answer":
        return None

    if (
        record.get("type") == "response_item"
        and payload.get("type") == "message"
        and payload.get("role") == "assistant"
    ):
        content = payload.get("content", [])
        if not isinstance(content, list):
            return None
        chunks = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "output_text" and item.get("text")
        ]
        return "\n".join(chunks) if chunks else None

    if record.get("type") == "event_msg" and payload.get("type") == "agent_message":
        message = payload.get("message")
        return message if isinstance(message, str) else None

    return None


def scan_codex_tasks(
    jsonl_files: list[Path],
    project_root: Path,
) -> tuple[dict[str, list[CodexTask]], dict[str, Path], list[CodexTask]]:
    file_tasks: dict[str, list[CodexTask]] = {}
    file_paths: dict[str, Path] = {}
    bare_file_tasks: dict[str, list[CodexTask]] = {}
    bare_file_names: dict[str, str] = {}
    short_name_paths: dict[str, ProjectFileReference] = {}
    all_tasks: list[CodexTask] = []

    for jsonl_file in jsonl_files:
        current_task: CodexTask | None = None

        for _line_number, record in iter_jsonl_records(jsonl_file):
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue

            payload_type = payload.get("type")
            record_type = record.get("type")

            if record_type == "event_msg" and payload_type == "user_message":
                if current_task is not None:
                    all_tasks.append(current_task)
                timestamp = str(record.get("timestamp", ""))
                current_task = CodexTask(
                    date=format_timestamp(timestamp),
                    user_message=strip_open_tabs_section(str(payload.get("message", ""))),
                )
                continue

            if current_task is None:
                continue

            if record_type == "event_msg" and payload_type == "patch_apply_end":
                if payload.get("success") is False:
                    continue
                changes = payload.get("changes", {})
                if isinstance(changes, dict):
                    for changed_path in changes:
                        add_touched_file(
                            current_task,
                            changed_path,
                            project_root,
                            file_tasks,
                            file_paths,
                            bare_file_tasks,
                            bare_file_names,
                            short_name_paths,
                        )
                for stream_name in ("stdout", "stderr"):
                    stream_text = payload.get(stream_name)
                    if isinstance(stream_text, str):
                        add_touched_files_from_text(
                            current_task,
                            stream_text,
                            project_root,
                            file_tasks,
                            file_paths,
                            bare_file_tasks,
                            bare_file_names,
                            short_name_paths,
                        )

            if record_type == "event_msg" and payload_type == "agent_message":
                message = payload.get("message", "")
                if isinstance(message, str):
                    add_touched_files_from_text(
                        current_task,
                        message,
                        project_root,
                        file_tasks,
                        file_paths,
                        bare_file_tasks,
                        bare_file_names,
                        short_name_paths,
                    )

            reply_text = final_answer_text(record)
            if reply_text is not None:
                add_touched_files_from_text(
                    current_task,
                    reply_text,
                    project_root,
                    file_tasks,
                    file_paths,
                    bare_file_tasks,
                    bare_file_names,
                    short_name_paths,
                )
                current_task.add_final_reply(str(record.get("timestamp", "")), reply_text)

        if current_task is not None:
            all_tasks.append(current_task)

    resolve_bare_file_tasks(
        project_root,
        file_tasks,
        file_paths,
        bare_file_tasks,
        bare_file_names,
        short_name_paths,
    )

    return file_tasks, file_paths, all_tasks


def parse_blame_commit_hashes(blame_output: str) -> list[str]:
    hashes: list[str] = []
    seen: set[str] = set()

    for line in blame_output.splitlines():
        match = re.match(r"^\^?([0-9a-f]{40})\s", line)
        if not match:
            continue

        commit_hash = match.group(1)
        if commit_hash == "0" * 40 or commit_hash in seen:
            continue

        seen.add(commit_hash)
        hashes.append(commit_hash)

    return hashes


def git_commit_details(project_root: Path, commit_hash: str) -> GitCommit | None:
    result = subprocess.run(
        ["git", "show", "-s", "--format=%cI%x00%H%x00%B", commit_hash],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None

    parts = result.stdout.split("\x00", 2)
    if len(parts) != 3:
        return None

    commit_date, full_hash, message = parts
    return GitCommit(
        date=format_timestamp(commit_date.strip()),
        commit_hash=full_hash.strip(),
        message=message.strip(),
    )


def git_commits_for_file(
    project_root: Path,
    relative_file: Path,
    commit_cache: dict[str, GitCommit | None],
) -> list[GitCommit]:
    result = subprocess.run(
        ["git", "blame", "--line-porcelain", "--", relative_file.as_posix()],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return []

    commits: list[GitCommit] = []
    for commit_hash in parse_blame_commit_hashes(result.stdout):
        if commit_hash not in commit_cache:
            commit_cache[commit_hash] = git_commit_details(project_root, commit_hash)
        commit = commit_cache[commit_hash]
        if commit is not None:
            commits.append(commit)

    return commits


def text_to_history_value(text: str) -> str | list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in normalized:
        return normalized
    return normalized.splitlines()


def history_value_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return ""


def codex_task_history_item(task: CodexTask) -> dict[str, Any]:
    return {
        "timestamp": task.date,
        "type": "codex_task",
        "user_prompt": text_to_history_value(strip_open_tabs_section(task.user_message)),
        "agent_reply": text_to_history_value(task.final_reply_message),
        "files": task.files,
    }


def git_commit_history_item(commit: GitCommit) -> dict[str, Any]:
    return {
        "timestamp": commit.date,
        "type": "git_commit",
        "commit_message": text_to_history_value(commit.message),
        "commit_hash": commit.commit_hash,
    }


def history_path_for_file(project_root: Path, history_root: Path, file_path: Path) -> Path | None:
    relative = relative_to_project(file_path, project_root)
    if relative is None or has_dot_directory(relative):
        return None

    parent = history_root / relative.parent
    return parent / f"{relative.name}.codexhist.json"


def read_existing_history(history_file: Path) -> list[Any]:
    if not history_file.exists():
        return []

    with history_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError(f"{history_file} does not contain a JSON array")

    return data


def history_dedupe_key(item: Any) -> tuple[Any, Any] | None:
    if not isinstance(item, dict):
        return None
    return item.get("timestamp"), item.get("type")


def merge_text_field(existing: dict[str, Any], new_item: dict[str, Any], field_name: str) -> None:
    new_value = new_item.get(field_name)
    if not new_value:
        return

    existing_value = existing.get(field_name)
    if not existing_value:
        existing[field_name] = new_value
        return

    existing_text = history_value_to_text(existing_value)
    new_text = history_value_to_text(new_value)
    if field_name == "user_prompt" and strip_open_tabs_section(existing_text) == new_text and existing_text != new_text:
        existing[field_name] = new_value
        return

    if existing_text == new_text and existing_value != new_value:
        existing[field_name] = new_value
        return

    if field_name == "agent_reply" and existing_text in new_text and len(new_text) > len(existing_text):
        existing[field_name] = new_value


def merge_duplicate_history_item(existing: dict[str, Any], new_item: dict[str, Any]) -> None:
    for field_name in ("user_prompt", "agent_reply", "commit_message"):
        merge_text_field(existing, new_item, field_name)

    if not existing.get("commit_hash") and new_item.get("commit_hash"):
        existing["commit_hash"] = new_item["commit_hash"]

    existing_files = existing.get("files")
    new_files = new_item.get("files")
    if isinstance(existing_files, list) and isinstance(new_files, list):
        for file_name in new_files:
            if file_name not in existing_files:
                existing_files.append(file_name)
    elif "files" not in existing and isinstance(new_files, list):
        existing["files"] = list(new_files)


def merged_history_items(existing: list[Any], new_items: list[dict[str, Any]]) -> list[Any]:
    merged = list(existing)
    seen = {key for key in (history_dedupe_key(item) for item in existing) if key is not None}
    existing_by_key = {
        key: item
        for item in existing
        if isinstance(item, dict)
        for key in [history_dedupe_key(item)]
        if key is not None
    }

    for item in new_items:
        key = history_dedupe_key(item)
        if key is None:
            continue
        if key in seen:
            existing_item = existing_by_key.get(key)
            if isinstance(existing_item, dict):
                merge_duplicate_history_item(existing_item, item)
            continue
        seen.add(key)
        existing_by_key[key] = item
        merged.append(item)

    return sorted(
        merged,
        key=lambda item: (
            timestamp_sort_key(item.get("timestamp", "") if isinstance(item, dict) else ""),
            item.get("type", "") if isinstance(item, dict) else "",
        ),
    )


def write_json_array_atomic(history_file: Path, items: list[Any]) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{history_file.name}.",
        suffix=".tmp",
        dir=os.fspath(history_file.parent),
        text=True,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(items, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, history_file)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def write_history_files(
    project_root: Path,
    history_root: Path,
    file_tasks: dict[str, list[CodexTask]],
    file_paths: dict[str, Path],
) -> tuple[int, int, int]:
    written = 0
    unchanged = 0
    skipped = 0
    commit_cache: dict[str, GitCommit | None] = {}

    for file_key, tasks in sorted(file_tasks.items(), key=lambda item: item[0]):
        file_path = file_paths[file_key]
        relative = relative_to_project(file_path, project_root)
        if relative is None:
            skipped += 1
            continue

        history_file = history_path_for_file(project_root, history_root, file_path)
        if history_file is None:
            skipped += 1
            continue

        task_items = [codex_task_history_item(task) for task in tasks]
        commit_items = [
            git_commit_history_item(commit)
            for commit in git_commits_for_file(project_root, relative, commit_cache)
        ]
        new_items = task_items + commit_items

        try:
            existing = read_existing_history(history_file)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"warning: skipped {history_file}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        merged = merged_history_items(existing, new_items)
        if merged == existing:
            unchanged += 1
            continue

        write_json_array_atomic(history_file, merged)
        written += 1

    return written, unchanged, skipped


def build_arg_parser() -> argparse.ArgumentParser:
    default_start = subtract_months(date.today(), 2).isoformat()
    parser = argparse.ArgumentParser(
        description="Build per-file Codex history JSON files from Codex session logs and git blame."
    )
    parser.add_argument("project_root", help="Project root directory Codex was working in.")
    parser.add_argument(
        "--codex-dir",
        default=os.fspath(Path.home() / ".codex"),
        help="Codex data directory. Defaults to %(default)s.",
    )
    parser.add_argument(
        "--start-date",
        default=default_start,
        help="Only scan sessions on or after this date. Defaults to %(default)s.",
    )
    return parser


def print_progress(message: str) -> None:
    print(message, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    project_root = resolve_existing_or_future_path(Path(args.project_root))
    if not project_root.is_dir():
        parser.error(f"project root does not exist or is not a directory: {project_root}")

    codex_dir = resolve_existing_or_future_path(Path(args.codex_dir))
    try:
        start = parse_start_date(args.start_date)
    except ValueError as exc:
        parser.error(f"invalid --start-date: {exc}")

    history_root = project_root / ".codex_history"
    print_progress(f"Using project root: {project_root}")
    print_progress(f"Ensuring history root exists: {history_root}")
    history_root.mkdir(parents=True, exist_ok=True)

    print_progress(f"Finding Codex session logs in {codex_dir / 'sessions'} since {start.isoformat()}...")
    jsonl_files = find_session_jsonl_files(project_root, codex_dir, start)
    print_progress(f"Matched {len(jsonl_files)} Codex session log(s).")

    print_progress("Parsing Codex tasks and resolving touched files...")
    file_tasks, file_paths, all_tasks = scan_codex_tasks(jsonl_files, project_root)
    print(f"Parsed {len(all_tasks)} Codex task(s).")
    print(f"Found {len(file_tasks)} touched project file(s).")

    print_progress("Writing history files and collecting git blame commits...")
    written, unchanged, skipped = write_history_files(project_root, history_root, file_tasks, file_paths)
    print(f"Wrote {written} history file(s), left {unchanged} unchanged, skipped {skipped}.")
    print(f"History root: {history_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
