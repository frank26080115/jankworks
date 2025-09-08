#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
dom_pattern_finder.py
Detect repeated item-like structures in large HTML pages (invoices/orders/catalogs).

Usage examples:
  python dom_pattern_finder.py --file sample.html --topn 5 --save-snippets out_snips
  python dom_pattern_finder.py --url https://example.com/order/123 --topn 3 --json-report report.json
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse, unquote
from collections import Counter

import lxml.html
import lxml.etree
import lxml.etree as ET

CURRENCY_RE = re.compile(r'(?i)(?:[$€£]\s?\d[\d,]*(?:\.\d{2})?|USD\s?\d[\d,]*(?:\.\d{2})?)')
QTY_WORD_RE = re.compile(r'(?i)\b(qty|quantity|count|pcs|units?)\b')
QTY_PAT_RE = re.compile(r'(?i)\b(?:x\s?\d+|\d+\s?x)\b')
SKU_RE = re.compile(r'(?i)\b(SKU|Item\s?#|Part\s?#|Model|PN|P/N|ASIN|UPC)\b')
PRICE_WORD_RE = re.compile(r'(?i)\b(total|price|amount|subtotal|line\s?total|unit\s?price)\b')
NUMBERY_RE = re.compile(r'\d')

# Words on invoice/order pages that hint "line item containers"
LINE_ITEM_HINTS = re.compile(r'(?i)\b(item|line\s?item|product|description)\b')

# Minimal children to consider a repeating sibling block
MIN_REPEAT = 3

def text_clean(s):
    if s is None:
        return ""
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def subtree_text(el, limit=2000):
    # Extract text content with a soft limit
    txt = ' '.join(el.itertext())
    txt = text_clean(txt)
    return txt[:limit]

def class_signature(el):
    classes = el.get('class', '')
    if isinstance(classes, str):
        tokens = sorted(set(c for c in classes.split() if c))
    else:
        tokens = []
    return '.'.join(tokens)

def child_tag_hist(el, max_k=5):
    c = Counter([child.tag for child in el if isinstance(child, lxml.etree._Element)])
    # keep top-k to avoid huge signatures
    items = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:max_k]
    return tuple(items)

def node_signature(el):
    """Signature used to group siblings."""
    return (
        el.tag,
        class_signature(el),
        child_tag_hist(el, max_k=6),
        bool(el.xpath('.//img')),
        bool(el.xpath('.//a')),
    )

def depth_of(el):
    d = 0
    cur = el
    while cur.getparent() is not None:
        d += 1
        cur = cur.getparent()
    return d

def looks_like_table(el):
    return el.tag == 'table' or (len(el.xpath('.//tr')) >= MIN_REPEAT and len(el.xpath('.//td|.//th')) >= 6)

def header_hints(el):
    head_txt = ' '.join([text_clean(t.text_content()) for t in el.xpath('.//th')][:10])
    return PRICE_WORD_RE.search(head_txt) or QTY_WORD_RE.search(head_txt) or LINE_ITEM_HINTS.search(head_txt)

def count_matches(text):
    return {
        "currency": len(CURRENCY_RE.findall(text)),
        "qty_word": len(QTY_WORD_RE.findall(text)),
        "qty_pat": len(QTY_PAT_RE.findall(text)),
        "sku": len(SKU_RE.findall(text)),
        "price_word": len(PRICE_WORD_RE.findall(text)),
        "numbers": len(NUMBERY_RE.findall(text)),
    }

def normalize_path(path):
    # convert /product/1234/blue -> /product/{num}/{word}
    segs = [seg for seg in path.split('/') if seg]
    norm = []
    for s in segs:
        if s.isdigit():
            norm.append('{num}')
        elif re.fullmatch(r'[0-9a-fA-F]{8,}', s):
            norm.append('{hex}')
        elif re.search(r'\d', s):
            norm.append('{alnum}')
        else:
            norm.append('{word}')
    return '/' + '/'.join(norm)

def href_templates(root):
    hrefs = [a.get('href') for a in root.xpath('.//a[@href]')]
    tpl_counter = Counter()
    domains = Counter()
    for h in hrefs:
        try:
            u = urlparse(h)
        except Exception:
            continue
        domains[u.netloc] += 1 if u.netloc else 0
        p = u.path or '/'
        tpl = f"{u.netloc}{normalize_path(p)}" if u.netloc else normalize_path(p)
        tpl_counter[tpl] += 1
    return tpl_counter, domains

