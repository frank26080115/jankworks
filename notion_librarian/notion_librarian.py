#!/usr/bin/env python3
import argparse
import queue
import threading, signal
import time
import json
import os, sys
from datetime import datetime
from pathlib import Path

from openai import OpenAI, OpenAIError

import myutils
import keywordextract
from notion_authtoken_reader import AuthTokenFileReader
from openai_credloader import OpenAICredentialsLoader
from chunker import notion_page_to_h1_chunks
from notiondata import NotionTextChunk
from textsplitter import windowed_markdown_chunks
from llmcall import judge_and_answer, ensure_ollama_up
from notion_breadcrumb import get_breadcrumb_with_block_text
from evidencelink import find_block_by_evidence
from progresstracker import ProgressTracker
from ollamamodels import has_ollama_model, is_local

STOP = threading.Event()

def _stop_now(signum, frame):
    # Minimal work in a signal handler: set an Event that loops can see.
    STOP.set()

signal.signal(signal.SIGINT, _stop_now)    # Ctrl+C
if hasattr(signal, "SIGBREAK"):            # Windows: Ctrl+Break (sometimes easier to hit)
    signal.signal(signal.SIGBREAK, _stop_now)

notion_token = AuthTokenFileReader().get_token()
llm_client = None
llm_can_start = False

progtracker = ProgressTracker()

class LibrarianAnswer(object):
    def __init__(self, json, chunk):
        self.json = json
        self.chunk = chunk

def notion_page_process(notion_token, page_id, out_q, max_batch_tokens = 6000, keywords: dict = None):
    page_id = myutils.unshorten_id(myutils.shorten_id(myutils.extract_uuids(page_id)[0]))
    chunks, children = notion_page_to_h1_chunks(notion_token, page_id)
    for key, md in chunks.items():
        subchunks = windowed_markdown_chunks(md, max_batch_tokens)
        for c in subchunks:
            s = 0
            if keywords is not None:
                s = keywordextract.score_block(c, keywords)
            else:
                progtracker.on_add()
            nc = NotionTextChunk(page_id, key, c, score=s)
            out_q.put(nc)
    for cp in children:
        notion_page_process(notion_token, cp, out_q, max_batch_tokens, keywords)

def notion_producer_worker(
    page_url: str,
    prompt: str,
    out_q: "queue.Queue[NotionTextChunk | object]",
    max_batch_tokens: int = 6000,
    llm_model: str = "gpt-4o-mini",
    keywords: dict = None,
    superfast: bool = False,
    timelimit: int = 0,
) -> None:
    global llm_can_start

    page_id = myutils.unshorten_id(myutils.shorten_id(myutils.extract_uuids(page_url)[0]))
    notion_page_process(notion_token, page_id, out_q, max_batch_tokens, keywords)

    if keywords is not None:
        items = []
        while True:
            try:
                items.append(out_q.get_nowait())
            except queue.Empty:
                break
        items.sort(key=lambda x: x.score, reverse=True)

        if not items:
            pass # do nothing if no results
        elif timelimit <= 0:
            max_score = items[0].score
            if max_score > 0:
                cutoff = (0.8 if superfast else 0.5) * max_score  # ≥80% of the best score
                filtered = [it for it in items if it.score >= cutoff]
                #top10 = filtered[:10]
                for item in filtered:
                    out_q.put(item)
                    progtracker.on_add()
        else:
            # there is a time limit, so just put the ordered list back into the queue
            for item in items:
                out_q.put(item)
                progtracker.on_add()

    out_q.put(NotionTextChunk("eof", "eof", "eof"))
    print(f"\nFINISHED NOTION SCAN\n")
    llm_can_start = True

