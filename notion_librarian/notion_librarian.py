#!/usr/bin/env python3
import argparse
import queue
import threading, signal
import time
import json
import os, sys
from datetime import datetime
from pathlib import Path

import myutils
import progresstracker
from notion_authtoken_reader import AuthTokenFileReader
from openai_credloader import OpenAICredentialsLoader
from chunker import notion_page_to_h1_chunks
from notiondata import NotionTextChunk
from textsplitter import windowed_markdown_chunks
from llmcall import judge_and_answer_structured, judge_and_answer_oss, ensure_ollama_up
from notion_breadcrumb import get_breadcrumb_with_block_text
from evidencelink import find_block_by_evidence
from progresstracker import ProgressTracker

STOP = threading.Event()

def _stop_now(signum, frame):
    # Minimal work in a signal handler: set an Event that loops can see.
    STOP.set()

signal.signal(signal.SIGINT, _stop_now)    # Ctrl+C
if hasattr(signal, "SIGBREAK"):            # Windows: Ctrl+Break (sometimes easier to hit)
    signal.signal(signal.SIGBREAK, _stop_now)

notion_token = AuthTokenFileReader().get_token()

progtracker = ProgressTracker()

class LibrarianAnswer(object):
    def __init__(self, json, chunk):
        self.json = json
        self.chunk = chunk

def notion_page_process(notion_token, page_id, out_q, max_batch_tokens = 6000):
    page_id = myutils.unshorten_id(myutils.shorten_id(myutils.extract_uuids(page_id)[0]))
    chunks, children = notion_page_to_h1_chunks(notion_token, page_id)
    for key, md in chunks.items():
        subchunks = windowed_markdown_chunks(md, max_batch_tokens)
        for c in subchunks:
            nc = NotionTextChunk(page_id, key, c)
            out_q.put(nc)
            progtracker.on_add()
    for cp in children:
        notion_page_process(notion_token, cp, out_q)

def notion_producer_worker(
    page_url: str,
    out_q: "queue.Queue[NotionTextChunk | object]",
    max_batch_tokens: int = 6000,
) -> None:

    page_id = myutils.unshorten_id(myutils.shorten_id(myutils.extract_uuids(page_url)[0]))
    notion_page_process(notion_token, page_id, out_q, max_batch_tokens)
    out_q.put(NotionTextChunk("eof", "eof", "eof"))
    print(f"\nFINISHED NOTION SCAN\n")

def llm_consumer_worker(
    prompt: str,
    in_q: "queue.Queue[NotionTextChunk | object]",
    llm_model: str = "gpt-4o-mini",
    max_batch_tokens: int = 6000,
) -> None:
    """
    Consume NotionTextChunk items and send to your LLM.
    """

    if "gpt-oss" not in llm_model:
        openai_apikey = OpenAICredentialsLoader().get_api_key()
        os.environ["OPENAI_API_KEY"] = openai_apikey
        from openai import OpenAI, OpenAIError
        llm_client = OpenAI()
    else:
        ensure_ollama_up()

    start_date = datetime.now()

    answers = []

    html_head = f"""<!doctype html>
    <html lang="en">
    <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Notion Librarian Answer</title>
    <link rel="stylesheet" href="../web/style.css" />
    <script src="../web/markdown-it.min.js"></script>
    <script src="../web/purify.min.js"></script>
    </head><body>\n
    """
    fname = "answer-" + start_date.strftime("%Y-%m-%d-%H-%M-%S") + ".html"
    dirname = "answers"
    os.makedirs(dirname, exist_ok=True)
    fpath = os.path.join(dirname, fname)
    with open(fpath, "w") as f:
        f.write(html_head)
        f.write(f"<div class='prompt'><fieldset class='prompt'><legend>Prompt:</legend><div class='prompt-inner'>{prompt}</div></fieldset></div>\n")

        progtracker.on_inference(in_q.qsize())

        while True:
            item = in_q.get()
            if item.is_eof():
                in_q.task_done()
                break
            if STOP.is_set():
                break
            try:
                #print(f"TEXT: {item.text}")
                if "gpt-oss" not in llm_model:
                    answer = judge_and_answer_structured(llm_client, item.text, prompt, llm_model) # this returns a JSON object with our custom structure
                else:
                    answer = judge_and_answer_oss(item.text, prompt)
                progtracker.on_inference(in_q.qsize())
                if answer.get("related", "").upper() == "YES":
                    ans = LibrarianAnswer(answer, item)
                    answers.append(ans)
                    url = item.get_url()
                    print(f"\nANSWER URL: {url}")
                    print(f"ANSWER TXT: {answer.get("answer", "")}")
                    breadcrumb = get_breadcrumb_with_block_text(notion_token, item.page_id, item.block_id)
                    html = f"<div class='answer-outer'><fieldset class='answer'><legend><a href='{url}' target='_blank'>{breadcrumb}</a></legend>"
                    html += "<div class='answer-inner-1'>\n"
                    html += answer.get("answer", "")
                    html += "\n</div>\n"
                    f.write(html)
                    f.flush()
                    evidences = answer.get("evidence", "")
                    if len(evidences) > 0:
                        for ev in evidences:
                            if ev and ev.strip():
                                ev_block_id = find_block_by_evidence(notion_token, item.page_id, ev, item.block_id)
                                if ev_block_id is not None:
                                    ev_url = f"https://www.notion.so/{myutils.shorten_id(item.page_id)}#{myutils.shorten_id(ev_block_id)}"
                                    ev_text = f"{ev} [<a href='{ev_url}' target='_blank'>link</a>]"
                                else:
                                    ev_text = f"{ev}"
                                html += f"<div class='answer-inner-evidence'>{ev_text}</div>\n"
                    html += "\n</fieldset></div>\n"
            except KeyboardInterrupt:
                f.flush()
                break
        if len(answers) <= 0:
            html += f"<h3>Sorry! No Results</h3>\n"
            print("Sorry! No Results")
        f.write("</body></html>")

    print(f"answer written to '{fpath}'")
    myutils.open_html_new_window(fpath)

def main():
    p = argparse.ArgumentParser(description="Notion Librarian")
    p.add_argument("url", help="URL (or string) containing the Notion page UUID")
    p.add_argument("prompt", help="Prompt to send alongside Notion content")

    p.add_argument("--model", default=
        #"gpt-5-nano"
        #"gpt-oss-20b"
        "gpt-oss-20b-3060"
           , help="LLM model name")
    p.add_argument("--max-batch-tokens", type=int, default=4000, help="Approx token cap per LLM request")

    args = p.parse_args()

    q = queue.Queue(maxsize=1024)

    prod = threading.Thread(
        target=notion_producer_worker,
        name="producer",
        args=(args.url, q, args.max_batch_tokens),
        daemon=True,
    )
    cons = threading.Thread(
        target=llm_consumer_worker,
        name="consumer",
        args=(args.prompt, q, args.model, args.max_batch_tokens),
        daemon=True,
    )

    prod.start()
    cons.start()

    try:
        prod.join()
        while cons.is_alive() and not STOP.is_set():
            cons.join(timeout=0.2)
    except KeyboardInterrupt:
        print("\nGoodbye")
        quit()
    finally:
        STOP.set()
        if cons.is_alive():
            cons.join(timeout=2.0)
        if cons.is_alive():
            os._exit(0)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
