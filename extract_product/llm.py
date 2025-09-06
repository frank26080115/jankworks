import requests, time, subprocess, platform, os, sys, json
from openai import OpenAI
from typing import Tuple, Optional, Any, Dict

def is_online_model(model:str) -> bool:
    if "-oss" in model:
        return False
    if model.startswith("gpt-"):
        return True
    if "gemma" in model:
        return False
    if "gwen" in model:
        return False
    return False

def ensure_ollama_up(host="http://127.0.0.1:11434", wait_sec=8):
    # 1) Probe
    try:
        r = requests.get(f"{host}/api/version", timeout=1)
        if r.ok:
            return True
    except Exception:
        pass

    # 2) Try to start (requires Ollama installed and on PATH)
    try:
        if platform.system() == "Windows":
            creationflags = 0
            if hasattr(subprocess, "DETACHED_PROCESS"):
                creationflags |= subprocess.DETACHED_PROCESS
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(["ollama", "serve"], creationflags=creationflags,
                             stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        else:
            subprocess.Popen(["ollama", "serve"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        raise RuntimeError("Ollama not found on PATH. Install it and try again.")

    # 3) Wait for it to come up
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        try:
            r = requests.get(f"{host}/api/version", timeout=1)
            if r.ok:
                return True
        except Exception:
            time.sleep(0.25)

    raise RuntimeError("Ollama did not start in time.")

# Tool schema: the model should call this function with the name/description it found.
_PRODUCT_HEADER_TOOL_1 = {
    "type": "function",
    "function": {
        "name": "return_product_header",
        "description": "Return the product name and a one-line product description derived strictly from the provided page content.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Concise product/family name as a user would see as the title/header. No prices, no CTAs."
                },
                "description": {
                    "type": "string",
                    "description": "One-line descriptor immediately under/near the name (material/spec/size/etc.)."
                }
            },
            "required": ["name", "description"],
            "additionalProperties": False
        }
    }
}

_JSON_SCHEMA_1 = {
    "name": "product_header",
    "schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"}
        },
        "required": ["name", "description"],
        "additionalProperties": False
    },
    "strict": True
}

_SYSTEM_PROMPT_1 = (
    "You are a product page extractor. Read the provided HTML and identify a product's two-line header.\n"
    "Return results only by CALLING the provided tool `return_product_header` with:\n"
    "- name: short product/family title as shown to users (no price/stock/CTA/availability).\n"
    "- description: the single concise descriptor line directly under or adjacent to the name (material/spec/size).\n"
    "If multiple candidates exist, pick the best one closest to the top. Use ONLY supplied content; do not invent."
)

_USER_PROMPT_TEMPLATE_1 = (
    "SOURCE CONTENT START\n"
    "---- HTML ----\n{html}\n"
    "SOURCE CONTENT END\n\n"
    "Task: Call the tool with the product name and one-line description strictly from the content above."
)

def _truncate(s: str, max_chars: int = 100_000) -> str:
    if len(s) <= max_chars:
        return s
    head = s[: int(max_chars * 0.75)]
    tail = s[- int(max_chars * 0.25):]
    return head + "\n[...TRUNCATED...]\n" + tail

def _extract_tool_args_from_responses(resp) -> Optional[dict]:
    """
    Robustly dig out the tool/function call arguments from Responses API-like objects.
    Falls back to scanning message content if needed.
    """
    # Preferred path: resp.output contains structured items
    if hasattr(resp, "output") and resp.output:
        for item in resp.output:
            # Newer SDKs: tool calls may appear as 'tool_call' items
            if getattr(item, "type", None) in ("tool_call", "function_call"):
                fc = getattr(item, "function", None) or getattr(item, "tool", None)
                if fc and hasattr(fc, "arguments"):
                    return fc.arguments  # already a dict in some runtimes
            # Messages with content blocks (tool_use)
            if getattr(item, "type", None) == "message":
                content = getattr(item, "content", []) or []
                for block in content:
                    if isinstance(block, dict) and block.get("type") in ("tool_use", "function_call", "tool_call"):
                        args = block.get("input") or block.get("arguments")
                        if isinstance(args, dict):
                            return args
                        # Sometimes arguments are a JSON string
                        if isinstance(args, str):
                            try:
                                return json.loads(args)
                            except Exception:
                                pass

    # Fallback: try a combined text field (rare)
    raw = getattr(resp, "output_text", None) or getattr(resp, "message", None)
    if isinstance(raw, str):
        try:
            # If the model replied with raw JSON (without tool call), accept it
            obj = json.loads(raw)
            if isinstance(obj, dict) and "name" in obj and "description" in obj:
                return obj
        except Exception:
            pass

    return None

