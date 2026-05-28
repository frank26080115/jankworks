#!/usr/bin/env python3
"""
codex_account_switcher.py

Keeps multiple Codex auth.json files in:
  ~/.codex-accounts/

Switches the active account by overwriting:
  ~/.codex/auth.json
"""

import argparse
import base64
import json
import re
import shutil
from pathlib import Path
from typing import Any, Optional


CODEX_DIR = Path.home() / ".codex"
AUTH_PATH = CODEX_DIR / "auth.json"
ACCOUNTS_DIR = Path.home() / ".codex-accounts"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def find_first_key(obj: Any, key: str) -> Optional[Any]:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = find_first_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_first_key(item, key)
            if found is not None:
                return found
    return None


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("._ ") or "unknown_account"


def parse_jwt_payload(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}

        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        parsed = json.loads(decoded.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def find_codex_id_token(auth_data: Any) -> Optional[str]:
    if not isinstance(auth_data, dict):
        return None

    tokens = auth_data.get("tokens") or {}
    if not isinstance(tokens, dict):
        tokens = {}

    id_token = tokens.get("id_token") or auth_data.get("id_token")
    return id_token if isinstance(id_token, str) and id_token else None


def get_username_from_id_token(auth_data: Any) -> Optional[str]:
    id_token = find_codex_id_token(auth_data)
    if not id_token:
        return None

    id_payload = parse_jwt_payload(id_token)
    value = id_payload.get("email")
    return value.strip() if isinstance(value, str) and value.strip() else None


def infer_account_name(auth_data: Any) -> str:
    username = get_username_from_id_token(auth_data)
    if username:
        return username

    for key in ("email", "username", "name", "account_id"):
        value = find_first_key(auth_data, key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return "unknown_account"


def unique_account_path(base_name: str) -> Path:
    safe = sanitize_filename(base_name)
    path = ACCOUNTS_DIR / f"{safe}.json"

    if not path.exists():
        return path

    i = 2
    while True:
        candidate = ACCOUNTS_DIR / f"{safe}_{i}.json"
        if not candidate.exists():
            return candidate
        i += 1


def copy_current_auth_into_accounts() -> Path:
    auth_data = load_json(AUTH_PATH)
    name = infer_account_name(auth_data)
    dest = unique_account_path(name)
    save_json(dest, auth_data)
    return dest


def get_json_files() -> list[Path]:
    return sorted(
        ACCOUNTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def resolve_requested_account(name: str) -> Optional[Path]:
    raw = Path(name)

    candidates = []

    if raw.is_absolute():
        candidates.append(raw)
        if raw.suffix.lower() != ".json":
            candidates.append(raw.with_suffix(".json"))
    else:
        candidates.append(ACCOUNTS_DIR / raw.name)
        if raw.suffix.lower() != ".json":
            candidates.append(ACCOUNTS_DIR / f"{raw.name}.json")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def overwrite_active_auth(selected: Path) -> None:
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(selected, AUTH_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Switch Codex accounts by swapping ~/.codex/auth.json."
    )
    parser.add_argument(
        "account",
        nargs="?",
        help="Account file from ~/.codex-accounts, with or without .json.",
    )
    args = parser.parse_args()

    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)

    account_files = get_json_files()

    if not account_files:
        if not AUTH_PATH.exists():
            print("Error: no ~/.codex-accounts/*.json files and no ~/.codex/auth.json found.")
            return 1

        dest = copy_current_auth_into_accounts()
        print(f"Created account store: {dest}")
        print("Only one account exists, so there is nothing to switch.")
        return 0

    current_account_id = None
    current_match = None

    if AUTH_PATH.exists():
        current_auth = load_json(AUTH_PATH)
        current_account_id = find_first_key(current_auth, "account_id")

        if current_account_id:
            for path in account_files:
                try:
                    data = load_json(path)
                    if find_first_key(data, "account_id") == current_account_id:
                        current_match = path
                        break
                except Exception:
                    pass

        if current_match is None:
            dest = copy_current_auth_into_accounts()
            current_match = dest
            account_files = get_json_files()
            print(f"Saved current unknown account as: {dest.name}")

    if args.account:
        selected = resolve_requested_account(args.account)
        if selected is None:
            print(f"Error: could not find account file: {args.account}")
            return 1

        overwrite_active_auth(selected)
        print(f"Switched Codex auth to: {selected.stem}")
        return 0

    display = account_files[:9]

    print()
    print("Codex accounts:")
    for i, path in enumerate(display, start=1):
        marker = "  <-- current" if current_match and path.resolve() == current_match.resolve() else ""
        print(f"  {i}. {path.stem}{marker}")

    print()
    choice = input("Pick account 1-9, or Enter to cancel: ").strip()

    if not choice:
        print("Cancelled.")
        return 0

    if not choice.isdigit():
        print("Error: choice must be a number.")
        return 1

    index = int(choice)
    if index < 1 or index > len(display):
        print("Error: choice out of range.")
        return 1

    selected = display[index - 1]
    overwrite_active_auth(selected)
    print(f"Switched Codex auth to: {selected.stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
