"""
Report Codex usage pace from the local Codex login.

This intentionally never fails the caller. It is meant to be safe as a
PlatformIO post-build hook: missing auth, expired tokens, network failures, or
API shape changes are reported as a skipped check and return success.
"""

import argparse
import base64
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
MAX_TIMEOUT_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 5


@dataclass
class AuthData:
    path: Path
    access_token: str
    account_id: Optional[str]
    email: Optional[str]
    plan_type: Optional[str]
    model: Optional[str]


@dataclass
class RateLimitWindow:
    name: str
    used_percent: float
    window_minutes: Optional[int]
    resets_in_seconds: Optional[int]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check current Codex usage pace.")
    parser.add_argument(
        "--auth-path",
        type=Path,
        default=None,
        help="Path to Codex auth.json. Defaults to C:/Users/<user>/.codex/auth.json, CODEX_HOME, then ~/.codex/auth.json.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Network timeout in seconds, capped at 5.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print auth path, HTTP status, and returned Codex rate-limit header details.",
    )
    args = parser.parse_args(argv)

    try:
        auth = load_auth(args.auth_path, args.verbose)
        windows = fetch_rate_limits(auth, clamp_timeout(args.timeout), args.verbose)
        print_report(auth, windows)
    except Exception as exc:
        print("Codex usage check skipped: %s" % exc)

    return 0


def load_auth(explicit_path: Optional[Path], verbose: bool) -> AuthData:
    candidates = auth_path_candidates(explicit_path)
    verbose_print(verbose, "Checking Codex auth paths:")
    for candidate in candidates:
        verbose_print(verbose, "  %s" % candidate)

    for auth_path in candidates:
        if not auth_path.is_file():
            continue

        verbose_print(verbose, "Using Codex auth file: %s" % auth_path)
        with auth_path.open("r", encoding="utf-8") as handle:
            auth_json = json.load(handle)

        tokens = auth_json.get("tokens") or {}
        access_token = tokens.get("access_token") or auth_json.get("access_token")
        if not access_token:
            raise RuntimeError("Codex access token was not found in %s" % auth_path)

        id_token = tokens.get("id_token") or auth_json.get("id_token")
        id_payload = parse_jwt_payload(id_token) if id_token else {}
        plan_payload = id_payload.get("https://api.openai.com/auth") or {}

        return AuthData(
            path=auth_path,
            access_token=access_token,
            account_id=tokens.get("account_id") or auth_json.get("account_id"),
            email=id_payload.get("email"),
            plan_type=plan_payload.get("chatgpt_plan_type"),
            model=load_codex_model(auth_path.parent),
        )

    raise RuntimeError("Codex auth file not found; run `codex login` first")


def auth_path_candidates(explicit_path: Optional[Path]) -> List[Path]:
    if explicit_path:
        return [explicit_path.expanduser()]

    candidates: List[Path] = []

    env_auth_path = os.environ.get("CODEX_AUTH_JSON")
    if env_auth_path:
        candidates.append(Path(env_auth_path))

    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / "auth.json")

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / ".codex" / "auth.json")

    candidates.append(Path.home() / ".codex" / "auth.json")

    unique_candidates: List[Path] = []
    seen: Set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.expanduser().resolve(strict=False)).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_candidates.append(candidate.expanduser())

    return unique_candidates


def parse_jwt_payload(token: str) -> Dict[str, Any]:
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


def clamp_timeout(timeout_seconds: int) -> int:
    return min(MAX_TIMEOUT_SECONDS, max(1, timeout_seconds))


def fetch_rate_limits(auth: AuthData, timeout_seconds: int, verbose: bool) -> List[RateLimitWindow]:
    session_id = secrets.token_hex(16)
    verbose_print(verbose, "Requesting Codex rate-limit headers from %s" % CODEX_RESPONSES_URL)
    verbose_print(verbose, "Request timeout: %ss" % timeout_seconds)
    if auth.account_id:
        verbose_print(verbose, "Using chatgpt-account-id from auth file")

    payload = minimal_codex_payload(session_id, auth.model)
    verbose_print(verbose, "Request model: %s" % payload["model"])
    verbose_print(verbose, "Request payload keys: %s" % ", ".join(sorted(payload.keys())))

    request = urllib.request.Request(
        CODEX_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers(auth, session_id),
        method="POST",
    )

    response_body = b""
    status_code = None
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            headers = response.headers
            response_body = response.read(2048)
            status_code = response.status
            verbose_print(verbose, "HTTP status: %s" % response.status)
    except urllib.error.HTTPError as exc:
        headers = exc.headers
        response_body = exc.read(2048)
        status_code = exc.code
        verbose_print(verbose, "HTTP status: %s" % exc.code)
        verbose_print(verbose, "HTTP reason: %s" % exc.reason)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError("network request failed: %s" % reason) from exc

    verbose_print_rate_headers(verbose, headers)
    verbose_print_response_body(verbose, status_code, response_body)
    windows = extract_rate_limit_windows(headers)
    if not windows:
        raise RuntimeError("no Codex rate-limit headers were returned")

    return windows


def request_headers(auth: AuthData, session_id: str) -> Dict[str, str]:
    headers = {
        "Accept": "text/event-stream",
        "Authorization": "Bearer %s" % auth.access_token,
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "User-Agent": "the-fly-check-dev-pace/1.0",
        "originator": "codex_vscode_extension",
        "session_id": session_id,
    }

    if auth.account_id:
        headers["chatgpt-account-id"] = auth.account_id

    return headers


