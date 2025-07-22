from logger_setup import logger
from notion_client import Client
from notion_auth_token_reader import AuthTokenFileReader
from datetime import datetime
import pageutils
import myutils

def process_master_journal(master_page_id: str, uid_to_title: dict, uid_to_tag: dict, token: str):
    notion = Client(auth=token)

    start_cursor = None
    blocks = []
    while True:
        res = notion.blocks.children.list(master_page_id, start_cursor=start_cursor)
        blocks.extend(res["results"])
        if not res.get("has_more"):
            break
        start_cursor = res["next_cursor"]

    current_date = datetime.today()
    current_tag = "other"

    for block in blocks:
        try:
            block_type = block.get("type")
            block_id = block.get("id")
            block_txt = myutils.truncate_preview(pageutils.get_block_text_or_type(block))

            if block_type == "heading_1":
                heading_text = extract_text(block["heading_1"]["rich_text"])
                current_date = myutils.parse_fuzzy_date(heading_text)
                logger.info(f"Context date set to: {current_date.strftime('%Y-%m-%d')}")

            elif block_type == "heading_3":
                current_tag = extract_text(block["heading_3"]["rich_text"]).strip().lower()
                logger.info(f"Context tag set to: {current_tag}")

            elif block_type in {"child_page", "child_database"}:
                logger.debug(f"Ignoring block {block_id}, content: \"{block_txt}\"")
            else:
                # Route this block
                routed = route_block_to_journal(notion, block, current_tag, current_date, uid_to_title, uid_to_tag)
                if routed:
                    notion.blocks.delete(block_id)
                    print(f"✓ Routed and removed block {block_id}, content: \"{block_txt}\"")
                else:
                    logger.warning(f"Could not route block {block_id}, content: \"{block_txt}\"")
        except Exception as e:
            logger.error(f"Error processing block {block.get('id')}: {e!r}")

def extract_text(rich_text: list) -> str:
    return "".join(t["text"]["content"] for t in rich_text if t["type"] == "text")

def route_block_to_journal(notion, block, tag, date_obj, uid_to_title, uid_to_tag):
    block_type = block.get("type")
    block_id = block.get("id")
    block_txt = myutils.truncate_preview(pageutils.get_block_text_or_type(block))

    filtered = pageutils.filter_latest_parts(uid_to_title, uid_to_tag)
    uid, matched_tag = myutils.fuzzy_match_tag(tag, filtered)

    if not uid:
        logger.warning(f"No match found for tag '{tag}', block_id: '{block_id}', content: \"{block_txt}\"")
        return False

    date_heading = myutils.format_notion_date_heading(date_obj)

    # Fetch destination page content
    children = []
    start_cursor = None
    while True:
        res = notion.blocks.children.list(uid, start_cursor=start_cursor)
        children.extend(res["results"])
        if not res.get("has_more"):
            break
        start_cursor = res["next_cursor"]

    # Scan from bottom up for matching heading_1
    insert_under = None
    for b in reversed(children):
        if b["type"] == "heading_1":
            heading_text = extract_text(b["heading_1"]["rich_text"]).strip()
            if myutils.parse_fuzzy_date(heading_text) == myutils.parse_fuzzy_date(date_heading):
                insert_under = b["id"]
                break

    if not insert_under:
        # Insert new heading at end
        logger.info(f"Inserting new heading '{date_heading}' in {matched_tag}")
        res = notion.blocks.children.append(uid, children=[
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{
                        "type": "text",
                        "text": {
                            "content": date_heading
                        }
                    }]
                }
            }
        ])
        insert_under = res["results"][0]["id"]

    # Append the block under the heading
    c = clone_block_for_append(block)
    if c is not None:
        notion.blocks.children.append(uid, children=[c])
        logger.info(f"Routed block {block_id} under tag '{tag}' and date {date_obj}, content: \"{block_txt}\"")
        return True

    logger.info(f"Unable to routed block {block_id} under tag '{tag}', content: \"{block_txt}\"")
    return False

