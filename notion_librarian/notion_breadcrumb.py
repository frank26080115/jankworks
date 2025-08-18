from typing import List, Optional
from notion_client import Client

def get_breadcrumb_with_block_text(
    api_token: str,
    page_id: str,
    block_id: str,
    delimiter: str = "/",
) -> str:
    """
    Build a breadcrumb of page/database titles up to the workspace, then append
    the block's text content. All joined with the chosen delimiter (default '/').
    """
    client = Client(auth=api_token)

    # ---------- helpers ----------
    def _join_rich_text(rts: List[dict]) -> str:
        # Plain-text join (keeps links' visible text, ignores styling)
        return "".join(rt.get("plain_text", "") for rt in (rts or []))

    def _page_title(page_obj: dict) -> str:
        # For standalone pages and DB items, the title prop is the one with type='title'
        props = page_obj.get("properties", {}) or {}
        for p in props.values():
            if p.get("type") == "title":
                return _join_rich_text(p.get("title", [])) or "(untitled)"
        # Fallback: some API responses also have 'title' at top-level for legacy objects
        if "title" in page_obj:
            return _join_rich_text(page_obj.get("title", [])) or "(untitled)"
        return "(untitled)"

    def _database_title(db_obj: dict) -> str:
        return _join_rich_text(db_obj.get("title", [])) or "(database)"

    def _block_text(b: dict) -> str:
        btype = b.get("type")
        body = b.get(btype, {}) or {}
        # Common rich_text-based blocks
        if btype in ("paragraph", "heading_1", "heading_2", "heading_3",
                     "bulleted_list_item", "numbered_list_item", "to_do",
                     "callout", "quote"):
            base = _join_rich_text(body.get("rich_text", []))
            if btype == "to_do":
                # Optionally include checkbox state
                checked = body.get("checked", False)
                prefix = "[x] " if checked else "[ ] "
                return prefix + base
            return base
        if btype == "code":
            return _join_rich_text(body.get("rich_text", []))
        if btype == "equation":
            return body.get("expression", "") or ""
        if btype == "bookmark":
            return body.get("url", "") or ""
        if btype == "child_page":
            return body.get("title", "") or "(page)"
        # Fallback: try generic rich_text
        if "rich_text" in body:
            return _join_rich_text(body.get("rich_text", []))
        # Otherwise return empty
        return ""

    # ---------- build breadcrumb ----------
    # Start from the provided page_id and walk up via 'parent'
    breadcrumb_parts: List[str] = []
    cur_page_id: Optional[str] = page_id

    visited = set()
    while cur_page_id and cur_page_id not in visited:
        visited.add(cur_page_id)
        page = client.pages.retrieve(page_id=cur_page_id)
        breadcrumb_parts.append(_page_title(page))

        parent = page.get("parent", {}) or {}
        ptype = parent.get("type")
        if ptype == "page_id":
            cur_page_id = parent.get("page_id")
            continue
        elif ptype == "database_id":
            # Prepend database title, then stop (DB’s parent may be workspace)
            db = client.databases.retrieve(database_id=parent.get("database_id"))
            breadcrumb_parts.append(_database_title(db))
            break
        else:
            # workspace, block_id (rare for page), or unknown → stop
            break

    # We collected from child upward; reverse to get root → leaf
    breadcrumb_parts = list(reversed(breadcrumb_parts))
    delim = f" {delimiter} " if delimiter else "/"

    breadcrumb = delim.join(part for part in breadcrumb_parts if part)

    block_text = None
    # ---------- fetch block text ----------
    if block_id:
        try:
            block = client.blocks.retrieve(block_id=block_id)
            block_text = _block_text(block).strip()
        except:
            pass

    # ---------- final string ----------
    if breadcrumb and block_text:
        return f"{breadcrumb}{delim}{block_text}"
    elif breadcrumb:
        return breadcrumb
    else:
        return block_text