def minimal_codex_payload(session_id: str, configured_model: Optional[str]) -> Dict[str, Any]:
    return {
        "model": configured_model or "gpt-5-codex",
        "instructions": "You are Codex CLI. Reply with ok.",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            }
        ],
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "reasoning": {"effort": "low", "summary": "auto"},
        "store": False,
        "stream": True,
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": session_id,
        "client_metadata": {"x-codex-installation-id": "the-fly-check-dev-pace"},
    }


def load_codex_model(codex_dir: Path) -> Optional[str]:
    config_path = codex_dir / "config.toml"
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("model"):
                    key, separator, value = stripped.partition("=")
                    if separator and key.strip() == "model":
                        return parse_toml_string(value.strip())
    except OSError:
        return None

    return None


def parse_toml_string(value: str) -> Optional[str]:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return None


def extract_rate_limit_windows(headers: Any) -> List[RateLimitWindow]:
    windows: List[RateLimitWindow] = []

    primary = extract_window(headers, "primary", "5-hour")
    if primary:
        windows.append(primary)

    secondary = extract_window(headers, "secondary", "7-day")
    if secondary:
        windows.append(secondary)

    return windows


def extract_window(headers: Any, key: str, display_name: str) -> Optional[RateLimitWindow]:
    used_percent = header_float(headers, "x-codex-%s-used-percent" % key)
    if used_percent is None:
        return None

    return RateLimitWindow(
        name=display_name,
        used_percent=used_percent,
        window_minutes=header_int(headers, "x-codex-%s-window-minutes" % key),
        resets_in_seconds=header_int(headers, "x-codex-%s-reset-after-seconds" % key),
    )


def header_value(headers: Any, name: str) -> Optional[str]:
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is None:
            value = headers.get(name.lower())
        if value is not None:
            return str(value)

    return None


def header_float(headers: Any, name: str) -> Optional[float]:
    value = header_value(headers, name)
    if value is None:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def header_int(headers: Any, name: str) -> Optional[int]:
    value = header_value(headers, name)
    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def verbose_print(verbose: bool, message: str) -> None:
    if verbose:
        print(message)


def verbose_print_rate_headers(verbose: bool, headers: Any) -> None:
    if not verbose:
        return

    codex_headers = []
    if hasattr(headers, "items"):
        for name, value in headers.items():
            if str(name).lower().startswith("x-codex-"):
                codex_headers.append((str(name), str(value)))

    if codex_headers:
        print("Codex headers:")
        for name, value in sorted(codex_headers):
            print("  %s: %s" % (name, value))
    else:
        print("Codex headers: none returned")

    if hasattr(headers, "items"):
        interesting_headers = []
        for name, value in headers.items():
            lower_name = str(name).lower()
            if lower_name in ("content-type", "openai-organization", "www-authenticate"):
                interesting_headers.append((str(name), str(value)))

        if interesting_headers:
            print("Other response headers:")
            for name, value in sorted(interesting_headers):
                print("  %s: %s" % (name, value))


def verbose_print_response_body(verbose: bool, status_code: Optional[int], response_body: bytes) -> None:
    if not verbose or not response_body or status_code is None or status_code < 400:
        return

    text = response_body.decode("utf-8", errors="replace").strip()
    if not text:
        return

    print("Response body:")
    try:
        parsed = json.loads(text)
        compact = json.dumps(parsed, ensure_ascii=True)
        print("  %s" % compact[:1000])
    except ValueError:
        print("  %s" % text[:1000])


def print_report(auth: AuthData, windows: List[RateLimitWindow]) -> None:
    print("Codex usage pace:")
    if auth.email or auth.plan_type:
        print("Codex usage Account: %s%s" % (auth.email or "unknown", plan_suffix(auth.plan_type)))

    for window in windows:
        remaining = max(0.0, 100.0 - window.used_percent)
        print(
            "Codex usage pace: %s: %s used, %s remaining%s%s"
            % (
                window_label(window),
                format_percent(window.used_percent),
                format_percent(remaining),
                status_suffix(window.used_percent),
                reset_suffix(window.resets_in_seconds),
            )
        )


def plan_suffix(plan_type: Optional[str]) -> str:
    return " (%s)" % plan_type if plan_type else ""


def window_label(window: RateLimitWindow) -> str:
    if window.window_minutes:
        return "%s window" % format_minutes(window.window_minutes)
    return "%s window" % window.name


def status_suffix(used_percent: float) -> str:
    if used_percent >= 95.0:
        return " [critical]"
    if used_percent >= 80.0:
        return " [warning]"
    return " [ok]"


def reset_suffix(resets_in_seconds: Optional[int]) -> str:
    if resets_in_seconds is None:
        return ""

    return "; resets in %s" % format_seconds(resets_in_seconds)


def format_percent(value: float) -> str:
    return "%.1f%%" % value


def format_minutes(minutes: int) -> str:
    if minutes % (60 * 24) == 0:
        return "%dd" % (minutes // (60 * 24))
    if minutes % 60 == 0:
        return "%dh" % (minutes // 60)
    return "%dm" % minutes


def format_seconds(seconds: int) -> str:
    seconds = max(0, seconds)
    days, remainder = divmod(seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)

    if days:
        return "%dd %dh" % (days, hours)
    if hours:
        return "%dh %dm" % (hours, minutes)
    if minutes:
        return "%dm %ds" % (minutes, seconds)
    return "%ds" % seconds


def platformio_after_build(target: Any, source: Any, env: Any) -> int:
    return main([])


if __name__ == "__main__":
    sys.exit(main())
else:
    try:
        Import("env")  # type: ignore[name-defined]
    except NameError:
        pass
    else:
        env.AddPostAction("$PROGPATH", platformio_after_build)  # type: ignore[name-defined]