def score_container(el):
    """Heuristic scoring for 'this is an item list'."""
    txt = subtree_text(el, limit=3000)
    counts = count_matches(txt)
    anchors = el.xpath('.//a')
    images = el.xpath('.//img')
    rows = el.xpath('./*')

    score = 0.0
    # signal from money/qty/sku words
    score += counts["currency"] * 3.0
    score += (counts["qty_word"] + counts["qty_pat"]) * 1.5
    score += counts["sku"] * 2.0
    score += counts["price_word"] * 1.25

    # structural signals
    # many child rows with similar signatures (added by caller)
    # anchors/images typical for product tiles
    score += min(len(anchors), 20) * 0.2
    score += min(len(images), 20) * 0.2
    score += min(len(rows), 25) * 0.15

    # boost for tables with header hints
    if looks_like_table(el) and header_hints(el):
        score += 6.0

    # slight boost for length & numbers (but cap so huge text doesn’t dominate)
    score += min(counts["numbers"] / 30.0, 3.0)

    return score

def slice_html(el):
    """Return a minimal outerHTML for inspection."""
    return lxml.html.tostring(el, encoding='unicode', pretty_print=True)

def group_repeating_siblings(root):
    """Find parents whose children repeat by signature."""
    candidates = []
    for parent in root.iter():
        if not isinstance(parent, lxml.etree._Element):
            continue
        kids = [c for c in parent if isinstance(c, lxml.etree._Element)]
        if len(kids) < MIN_REPEAT:
            continue
        buckets = defaultdict(list)
        for k in kids:
            sig = node_signature(k)
            buckets[sig].append(k)
        # we only care if some signature repeats enough
        best_sig, best_group = None, []
        for sig, group in buckets.items():
            if len(group) >= MIN_REPEAT:
                if len(group) > len(best_group):
                    best_sig, best_group = sig, group

        if best_group:
            candidates.append({
                "parent": parent,
                "group_size": len(best_group),
                "unique_sigs": len([1 for sig, g in buckets.items() if len(g) >= MIN_REPEAT]),
                "child_signature": str(best_sig),
                "depth": depth_of(parent),
            })
    return candidates

def analyze(html, base_url=None, topn=5):
    root = lxml.html.fromstring(html)
    root = sanitize_dom(root)
    root.make_links_absolute(base_url) if base_url else None

    # tag frequency by depth
    tag_by_depth = defaultdict(Counter)
    for el in root.iter():
        if isinstance(el, lxml.etree._Element):
            tag_by_depth[depth_of(el)][el.tag] += 1

    # class frequency
    class_freq = Counter()
    for el in root.iter():
        if isinstance(el, lxml.etree._Element):
            cs = class_signature(el)
            if cs:
                class_freq[cs] += 1

    # href templates
    href_tpls, domains = href_templates(root)

    # repeating sibling containers
    rep = group_repeating_siblings(root)
    # also consider obvious tables
    for table in root.xpath('.//table'):
        rep.append({
            "parent": table,
            "group_size": len(table.xpath('.//tr')),
            "unique_sigs": 1,
            "child_signature": "TABLE/TR",
            "depth": depth_of(table),
        })

    # score and sort candidates
    scored = []
    for r in rep:
        el = r["parent"]
        s = score_container(el)
        # extra signal: bigger repeating groups & multiple repeating signatures under same parent
        s += min(r["group_size"] / 3.0, 6.0)
        s += min(r["unique_sigs"], 3) * 0.5
        url_info = first_href(el)
        scored.append({
            "score": round(s, 3),
            "depth": r["depth"],
            "group_size": r["group_size"],
            "child_signature": r["child_signature"],
            "xpath": el.getroottree().getpath(el),
            "preview_text": subtree_text(el, limit=240),
            "html_bytes": len(slice_html(el).encode('utf-8')),
            "url": url_info["url"],
            "anchor_text": url_info["text"],
            "element": el,
        })

    scored.sort(key=lambda x: (-x["score"], x["depth"]))

    # --- Depth histogram → double scores at the modal depth(s) ---
    if scored:
        depth_hist = Counter(c["depth"] for c in scored)
        if depth_hist:
            mode_count = max(depth_hist.values())
            modal_depths = {d for d, cnt in depth_hist.items() if cnt == mode_count}
            if mode_count > 1 and len(modal_depths) > 0:
                # keep original score (optional, useful for debugging)
                for c in scored:
                    if "preboost_score" not in c:
                        c["preboost_score"] = c["score"]

                # double scores for modal depths
                for c in scored:
                    if c["depth"] in modal_depths:
                        c["score"] = round(c["score"] * 10.0, 3)

                # resort after boosting
                scored.sort(key=lambda x: (-x["score"], x["depth"]))

    # Build compact report (no raw elements)
    report = {
        "top_candidates": [
            {k: v for k, v in cand.items() if k != "element"}
            for cand in scored[:topn]
        ],
        "class_frequency_top20": class_freq.most_common(20),
        "href_templates_top20": href_tpls.most_common(20),
        "href_domains_top10": domains.most_common(10),
        "tag_by_depth_top": {
            str(d): Counter(c).most_common(10)
            for d, c in list(tag_by_depth.items())
        },
    }
    return report, scored

