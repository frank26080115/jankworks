from typing import Dict, List, Optional, Tuple
from notion_client import Client

import time

import myutils
import notiondata

NOTION_VERSION = "2022-06-28"  # stable for Blocks API

def notion_page_to_h1_chunks(api_key: str, page_id: str) -> Tuple[Dict[str, str], List[str]]:
    """
    Split a Notion page into markdown chunks at each heading_1, and also
    collect UUIDs of child pages (blocks of type 'child_page').

    Returns:
        (chunks_dict, child_page_ids)
          - chunks_dict: { heading_1_block_uuid | page_id_for_intro : markdown }
          - child_page_ids: [uuid_of_child_page_block, ...]
    """

    page_id = myutils.unshorten_id(myutils.shorten_id(myutils.extract_uuids(page_id)[0]))

    client = Client(auth=api_key, notion_version=NOTION_VERSION)

    last_edited_time = myutils.get_page_last_edited_datetime(client, page_id)
    datacache = notiondata.load_page_cache(page_id)
    if datacache is not None:
        if datacache.dt >= last_edited_time:
            return datacache.chunks, datacache.child_pages

    # ------------ helpers ----------------------------------------------------

    def fetch_children(block_id: str) -> List[dict]:
        results: List[dict] = []
        cursor: Optional[str] = None
        while True:
            time.sleep(0.3)
            resp = client.blocks.children.list(block_id=block_id, start_cursor=cursor)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    def rt_inline(rt: dict) -> str:
        txt = rt.get("plain_text", "") or ""
        href = rt.get("href")
        ann = rt.get("annotations") or {}
        if ann.get("code"):
            txt = f"`{txt}`"
        if ann.get("bold"):
            txt = f"**{txt}**"
        if ann.get("italic"):
            txt = f"*{txt}*"
        if ann.get("strikethrough"):
            txt = f"~~{txt}~~"
        if ann.get("underline"):
            txt = f"<u>{txt}</u>"
        if href:
            txt = f"[{txt}]({href})"
        return txt

    def join_rich_text(rts: List[dict]) -> str:
        return "".join(rt_inline(rt) for rt in (rts or []))

    def fence(lang: Optional[str]) -> str:
        return f"```{(lang or '').strip()}\n"

    list_state = {"mode": None, "counter": 0}
    child_page_ids: List[str] = []

    def ensure_list_mode(mode: Optional[str]):
        if list_state["mode"] != mode:
            list_state["mode"] = mode
            list_state["counter"] = 0

    def render_block(block: dict, indent_level: int = 0) -> List[str]:
        """Render a block to markdown, noting child pages when seen."""
        btype = block.get("type")
        block_id = block.get("id")
        body = block.get(btype) or {}
        lines: List[str] = []
        indent = "  " * indent_level

        # --- Detect child pages anywhere they appear ---
        if btype == "child_page":
            # The block id for a child_page is also the child page's UUID
            child_page_ids.append(block["id"])
            # Optional: render a link-ish line for visibility
            title = body.get("title") or "(untitled page)"
            lines.append(indent + f"- [[{title}]]")  # simple marker; no URL here
            return lines

        if btype == "paragraph":
            ensure_list_mode(None)
            lines.append(indent + join_rich_text(body.get("rich_text")))
        elif btype == "heading_1":
            ensure_list_mode(None)
            lines.append("# " + join_rich_text(body.get("rich_text")) + "[" + block_id + "]")
        elif btype == "heading_2":
            ensure_list_mode(None)
            lines.append("## " + join_rich_text(body.get("rich_text")))
        elif btype == "heading_3":
            ensure_list_mode(None)
            lines.append("### " + join_rich_text(body.get("rich_text")))
        elif btype == "quote":
            ensure_list_mode(None)
            for ln in (join_rich_text(body.get("rich_text")) or "").splitlines() or [""]:
                lines.append(indent + "> " + ln)
        elif btype == "callout":
            ensure_list_mode(None)
            icon = (body.get("icon") or {}).get("emoji") or "💡"
            text = join_rich_text(body.get("rich_text"))
            lines.append(indent + f"> {icon} {text}")
        elif btype == "code":
            ensure_list_mode(None)
            lang = (body.get("language") or "").strip()
            text = join_rich_text(body.get("rich_text"))
            lines.append(fence(lang) + text + "\n```")
        elif btype in ("bulleted_list_item", "numbered_list_item", "to_do"):
            if btype == "bulleted_list_item":
                ensure_list_mode("ul")
                lines.append(indent + "- " + join_rich_text(body.get("rich_text")))
            elif btype == "numbered_list_item":
                ensure_list_mode("ol")
                list_state["counter"] += 1
                lines.append(indent + f"{list_state['counter']}. " + join_rich_text(body.get("rich_text")))
            else:
                ensure_list_mode(None)
                checked = body.get("checked", False)
                mark = "x" if checked else " "
                lines.append(indent + f"- [{mark}] " + join_rich_text(body.get("rich_text")))

            if block.get("has_children"):
                for ch in fetch_children(block["id"]):
                    lines.extend(render_block(ch, indent_level + 1))

        elif btype == "toggle":
            ensure_list_mode(None)
            summary = join_rich_text(body.get("rich_text"))
            lines.append(indent + f"<details><summary>{summary}</summary>")
            if block.get("has_children"):
                for ch in fetch_children(block["id"]):
                    lines.extend(render_block(ch, indent_level + 1))
            lines.append(indent + "</details>")
        elif btype == "divider":
            ensure_list_mode(None)
            lines.append("---")
        elif btype == "bookmark":
            ensure_list_mode(None)
            url = body.get("url", "")
            lines.append(indent + f"[{url}]({url})")
        elif btype == "image":
            ensure_list_mode(None)
            f = body.get("file") or body.get("external") or {}
            url = f.get("url", "")
            cap = join_rich_text(body.get("caption"))
            alt = cap or "image"
            lines.append(indent + f"![{alt}]({url})")
        elif btype == "equation":
            ensure_list_mode(None)
            expr = (body.get("expression") or "").strip()
            lines.append(indent + f"$$\n{expr}\n$$")
        else:
            ensure_list_mode(None)
            if "rich_text" in body:
                lines.append(indent + join_rich_text(body.get("rich_text")))

        if block.get("has_children") and btype not in ("bulleted_list_item", "numbered_list_item", "to_do", "toggle"):
            for ch in fetch_children(block["id"]):
                lines.extend(render_block(ch, indent_level + 1))

        return [ln.rstrip() for ln in lines]

    def normalize_md(md: str) -> str:
        lines = md.splitlines()
        cleaned: List[str] = []
        blanks = 0
        for ln in lines:
            if ln.strip() == "":
                blanks += 1
                if blanks <= 2:
                    cleaned.append("")
            else:
                blanks = 0
                cleaned.append(ln)
        return "\n".join(cleaned).strip() + "\n"

    # ------------ main -------------------------------------------------------

    blocks = fetch_children(page_id)  # top-level blocks of the page
    chunks: Dict[str, List[str]] = {}
    current_key: Optional[str] = None

    def ensure_intro_key():
        nonlocal current_key
        if current_key is None:
            current_key = page_id
            chunks.setdefault(current_key, [])

    for blk in blocks:
        btype = blk.get("type")
        if btype == "heading_1":
            current_key = blk["id"]
            chunks.setdefault(current_key, [])
            chunks[current_key].extend(render_block(blk))  # include the H1 line
            chunks[current_key].append("")
            list_state["mode"], list_state["counter"] = None, 0
        else:
            ensure_intro_key()
            chunks[current_key].extend(render_block(blk))

    chunks_dict = {k: normalize_md("\n".join(v)) for k, v in chunks.items()}
    # Deduplicate while preserving order
    seen = set()
    child_ids_unique = []
    for cid in child_page_ids:
        if cid not in seen:
            seen.add(cid)
            child_ids_unique.append(cid)

    datacache = notiondata.NotionPageCache(page_id, last_edited_time, chunks_dict, child_ids_unique)
    datacache.save()

    return chunks_dict, child_ids_unique

if __name__ == "__main__":
    from notion_authtoken_reader import AuthTokenFileReader
    x = AuthTokenFileReader()
    #print(x.get_token())
    uuid = "1f8dfffdf25c80b48308fa1c1dfc0c1b"
    chunks, children = notion_page_to_h1_chunks(x.get_token(), myutils.unshorten_id(uuid))
    for key, md in chunks.items():
        print(f"\n=== {key} ===\n{md}")
