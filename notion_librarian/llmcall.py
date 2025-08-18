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
