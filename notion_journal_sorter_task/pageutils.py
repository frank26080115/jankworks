from notion_client import Client
from typing import Dict
from notion_authtoken_reader import AuthTokenFileReader
import re
from logger_setup import logger
import myutils
import os, time
import pickle

def get_all_accessible_pages(token: str, print_dots: bool = False) -> Dict[str, str]:
    if print_dots:
        print("scanning all pages ...", end="", flush=True)
    notion = Client(auth=token)
    visited = {}

    def extract_title(page_obj):
        props = page_obj.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                text_items = prop.get("title", [])
                return "".join(t["text"]["content"] for t in text_items if t["type"] == "text")
        return "(Untitled Page)"

    def traverse_blocks(block_id):
        try:
            children = []
            start_cursor = None
            while True:
                response = notion.blocks.children.list(block_id=block_id, start_cursor=start_cursor)
                if print_dots:
                    print(".", end="", flush=True)
                children.extend(response["results"])
                if not response.get("has_more"):
                    break
                start_cursor = response["next_cursor"]

            for block in children:
                if block["type"] == "child_page":
                    page_id = block["id"]
                    title = block["child_page"]["title"]
                    visited[page_id] = title
                    print(",", end="", flush=True)
                    traverse_blocks(page_id)
                elif block["type"] == "child_database":
                    db_id = block["id"]
                    db = notion.databases.retrieve(db_id)
                    visited[db_id] = db.get("title", [{"type": "text", "text": {"content": "(Untitled DB)"}}])[0]["text"]["content"]
                    print("@", end="", flush=True)
                    # Optionally query the database here
                elif block.get("has_children"):
                    traverse_blocks(block["id"])
        except Exception as e:
            print(f"Failed to fetch children of block {block_id}: {e}")

    # Start with all top-level accessible pages via /search
    start_cursor = None
    while True:
        response = notion.search(start_cursor=start_cursor)
        results = response["results"]
        for result in results:
            if result["object"] == "page":
                page_id = result["id"]
                title = extract_title(result)
                visited[page_id] = title
                traverse_blocks(page_id)
        if not response.get("has_more"):
            break
        start_cursor = response["next_cursor"]

    if print_dots:
        print(" ✓ done")

    return visited

def get_all_accessible_page_paths(token: str, print_dots: bool = False) -> Dict[str, str]:
    """
    Returns a dictionary mapping page_id to full hierarchical path using ' / ' as delimiter.
    """
    notion = Client(auth=token)
    path_map = {}

    def build_path(page_id: str, title: str, parent_path: str | None) -> str:
        if parent_path:
            return f"{parent_path} / {title}"
        else:
            return title

    def traverse_blocks(block_id: str, parent_path: str | None = None):
        try:
            children = []
            start_cursor = None
            while True:
                response = notion.blocks.children.list(block_id=block_id, start_cursor=start_cursor)
                if print_dots:
                    print(".", end="", flush=True)
                children.extend(response["results"])
                if not response.get("has_more"):
                    break
                start_cursor = response["next_cursor"]

            for block in children:
                if block["type"] == "child_page":
                    page_id = block["id"]
                    title = block["child_page"]["title"]
                    full_path = build_path(page_id, title, parent_path)
                    path_map[page_id] = full_path
                    if print_dots:
                        print(",", end="", flush=True)
                    traverse_blocks(page_id, full_path)
                elif block["type"] == "child_database":
                    db_id = block["id"]
                    db = notion.databases.retrieve(db_id)
                    title = db.get("title", [{"type": "text", "text": {"content": "(Untitled DB)"}}])[0]["text"]["content"]
                    full_path = build_path(db_id, title, parent_path)
                    path_map[db_id] = full_path
                    if print_dots:
                        print("@", end="", flush=True)
                elif block.get("has_children"):
                    traverse_blocks(block["id"], parent_path)
        except Exception as e:
            print(f"Failed to fetch children of block {block_id}: {e}")

    # Start traversal from root accessible pages
    start_cursor = None
    while True:
        response = notion.search(start_cursor=start_cursor)
        for result in response["results"]:
            if result["object"] == "page":
                page_id = result["id"]
                title = next(
                    ("".join(t["text"]["content"] for t in prop["title"])
                     for prop in result.get("properties", {}).values()
                     if prop.get("type") == "title"),
                    "(Untitled Page)"
                )
                path_map[page_id] = title
                traverse_blocks(page_id, title)
        if not response.get("has_more"):
            break
        start_cursor = response["next_cursor"]

    if print_dots:
        print(" ✓ done")

    return path_map

CACHE_LIFESPAN_SECONDS = 2 * 24 * 60 * 60  # 2 days

def load_or_refresh_pages_cache(token: str, paths: bool = False, print_dots: bool = False) -> Dict[str, str]:
    """
    Load UID → title dictionary from a pickle cache file, or regenerate it if:
    - The file doesn't exist
    - The file is older than 2 days
    """
    def is_cache_fresh(path: str) -> bool:
        if not os.path.exists(path):
            return False
        mtime = os.path.getmtime(path)
        age = time.time() - mtime
        return age < CACHE_LIFESPAN_SECONDS

    CACHE_DIR = "cache"
    os.makedirs(CACHE_DIR, exist_ok=True)

    cache_file = "pages_cache.pkl" if not paths else "pages_paths_cache.pkl"
    cache_path = os.path.join(CACHE_DIR, cache_file)

    if is_cache_fresh(cache_path):
        logger.info("✓ Loaded page list from cache.")
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    logger.info("🔄 Cache missing or expired. Refreshing with Notion API...")
    all_pages = get_all_accessible_pages(token, print_dots = print_dots)

    with open(cache_path, "wb") as f:
        pickle.dump(all_pages, f)

    logger.info("✓ Refreshed and saved page cache.")
    return all_pages

