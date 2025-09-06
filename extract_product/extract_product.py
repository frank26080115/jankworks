# extract_product.py
# pip install playwright openai
# playwright install chromium
#
# Usage:
#   python extract_product.py --url https://example.com/product/123
#   python extract_product.py --url https://www.mcmaster.com/91251A540 --timeout-ms 60000 --model gpt-oss:20b
#
# Expects a local OpenAI-compatible endpoint in your environment (e.g., Ollama/OAI proxy),
# and that the model (default gpt-oss:20b) supports tool-calling.

import argparse
import json
import sys
from typing import Tuple, Optional

from playwright.sync_api import sync_playwright
from openai import OpenAI

from llm import ensure_ollama_up, is_online_model, extract_product_header_with_ollama_native, extract_product_header_with_llm, extract_product_header_with_llm_t

# ---------- Playwright helpers ----------

def wait_page_settled(page, timeout_ms: int):
    """
    Wait for DOMContentLoaded -> networkidle -> brief settle.
    """
    # If the site is very JS-heavy, networkidle catches post-load XHRs.
    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    page.wait_for_timeout(500)  # extra microtask settle

def gentle_lazy_scroll(page, steps: int = 6, pause_ms: int = 250):
    """
    Nudges lazy-loaded sections (images, product panes).
    """
    for _ in range(steps):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(pause_ms)

def capture_rendered(page) -> Tuple[str, str]:
    """
    Returns (rendered_html, visible_text).
    """
    rendered_html = page.content()
    visible_text = page.evaluate("document.body ? document.body.innerText : ''")
    return rendered_html, visible_text

def fetch_url(url: str, timeout_ms: int) -> Tuple[str, str]:
    """
    Launches a headless browser, loads the URL, waits, scrolls, and captures content.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        wait_page_settled(page, timeout_ms)
        gentle_lazy_scroll(page)
        # Final short settle in case lazy content injects text
        page.wait_for_timeout(300)
        html, text = capture_rendered(page)
        browser.close()
        return html, text

# ---------- Strippers ----------

import re

def _strip_noise(html: str) -> str:
    # Remove script/style blocks and compress whitespace
    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
    html = re.sub(r"<!--[\s\S]*?-->", "", html)  # comments
    # Optional: strip tags to plain-ish text while keeping top structure cues
    # Keeping tags is fine; the model can still use them.
    return re.sub(r"\s+", " ", html).strip()

def _head_tail(s: str, max_chars: int) -> str:
    """Keep 75% head, 25% tail to preserve above-the-fold content."""
    if len(s) <= max_chars:
        return s
    head = s[: int(max_chars * 0.75)]
    tail = s[- int(max_chars * 0.25):]
    return head + "\n[...TRUNCATED...]\n" + tail

def _shorten_inputs(html: str, text: str, max_html: int = 80_000, max_text: int = 40_000) -> Tuple[str, str]:
    return _head_tail(_strip_noise(html), max_html), _head_tail(text, max_text)

# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Extract product name/description from any product URL using Playwright + local LLM.")
    parser.add_argument("--url", required=True, help="Product page URL")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="Page load timeout in milliseconds (default 60000)")
    parser.add_argument("--model", default="gpt-oss:20b", help="OpenAI-compatible model name (default gpt-oss:20b)")
    args = parser.parse_args()

    if not is_online_model(args.model):
        ensure_ollama_up()

    try:
        html, text = fetch_url(args.url, args.timeout_ms)
        html, text = _shorten_inputs(html, text, 80000, 40000)
    except Exception as e:
        print(f"ERROR: Failed to load URL: {e}", file=sys.stderr)
        sys.exit(2)

    print("page obtained")

    if not is_online_model(args.model):
        client = OpenAI(
            base_url="http://127.0.0.1:11434/v1",  # Ollama's OpenAI-compatible endpoint
            api_key="ollama"  # any non-empty string
        )
    else:
        from openai_credloader import OpenAICredentialsLoader
        cl = OpenAICredentialsLoader()
        client = OpenAI(api_key=cl.get_api_key())

    try:
        if is_online_model(args.model):
            if "-4o" in args.model:
                name, desc = extract_product_header_with_llm_t(client, html, model=args.model)
            else:
                name, desc = extract_product_header_with_llm(client, html, model=args.model)
        else:
            if "gpt-oss" in args.model or "gemma" in args.model:
                name, desc = extract_product_header_with_llm(client, html, model=args.model)
            else:
                name, desc = extract_product_header_with_ollama_native(str(client.base_url).rstrip("/"), html, model=args.model)
    except Exception as e:
        print(f"ERROR: LLM extraction failed: {e}", file=sys.stderr)
        sys.exit(3)

    # Print plainly to stdout (easy to pipe/parse)
    print(name)
    print(desc)

if __name__ == "__main__":
    main()