def llm_consumer_worker(
    prompt: str,
    in_q: "queue.Queue[NotionTextChunk | object]",
    llm_model: str = "gpt-4o-mini",
    max_batch_tokens: int = 6000,
    keywords: dict = None,
    superfast: bool = False,
    timelimit: int = 0,
) -> None:
    global llm_client, llm_can_start
    """
    Consume NotionTextChunk items and send to your LLM.
    """

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
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html_head)
        f.write(f"<div class='prompt'><fieldset class='prompt'><legend>Prompt:</legend><div class='prompt-inner'>{prompt}</div></fieldset></div>\n")

        if keywords is not None:
            kw_text = ""
            for i, j in keywords.items():
                kw_text += f"<p><b>{i}:</b></p><ul class='keywords ul-inline'>\n"
                if len(j) <= 0:
                    kw_text += f"<li class='keyword-item'>(None)</li>\n"
                else:
                    for k in j:
                        kw_text += f"<li class='keyword-item'>{k}</li>\n"
                kw_text += f"</ul>\n"
            f.write(f"<div class='keywords'><fieldset class='keywords'><legend>Keywords:</legend><div class='keywords-inner'>{kw_text}</div></fieldset></div>\n")
            f.flush()
            while True:
                time.sleep(0.5)
                if llm_can_start:
                    break

        while True:

            t_now = datetime.now()
            if timelimit > 0:
                dt = t_now - start_date
                if dt.total_seconds() > timelimit * 60:
                    break

            item = in_q.get()
            if item.is_eof():
                in_q.task_done()
                break
            if STOP.is_set():
                break
            if superfast:
                ans = LibrarianAnswer(item, item)
                answers.append(ans)
                url = item.get_url()
                print(f"\nANSWER URL: {url}")
                print(f"ANSWER TXT: {item.text}")
                breadcrumb = get_breadcrumb_with_block_text(notion_token, item.page_id, item.block_id)
                html = f"<div class='answer-outer'><fieldset class='answer'><legend><a href='{url}' target='_blank'>{breadcrumb}</a></legend>"
                html += "<div class='answer-inner-1'><pre>\n"
                html += myutils.to_html_numeric(item.text)
                html += "\n</pre></div>\n"
                html += "\n</fieldset></div>\n"
                f.write(html)
                f.flush()
                continue
            try:
                #print(f"TEXT: {item.text}")
                answer = judge_and_answer(llm_client, item.text, prompt, llm_model)
                progtracker.on_inference(in_q.qsize())
                if answer and answer.get("related", "").upper() == "YES":
                    ans = LibrarianAnswer(answer, item)
                    answers.append(ans)
                    url = item.get_url()
                    answer_txt = answer.get("answer", "")
                    print(f"\nANSWER URL: {url}")
                    print(f"ANSWER TXT: {answer_txt}")
                    breadcrumb = get_breadcrumb_with_block_text(notion_token, item.page_id, item.block_id)
                    html = f"<div class='answer-outer'><fieldset class='answer'><legend><a href='{url}' target='_blank'>{breadcrumb}</a></legend>"
                    html += "<div class='answer-inner-1'><pre>\n"
                    html += myutils.to_html_numeric(answer.get("answer", ""))
                    html += "\n</pre></div>\n"
                    evidences = answer.get("evidence", "")
                    if len(evidences) > 0:
                        for ev in evidences:
                            if ev and ev.strip():
                                ev_block_id = find_block_by_evidence(notion_token, item.page_id, ev, item.block_id)
                                ev_text = myutils.to_html_numeric(ev)
                                if ev_block_id is not None:
                                    ev_url = f"https://www.notion.so/{myutils.shorten_id(item.page_id)}#{myutils.shorten_id(ev_block_id)}"
                                    ev_text += f"&nbsp;[<a href='{ev_url}' target='_blank'>link</a>]"
                                html += f"<div class='answer-inner-evidence'>{ev_text}</div>\n"
                    html += "\n</fieldset></div>\n"
                    f.write(html)
                    f.flush()
            except KeyboardInterrupt:
                f.flush()
                break
        if len(answers) <= 0:
            f.write(f"<h3>Sorry! No Results</h3>\n")
            print("Sorry! No Results")
        f.write("</body></html>")

    print(f"answer written to '{fpath}'")
    myutils.open_html_new_window(fpath)

def main():
    global llm_client, llm_can_start

    p = argparse.ArgumentParser(description="Notion Librarian")
    p.add_argument("url", help="URL (or string) containing the Notion page UUID")
    p.add_argument("prompt", help="Prompt to send alongside Notion content")

    p.add_argument("--model", default=
        #"gpt-5-nano"
        "gpt-oss:20b"
        #"gpt-oss-20b-3060"
           , help="LLM model name")
    p.add_argument("--max-batch-tokens", type=int, default=4000, help="Approx token cap per LLM request")
    p.add_argument("--timelimit", type=int, default=0, help="Total time limit for request in minutes")
    p.add_argument("--prefilter", default=False, action="store_true", help="Pre-filter the Notion page using auto-generated keywords")
    p.add_argument("--superfast", default=False, action="store_true", help="Only do fast keyword search")

    args = p.parse_args()

    ensure_ollama_up()

    if not has_ollama_model(args.model):
        openai_apikey = OpenAICredentialsLoader().get_api_key()
        os.environ["OPENAI_API_KEY"] = openai_apikey
        llm_client = OpenAI()
        print("Using OpenAI online model")
    else:
        llm_client = OpenAI(
            base_url="http://127.0.0.1:11434/v1",  # Ollama's OpenAI-compatible endpoint
            api_key="ollama"  # any non-empty string
        )
        print("Using offline OSS model")

    keywords = None
    if args.prefilter or args.superfast:
        import keywordextract
        print("Extracting keywords...", end="", flush=True)
        kw = keywordextract.llm_extract_keywords(llm_client, args.prompt, args.model)
        keywords = keywordextract.expand_keyword_bundle(kw)
        '''print("KEYWORDS EXTRACTED")
        for i, j in keywords.items():
            print(f" # {i}:")
            for k in j:
                print(f"   > {k}")
        print("=====")'''
        print("Done!")
    else:
        llm_can_start = True

    q = queue.Queue(maxsize=1024)

    prod = threading.Thread(
        target=notion_producer_worker,
        name="producer",
        args=(args.url, args.prompt, q, args.max_batch_tokens, args.model, keywords, args.superfast, args.timelimit),
        daemon=True,
    )
    cons = threading.Thread(
        target=llm_consumer_worker,
        name="consumer",
        args=(args.prompt, q, args.model, args.max_batch_tokens, keywords, args.superfast, args.timelimit),
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
