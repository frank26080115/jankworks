from openai import OpenAI
from rapidfuzz import fuzz
import itertools, re, json

# --- 1) Ask LLM for keywords (tool call)
TOOLS_KEYWORDS = [{
    "type": "function",
    "function": {
        "name": "return_keywords",
        "description": "Extract compact search terms to find relevant text for the user's question.",
        "parameters": {
            "type": "object",
            "properties": {
                "must":     {"type":"array","items":{"type":"string"}},
                "should":   {"type":"array","items":{"type":"string"}},
                "phrases":  {"type":"array","items":{"type":"string"}},
                "synonyms": {"type":"object","additionalProperties":{"type":"array","items":{"type":"string"}}},
                #"exclude":  {"type":"array","items":{"type":"string"}}
            },
            "required": ["must","should"]
        }
    }
}]

def llm_extract_keywords(client: object, question: str, model: str) -> dict:
    system = (
        "Extract search controls for filtering text:\n"
        "- Return JSON via function call `return_keywords`.\n"
        "- `must`: very specific anchor terms (few).\n"
        "- `should`: helpful terms.\n"
        "- `phrases`: multi-word quotes to match exactly.\n"
        "- `synonyms`: map from base term to near-synonyms and common misspellings.\n"
        #"- `exclude`: terms that indicate off-topic.\n"
        "Prefer concise, domain-relevant terms; avoid stopwords."
    )
    res = client.chat.completions.create(
        model=model,
        messages=[{"role":"system","content":system},
                  {"role":"user","content":question}],
        tools=TOOLS_KEYWORDS,
        tool_choice="auto",
        #temperature=0,
        #max_tokens=256,
        #extra_body={"keep_alive":"10m"}
    )
    call = res.choices[0].message.tool_calls[0]
    return json.loads(call.function.arguments)

# --- 2) Expand terms (morphology + hyphen/space variants)
def variants(term: str):
    t = term.strip().lower()
    out = {t}
    # hyphen/space variants
    out.add(t.replace("-", " "))
    out.add(t.replace(" ", "-"))
    # simple morphological forms
    if len(t) > 3:
        for suf in ["s","es","ed","ing"]:
            out.add(t+suf)
    return out

def expand_keyword_bundle(kw: dict) -> dict:
    must = set(itertools.chain.from_iterable(variants(x) for x in kw.get("must", [])))
    should = set(itertools.chain.from_iterable(variants(x) for x in kw.get("should", [])))
    phrases = set(kw.get("phrases", []))
    #exclude = set(itertools.chain.from_iterable(variants(x) for x in kw.get("exclude", [])))

    def to_list(x):
        """Normalize LLM output into a flat list of strings."""
        if x is None:
            return []
        if isinstance(x, str):
            # handle comma-separated or single token
            parts = [p.strip() for p in x.split(",")] if "," in x else [x.strip()]
            return [p for p in parts if p]
        if isinstance(x, (list, tuple, set)):
            out = []
            for e in x:
                out.extend(to_list(e))  # flatten nested stuff safely
            return out
        # fallback: coerce anything else to string
        return [str(x).strip()]

    # flatten synonyms → set
    synset = set()
    for base, syns in kw.get("synonyms", {}).items():
        for s in to_list(syns) + [base]:
            synset |= variants(s)  # your existing variants(...) function
    return {
        "must": must,
        "should": should | synset,  # treat synonyms as should-terms
        "phrases": phrases,
        #"exclude": exclude
    }

# --- 3) Fast fuzzy scoring for a block of text
def score_block(text: str, keys: dict,
                typo_thresh=88, soft_thresh=80) -> float:
    """
    Returns a score; higher = more relevant.
    - `typo_thresh` for 'must' terms (stricter).
    - `soft_thresh` for 'should' terms.
    """
    if not text:
        return 0.0
    low = text.lower()

    # hard exclude
    #for ex in keys["exclude"]:
    #    if fuzz.partial_ratio(ex, low) >= soft_thresh:
    #        return 0.0

    score = 0.0

    # phrases (exact-ish)
    for p in keys["phrases"]:
        if p.lower() in low:
            score += 40

    # must-terms: each matched adds strong points; if any must completely miss, we can downrank
    must_hits = 0
    for m in keys["must"]:
        if fuzz.partial_ratio(m, low) >= typo_thresh:
            score += 30
            must_hits += 1
    if keys["must"] and must_hits == 0:
        return 0.0  # enforce at least one anchor hit

    # should-terms (synonyms live here)
    for s in keys["should"]:
        r = fuzz.partial_ratio(s, low)
        if r >= soft_thresh:
            score += (r - soft_thresh) * 0.5  # gentle slope

    # small boost for length-normalized density (avoid huge rambles)
    words = max(1, len(low.split()))
    score += min(20.0, 2000.0 / words)

    return score

# --- 4) Filter & rank blocks (blocks: iterable of (block_id, text))
'''
def select_candidate_blocks(question: str, blocks, top_k=10):
    kw = llm_extract_keywords(question)
    keys = expand_keyword_bundle(kw)
    scored = []
    for bid, txt in blocks:
        s = score_block(txt, keys)
        if s > 0:
            scored.append((s, bid, txt))
    scored.sort(reverse=True, key=lambda x: x[0])
    return scored[:top_k], keys
'''