def clone_simple_block(block: dict) -> dict:
    block_type = block["type"]
    content = block.get(block_type, {})

    # Only handle basic text content blocks
    if "rich_text" in content:
        return {
            "object": "block",
            "type": block_type,
            block_type: {
                "rich_text": content["rich_text"]
            }
        }

    # Skip unsupported types or complex embeds
    return None

def clone_block_for_append(block: dict) -> dict | None:
    block_type = block.get("type")
    data = block.get(block_type, {})

    new_block = {
        "object": "block",
        "type": block_type
    }

    if block_type in {"paragraph", "heading_1", "heading_2", "heading_3",
                      "bulleted_list_item", "numbered_list_item",
                      "quote", "callout", "to_do"}:
        rich_text = data.get("rich_text", [])
        if not rich_text:
            return None
        new_block[block_type] = {
            "rich_text": rich_text,
        }
        # For to_do blocks, include checked state
        if block_type == "to_do":
            new_block[block_type]["checked"] = data.get("checked", False)
        # For callouts, include icon if present
        if block_type == "callout" and "icon" in data:
            new_block[block_type]["icon"] = data["icon"]
        return new_block

    elif block_type == "code":
        new_block["code"] = {
            "rich_text": data.get("rich_text", []),
            "language": data.get("language", "plain text")
        }
        return new_block

    elif block_type == "image":
        if "external" in data:
            new_block["image"] = {
                "type": "external",
                "external": {
                    "url": data["external"]["url"]
                }
            }
            return new_block
        elif "file" in data:
            new_block["image"] = {
                "type": "file",
                "file": {
                    "url": data["file"]["url"],
                    "expiry_time": data["file"]["expiry_time"]
                }
            }
            return new_block

    elif block_type == "bookmark":
        new_block["bookmark"] = {
            "url": data.get("url", "")
        }
        return new_block

    elif block_type == "embed":
        new_block["embed"] = {
            "url": data.get("url", "")
        }
        return new_block

    elif block_type == "divider":
        new_block["divider"] = {}
        return new_block

    elif block_type == "pdf":
        if "external" in data:
            new_block["pdf"] = {
                "type": "external",
                "external": {
                    "url": data["external"]["url"]
                }
            }
            return new_block
        elif "file" in data:
            new_block["pdf"] = {
                "type": "file",
                "file": {
                    "url": data["file"]["url"],
                    "expiry_time": data["file"]["expiry_time"]
                }
            }
            return new_block

    elif block_type == "video":
        if "external" in data:
            new_block["video"] = {
                "type": "external",
                "external": {
                    "url": data["external"]["url"]
                }
            }
            return new_block

    elif block_type == "equation":
        new_block["equation"] = {
            "expression": data.get("expression", "")
        }
        return new_block

    elif block_type == "synced_block":
        # You can’t recreate synced blocks directly, Notion blocks this
        logger.warning("Skipping synced_block (Notion API does not support creating them)")
        return None

    elif block_type == "child_page":
        # You can't recreate a child page via append — must use `pages.create`
        logger.warning("Skipping child_page (cannot insert via append)")
        return None

    elif block_type == "child_database":
        logger.warning("Skipping child_database (cannot insert via append)")
        return None

    else:
        logger.warning(f"Unhandled block type: {block_type}")
        return None

if __name__ == "__main__":
    print("starting master journal sorter")
    reader = AuthTokenFileReader()
    token = reader.get_token()

    uid_to_title = pageutils.load_or_refresh_pages_cache(token, print_dots = True)
    print("extracting journal tags ...", end="", flush=True)
    uid_to_tag = pageutils.extract_journal_identifiers(uid_to_title, token, print_dots = True)
    print(" ✓ done")

    # Master Journal ID from Notion URL:
    master_page_id = "238dfffdf25c80cd9edbd0c2636eb6bb"
    print("processing master journal ...")
    process_master_journal(master_page_id, uid_to_title, uid_to_tag, token)

    from cleanup import cleanup_master_journal
    cleanup_master_journal(token, master_page_id)

    from cleanup import detect_and_cleanup_blank_pages
    detect_and_cleanup_blank_pages(token, uid_to_title)