def extract_journal_identifiers(pages: Dict[str, str], token: str, print_dots: bool = False) -> Dict[str, str]:
    notion = Client(auth=token)
    results = {}

    for page_id, title in pages.items():
        if print_dots:
            print(".", end="", flush=True)
        if "journal" not in title.lower():
            continue

        try:
            # Fetch top-level blocks
            children = []
            start_cursor = None
            while True:
                response = notion.blocks.children.list(block_id=page_id, start_cursor=start_cursor)
                if print_dots:
                    print(",", end="", flush=True)
                children.extend(response["results"])
                if not response.get("has_more"):
                    break
                start_cursor = response["next_cursor"]

            # Find first heading_3 block
            for block in children:
                if block["type"] == "heading_3":
                    rich_text = block["heading_3"]["rich_text"]
                    heading_str = "".join(
                        t["text"]["content"]
                        for t in rich_text
                        if t["type"] == "text"
                    ).strip()
                    results[page_id] = heading_str
                    break  # Only first heading_3 needed
        except Exception as e:
            print(f"Error processing page {page_id}: {e}")

    return results

def filter_latest_parts(pages: Dict[str, str], tagged_pages: Dict[str, str]) -> Dict[str, str]:
    output = {}
    part_pages = []

    # Regular expression to capture "Part X" or "Pt. X" with optional spacing/case
    part_pattern = re.compile(r'\b(?:part|pt\.)\s*(\d+)', re.IGNORECASE)

    # Separate part pages and non-part pages
    for uid, tag in tagged_pages.items():
        title = pages.get(uid, "")
        match = part_pattern.search(title)
        if match:
            part_number = int(match.group(1))
            part_pages.append((tag.lower(), part_number, uid, tag))  # keep tag normalized
        else:
            output[uid] = tag  # keep all non-part pages

    # Group part pages by tag and keep only the one with the highest part number
    latest_parts = {}
    for tag, part_num, uid, original_tag in part_pages:
        if tag not in latest_parts or part_num > latest_parts[tag][0]:
            latest_parts[tag] = (part_num, uid, original_tag)

    # Add latest parts to output
    for _, uid, tag in latest_parts.values():
        output[uid] = tag

    return output

def filter_journal_pages_by_path(pages: dict[str, str]) -> dict[str, str]:
    """
    Given a dict of {page_id: path_title}, return a filtered dict
    where the final path segment includes the word 'journal' (case-insensitive).
    """
    result = {}
    for page_id, path in pages.items():
        final_segment = path.split(" / ")[-1].strip().lower()
        if "journal" in final_segment:
            result[page_id] = path
    return result

def get_block_text_or_type(block: dict) -> str:
    block_type = block.get("type")
    data = block.get(block_type, {})

    if block_type == "paragraph":
        rich_text = data.get("rich_text", [])
        if rich_text:
            x = myutils.get_rich_text_content(block)
            return x
        else:
            return "<empty paragraph>"

    # Generic fallback for any block with rich_text
    rich_text = data.get("rich_text", [])
    if rich_text:
        return "".join(
            t.get("text", {}).get("content", "")
            for t in rich_text
            if t.get("type") == "text"
        ).strip()

    return f"<{block_type}>"

def append_blocks_to_page(token: str, page_id: str, blocks: list[dict], eventlogger = None):
    """
    Appends a list of blocks to the bottom of a Notion page.

    Args:
        token (str): Notion integration token.
        page_id (str): The Notion page ID to append to.
        blocks (list[dict]): A list of valid Notion block objects (e.g. to_do blocks).
    """
    if not blocks:
        print("No blocks to append.")
        return

    notion = Client(auth=token)

    for b in blocks:
        if eventlogger is not None:
            eventlogger.log(f"TODO-TASK-INSERTED, {b["id"]}, {myutils.truncate_preview(get_block_text_or_type(b))}", dt = myutils.get_created_time_datetime(b))

    try:
        notion.blocks.children.append(
            block_id=page_id,
            children=blocks
        )
    except Exception as e:
        print(f"Error appending blocks: {e}")

def get_blocks_from_page(token: str, page_id):
    notion = Client(auth=token)
    blocks = []
    cursor = None

    while True:
        response = notion.blocks.children.list(block_id=page_id, start_cursor=cursor)
        blocks.extend(response["results"])
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return blocks

if __name__ == "__main__":
    print("testing Notion page traversal")
    tokenreader = AuthTokenFileReader()
    pages = get_all_accessible_pages(tokenreader.get_token())

    for pid, title in pages.items():
        print(f"\t{pid} : {title}")

    print("testing categorization extraction")
    j = extract_journal_identifiers(pages, tokenreader.get_token())
    for pid, tag in j.items():
        print(f"\t{pid} : {tag}")

    print("testing categorization filtering")
    j2 = filter_latest_parts(pages, j)
    for pid, tag in j2.items():
        print(f"\t{pid} : {tag}")
