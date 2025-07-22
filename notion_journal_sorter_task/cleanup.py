from notion_client import Client
from datetime import datetime
from logger_setup import logger
import myutils
import pageutils
import os

def cleanup_master_journal(token: str, master_page_id: str):
    notion = Client(auth=token)

    # Fetch all top-level blocks
    all_blocks = []
    cursor = None
    while True:
        res = notion.blocks.children.list(master_page_id, start_cursor=cursor)
        all_blocks.extend(res["results"])
        if not res.get("has_more"):
            break
        cursor = res["next_cursor"]

    # Heading levels in cleanup order
    levels = [3, 2, 1]

    for level in levels:
        heading_key = f"heading_{level}"
        i = 0
        while i < len(all_blocks):
            block = all_blocks[i]
            if block["type"] == heading_key:
                current_heading = block
                heading_index = i
                heading_id = block["id"]

                # Find next heading of same or higher level
                j = i + 1
                while j < len(all_blocks):
                    next_block = all_blocks[j]
                    if next_block["type"].startswith("heading_"):
                        next_level = int(next_block["type"][-1])
                        if next_level <= level:
                            break
                    j += 1

                # Extract all blocks under this heading
                under_blocks = all_blocks[i + 1:j]

                has_real_content = myutils.has_real_content(under_blocks)

                if not has_real_content:
                    notion.blocks.delete(heading_id)
                    logger.info(f"🧹 Removed empty heading_{level}: {pageutils.get_block_text_or_type(current_heading)}")
                    # Remove from local list to keep index in sync
                    all_blocks.pop(i)
                    continue  # Stay at the same index
            i += 1

    # Check if last heading_1 is today
    heading_1_blocks = [b for b in all_blocks if b["type"] == "heading_1"]
    today_str = myutils.format_notion_date_heading(datetime.today())

    if heading_1_blocks:
        last_heading_text = pageutils.get_block_text_or_type(heading_1_blocks[-1]).strip()
        if myutils.parse_fuzzy_date(last_heading_text) != myutils.parse_fuzzy_date(today_str):
            logger.info(f"📌 Last heading_1 is outdated ({last_heading_text}), appending new one: {today_str}")
            notion.blocks.children.append(master_page_id, children=[
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": today_str}
                        }]
                    }
                }
            ])
        else:
            logger.info("📌 Master journal already ends with today’s heading_1.")
    else:
        logger.info("📌 No heading_1 found. Adding today’s heading.")
        notion.blocks.children.append(master_page_id, children=[
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": today_str}
                    }]
                }
            }
        ])

def detect_and_cleanup_blank_pages(token: str, uid_to_title: dict):
    notion = Client(auth=token)

    today_str = datetime.today().strftime("%Y-%m-%d")
    report_file = f"blank_pages_{today_str}.txt"
    blank_urls = []

    for page_id, title in uid_to_title.items():
        title_clean = title.strip().lower() if title else ""
        if not title_clean or title_clean == "new page":
            # Check page content
            try:
                blocks = []
                cursor = None
                while True:
                    res = notion.blocks.children.list(page_id, start_cursor=cursor)
                    blocks.extend(res["results"])
                    if not res.get("has_more"):
                        break
                    cursor = res["next_cursor"]

                is_empty = True
                for b in blocks:
                    if b.get("has_children"):
                        is_empty = False
                        break

                    data = b.get(b["type"], {})
                    text = data.get("rich_text", [])
                    if any(
                        t.get("type") == "text" and t.get("text", {}).get("content", "").strip()
                        for t in text
                    ):
                        is_empty = False
                        break

                if is_empty:
                    try:
                        notion.pages.update(page_id, archived=True)
                        print(f"🗑️ Archived empty page: {page_id} ({title!r})")
                    except Exception as e:
                        print(f"⚠️ Could not archive page {page_id}: {e}")
                        blank_urls.append(f"https://www.notion.so/{page_id.replace('-', '')}")

            except Exception as e:
                print(f"⚠️ Failed to check page {page_id}: {e}")
                blank_urls.append(f"https://www.notion.so/{page_id.replace('-', '')}")

    # Save report if needed
    if blank_urls:
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("\n".join(blank_urls))
        print(f"📄 Wrote report: {report_file}")
