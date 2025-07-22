from notion_client import Client
from typing import Dict
from notion_auth_token_reader import AuthTokenFileReader
import re
from logger_setup import logger

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

import os
import pickle
import time
from typing import Dict

CACHE_FILE = "pages_cache.pkl"
CACHE_LIFESPAN_SECONDS = 2 * 24 * 60 * 60  # 2 days

def load_or_refresh_pages_cache(token: str, print_dots: bool = False) -> Dict[str, str]:
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

    if is_cache_fresh(CACHE_FILE):
        logger.info("✓ Loaded page list from cache.")
        with open(CACHE_FILE, "rb") as f:
            return pickle.load(f)

    logger.info("🔄 Cache missing or expired. Refreshing with Notion API...")
    pages = get_all_accessible_pages(token, print_dots = print_dots)

    with open(CACHE_FILE, "wb") as f:
        pickle.dump(pages, f)

    logger.info("✓ Refreshed and saved page cache.")
    return pages

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

def get_block_text_or_type(block: dict) -> str:
    block_type = block.get("type")
    data = block.get(block_type, {})

    if block_type == "paragraph":
        rich_text = data.get("rich_text", [])
        if rich_text:
            return "".join(
                t.get("text", {}).get("content", "")
                for t in rich_text
                if t.get("type") == "text"
            ).strip()
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