def _extract_tool_args_from_chat_response(resp: Any,
                                          required_keys: Optional[set] = None
                                          ) -> Optional[Dict[str, Any]]:
    """
    Extract function/tool call args from an OpenAI Chat Completions response.
    Supports:
      - choices[*].message.tool_calls[*].function.arguments  (modern)
      - choices[*].message.function_call.arguments           (legacy)
      - choices[*].message.content  (fallback JSON in content)

    Returns:
      dict of arguments if found/parsed, else None.

    Args:
      resp: return value of client.chat.completions.create(...)
      required_keys: if provided, ensure the parsed dict contains ALL these keys.
    """
    def _get(obj, name, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _parse_json_maybe(s: str) -> Optional[Dict[str, Any]]:
        if not isinstance(s, str):
            return None
        s = s.strip()
        # direct attempt
        try:
            return json.loads(s)
        except Exception:
            pass
        # brace-slice salvage
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(s[start:end+1])
            except Exception:
                return None
        return None

    def _ok(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if d is None:
            return None
        if required_keys is None:
            return d
        return d if required_keys.issubset(d.keys()) else None

    choices = _get(resp, "choices") or []
    # Prefer: first choice with tool_calls; else function_call; else content JSON
    # 1) tool_calls path
    for ch in choices:
        msg = _get(ch, "message") or {}
        tool_calls = _get(msg, "tool_calls") or []
        if tool_calls:
            # Prefer a known tool name if present (e.g., "return_product_header")
            # else just take the first with parseable JSON.
            # Try to sort so named functions are checked first.
            def _tc_name(tc):
                fn = _get(tc, "function") or {}
                return _get(fn, "name") or ""
            tool_calls_sorted = sorted(tool_calls, key=lambda tc: _tc_name(tc) != "return_product_header")
            for tc in tool_calls_sorted:
                fn = _get(tc, "function") or {}
                args_raw = _get(fn, "arguments")
                if isinstance(args_raw, dict):
                    if _ok(args_raw):
                        return args_raw
                parsed = _parse_json_maybe(args_raw) if isinstance(args_raw, str) else None
                if _ok(parsed):
                    return parsed

    # 2) legacy function_call path
    for ch in choices:
        msg = _get(ch, "message") or {}
        fcall = _get(msg, "function_call")
        if fcall:
            args_raw = _get(fcall, "arguments")
            if isinstance(args_raw, dict):
                if _ok(args_raw):
                    return args_raw
            parsed = _parse_json_maybe(args_raw) if isinstance(args_raw, str) else None
            if _ok(parsed):
                return parsed

    # 3) fallback: JSON in content
    for ch in choices:
        msg = _get(ch, "message") or {}
        content = _get(msg, "content")
        parsed = _parse_json_maybe(content) if isinstance(content, str) else None
        if _ok(parsed):
            return parsed

    return None

def extract_product_header_with_llm_t(
    client: OpenAI,
    html: str,
    model: str = "gpt-oss:20b",
    temperature: float = 0.0
) -> Tuple[str, str]:
    """
    Calls a local LLM (OpenAI-compatible) with a tool schema.
    Returns (name, description).
    """
    html_t = _truncate(html, 80_000)

    prompt = _USER_PROMPT_TEMPLATE_1.format(html=html_t)

    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_schema", "json_schema": _JSON_SCHEMA_1},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT_1},
            {"role": "user", "content": prompt},
        ],
    )

    args = _extract_tool_args_from_chat_response(resp)
    if not args:
        # Last-ditch: make a best-effort empty result instead of crashing
        return "", ""

    name = (args.get("name") or "").strip()
    desc = (args.get("description") or "").strip()
    return name, desc