def extract_rows_from_container(el, min_repeat=3):
    children = [c for c in el if isinstance(c, lxml.etree._Element)]
    if not children:
        children = el.xpath('./*/*')

    buckets = defaultdict(list)
    for c in children:
        buckets[node_signature(c)].append(c)

    best = max(buckets.items(), key=lambda kv: len(kv[1])) if buckets else (None, [])
    rows = best[1] if best and len(best[1]) >= min_repeat else children

    return [{
        "xpath": c.getroottree().getpath(c),
        "text": subtree_text(c, 200),
        "url": first_href(c)  # 👈 new
    } for c in rows]

SKIP_TAGS = {"script", "style", "noscript", "template"}

def sanitize_dom(root):
    """
    Mutates the tree:
      - removes <script>, <style>, <noscript>, <template> (and their content)
      - removes HTML comments <!-- ... -->
    """
    # strip entire elements (no tail kept)
    for tag in list(SKIP_TAGS):
        for el in root.xpath(f'//{tag}'):
            el.drop_tree()

    # remove comments
    for c in root.xpath('//comment()'):
        p = c.getparent()
        if p is not None:
            p.remove(c)

    return root


def xpath_of(el):
    tree = el.getroottree()
    if tree is None:
        # Very rare fallback; builds a tree if one wasn’t attached
        tree = lxml.etree.ElementTree(el)
    return tree.getpath(el)

#def first_href(el):
#    # Returns the first href within this element, else empty string.
#    a = el.xpath('.//a[@href][1]')
#    if a:
#        href = a[0].get('href') or ''
#        return href
#    return ''

def first_href(el):
    """
    Return {'url': <string>, 'text': <anchor_text>} from the first usable <a href>.
    Falls back to empty strings if none found.
    """
    # find first anchor with an href
    anchors = el.xpath('.//a[@href]')
    for a in anchors:
        href = (a.get('href') or '').strip()
        if not href:
            continue
        # skip non-navigational or junk hrefs
        if href.startswith(('javascript:', '#')):
            continue
        # keep it short; adjust limit if you want more
        text = subtree_text(a, limit=200)
        return {"url": href, "text": text}
    return {"url": "", "text": ""}

def save_snippets(scored, out_dir, limit=5):
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, cand in enumerate(scored[:limit]):
        el = cand["element"]
        snippet = slice_html(el)
        path = os.path.join(out_dir, f"candidate_{i+1}.html")
        with open(path, 'w', encoding='utf-8') as f:
            # wrap in a minimal document so it renders standalone
            f.write("<!doctype html><meta charset='utf-8'><style>body{font-family:system-ui,Segoe UI,Arial} .hint{color:#555}</style>")
            f.write(f"<div class='hint'>score={cand['score']} depth={cand['depth']} group_size={cand['group_size']} xpath={cand['xpath']}</div>")
            f.write(snippet)
        paths.append(path)
    return paths

def load_input(file=None, url=None):
    if file:
        with open(file, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(), None
    elif url:
        # Minimal stdlib fetch to avoid extra deps
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PatternFinder)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        return html, url
    else:
        raise ValueError("Provide --file or --url")

class SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

def main():
    ap = argparse.ArgumentParser(description="Find repeated item-like structures in an HTML page.")
    ap.add_argument("--file", help="Path to local HTML file")
    ap.add_argument("--url", help="URL to fetch")
    ap.add_argument("--topn", type=int, default=99999, help="How many top candidates to show/save")
    ap.add_argument("--save-snippets", help="Directory to write candidate_#.html")
    ap.add_argument("--json-report", help="Write JSON summary to this file")
    args = ap.parse_args()

    html, base_url = load_input(file=args.file, url=args.url)
    report, scored = analyze(html, base_url=base_url, topn=args.topn)

    # Print a compact summary to stdout
    jstr = json.dumps(report, indent=2, ensure_ascii=False, cls=SafeEncoder)
    if not args.save_snippets and not args.json_report:
        print(jstr)

    if args.save_snippets:
        paths = save_snippets(scored, args.save_snippets, limit=args.topn)
        print("\nSaved snippets:")
        for p in paths:
            print("  -", p)

    if args.json_report:
        with open(args.json_report, 'w', encoding='utf-8') as f:
            f.write(jstr)

if __name__ == "__main__":
    main()
