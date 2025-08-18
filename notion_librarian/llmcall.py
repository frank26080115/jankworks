import os, json
from openai import OpenAI

SCHEMA = {
    "name": "QAResult",
    "schema": {
        "type": "object",
        "properties": {
            "related": {"type": "string", "enum": ["YES", "NO"]},
            "answer":  {"type": "string"},      # may be "" when NO
            "evidence":{"type": "array", "items": {"type": "string"}, "maxItems": 5}
        },
        "required": ["related", "answer", "evidence"],
        "additionalProperties": False
    },
    "strict": True
}

def judge_and_answer_structured(client: object, md_text: str, question: str, model="gpt-4o-mini"):
    system = (
        "You are a retrieval QA checker.\n"
        "Use ONLY the provided document. If insufficient info, set related='NO' and answer=''. "
        "If sufficient, set related='YES' and answer concisely. Provide brief evidence quotes."
    )
    user_doc = f"Document (Markdown):\n```markdown\n{md_text}\n```"
    user_q   = f"Question:\n{question}"

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_doc},
            {"role": "user", "content": user_q},
        ],
        #temperature=0, # only supported by 4o
        response_format={"type": "json_schema", "json_schema": SCHEMA},
        #max_tokens=400, # only supported by 4o
    )
    return json.loads(resp.choices[0].message.content)

TOOLS = [{
    "type": "function",
    "function": {
        "name": "return_qa",
        "description": "Return if the question is answerable from the document and the answer if so.",
        "parameters": {
            "type": "object",
            "properties": {
                "related": {"type": "string", "enum": ["YES","NO"]},
                "answer":  {"type": "string"},
                "evidence":{"type": "array", "items": {"type":"string"}, "maxItems": 5}
            },
            "required": ["related","answer","evidence"],
            "additionalProperties": False
        }
    }
}]

def judge_and_answer_tools(client: object, md_text: str, question: str, model="gpt-4o-mini"):
    system = (
        "You are a retrieval QA checker. Use ONLY the provided document. "
        "If insufficient info, related='NO' and answer=''. If sufficient, related='YES'."
    )
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Document:\n```markdown\n{md_text}\n```"},
        {"role": "user", "content": f"Question:\n{question}"},
    ]
    res = client.chat.completions.create(
        model=model,
        messages=msgs,
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "return_qa"}},
        #temperature=0, # only supported by 4o
        #max_tokens=400, # only supported by 4o
    )
    call = res.choices[0].message.tool_calls[0]
    return json.loads(call.function.arguments)

def judge_and_answer_oss(question: str, document_text: str) -> dict:
    """
    Returns a dict like: {"related": "YES"|"NO", "answer": "...", "evidence": ["...", ...]}
    """

    client = OpenAI(
        base_url="http://127.0.0.1:11434/v1",  # Ollama's OpenAI-compatible endpoint
        api_key="ollama"  # any non-empty string
    )

    system = (
        "You are a QA judge. Read the document and the question.\n"
        "- If the question is answerable using ONLY the document, call function `return_qa` with:\n"
        "  related='YES', answer=<the answer>, evidence=<up to 5 short quotes/snippets from the doc>.\n"
        "- If NOT answerable, call `return_qa` with related='NO', answer=''.\n"
        "- Keep evidence concise; prefer exact snippets from the doc.\n"
        "- Always respond by CALLING the function (do not reply with plain text)."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Question:\n{question}\n\nDocument:\n{document_text}"}
    ]

    res = client.chat.completions.create(
        model="gpt-oss:20b",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",     # or: {"type":"function","function":{"name":"return_qa"}} to force
        temperature=0           # determinism for judging
    )

    choice = res.choices[0]
    tool_calls = choice.message.tool_calls
    if not tool_calls:
        # Fallback: model didn't follow instructions; surface content for debugging
        content = (choice.message.content or "").strip()
        raise RuntimeError(f"Model did not call tool. Got text: {content!r}")

    call = tool_calls[0]
    if call.function.name != "return_qa":
        raise RuntimeError(f"Unexpected tool called: {call.function.name}")

    # ✅ Your parse step:
    args = json.loads(call.function.arguments)
    # Optional safety: normalize fields
    args["related"] = args.get("related", "").upper()
    args["answer"] = args.get("answer", "")
    args["evidence"] = list(args.get("evidence", []))[:5]
    return args

import requests, time, subprocess, platform, os, sys

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