def extract_product_header_with_llm(
    client: OpenAI,
    html: str,
    model: str = "gpt-oss:20b",
    temperature: float = 0.0
) -> Tuple[str, str]:
    """
    Calls a local LLM (OpenAI-compatible) with a tool schema.
    Returns (name, description).
    """
    html_t = _truncate(html, 80_000)

    prompt = _USER_PROMPT_TEMPLATE_1.format(html=html_t)

    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_schema", "json_schema": _JSON_SCHEMA_1},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT_1},
            {"role": "user", "content": prompt},
        ],
    )

    args = _extract_tool_args_from_chat_response(resp)
    if not args:
        # Last-ditch: make a best-effort empty result instead of crashing
        return "", ""

    name = (args.get("name") or "").strip()
    desc = (args.get("description") or "").strip()
    return name, desc

def extract_product_header_with_ollama_native(
    base_url: str,
    html: str,
    model: str,
    temperature: float = 0.0,
) -> Tuple[str, str]:
    SYSTEM_2 = (
        "You extract a product's two-line header from provided HTML. "
        "Return a JSON object with keys: name (string), description (string). "
        "No extra keys. Do not invent text beyond the provided content."
    )
    USER_2 = (
        "SOURCE CONTENT START\n"
        "---- HTML ----\n{html}\n"
        "SOURCE CONTENT END\n\n"
        "Task: Return concise product name (title) and a single-line description nearby."
    ).format(html=html[:80_000])

    # Ollama native chat endpoint:
    url = base_url.rstrip("/").replace("/v1", "") + "/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_2},
            {"role": "user", "content": USER_2},
        ],
        "options": {"temperature": temperature},
        # Enforce JSON shape:
        "format": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"}
            },
            "required": ["name", "description"],
            "additionalProperties": False
        },
        "stream": False
    }
    r = requests.post(url, json=payload, timeout=600)
    r.raise_for_status()
    data = r.json()
    content = data.get("message", {}).get("content", "")
    try:
        obj = json.loads(content)
        return (obj.get("name", "").strip(), obj.get("description", "").strip())
    except Exception:
        # Some models put text before/after JSON—try brace slice:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            try:
                obj = json.loads(content[start:end+1])
                return (obj.get("name", "").strip(), obj.get("description", "").strip())
            except Exception:
                pass
        return "", ""

SYSTEM_3 = (
    "You extract a product's two-line header from provided HTML. "
    "Return ONLY JSON with keys: name (string), description (string). "
    "No commentary, no code fences. Do not invent text beyond the provided content."
)

USER_TMPL_3 = (
    "SOURCE CONTENT START\n"
    "---- HTML ----\n{html}\n"
    "SOURCE CONTENT END\n\n"
    "Task: Produce a concise product name (title) and a single-line description nearby. "
    "Return ONLY this JSON:\n"
    '{"name": "...", "description": "..."}'
)

def extract_product_header_with_llm_chat(
    client: OpenAI,
    html: str,
    model: str = "gpt-oss:20b",
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> Tuple[str, str]:
    html_t = html[:80_000]

    messages = [
        {"role": "system", "content": SYSTEM_3},
        {"role": "user", "content": USER_TMPL_3.format(html=html_t)},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        # Some OpenAI-compatible servers ignore this; harmless if unsupported:
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content.strip()
    # Hardening: try to locate JSON even if the model adds fluff
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        return "", ""
    try:
        obj = json.loads(content[start:end+1])
        return (obj.get("name", "").strip(), obj.get("description", "").strip())
    except Exception:
        return "", ""
