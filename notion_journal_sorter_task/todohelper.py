from notion_client import Client
import re
import os
from datetime import datetime, timezone, timedelta
from logger_setup import logger
import myutils, pageutils

def extract_uuid_from_todo_url(todo_block: dict) -> str | None:
    """
    Extracts a Notion-style UUID (with dashes) from any URL in the rich_text of a to_do block.
    Returns the UUID in standard API format (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx), or None.
    """
    block_data = todo_block.get("to_do", {})
    rich_text = block_data.get("rich_text", [])

    for span in rich_text:
        link = span.get("text", {}).get("link", {})
        if link and "url" in link:
            url = link["url"]
            # Match 32-character hex UUIDs with or without dashes
            match = re.search(r'([a-fA-F0-9]{32})|([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})', url)
            if match:
                hex_str = match.group(1) or match.group(2).replace("-", "")
                # Format into UUID with dashes
                return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"

    return None

def get_todo_blocks(token: str, page_id: str) -> list[dict]:
    """
    Fetches the top-level blocks of a Notion page and returns only the to_do blocks.
    """
    notion = Client(auth=token)
    todos = []
    start_cursor = None

    while True:
        response = notion.blocks.children.list(block_id=page_id, start_cursor=start_cursor)
        blocks = response.get("results", [])
        todos.extend(block for block in blocks if block.get("type") == "to_do")
        if not response.get("has_more"):
            break
        start_cursor = response["next_cursor"]

    return todos

def create_todo_blocks_from_journal_paragraph(openai_client, block: dict, page_uuid: str, title_pathlike: str, prev_paragraph: str | None = None) -> list[dict]:
    """
    Given a Notion paragraph block from a journal page, generate a list of valid to_do blocks,
    each ending with a link back to the source paragraph and an embedded timestamp.
    """
    todos = extract_todos_from_paragraph(
        openai_client,
        title_pathlike=title_pathlike,
        paragraph_text=myutils.get_rich_text_content(block),
        prev_paragraph=prev_paragraph
    )

    if not todos:
        return []

    block_id = block["id"].replace("-", "")
    page_id_squashed = page_uuid.replace('-', '')
    url = f"https://www.notion.so/{page_id_squashed}#{block_id}"

    creation_date_str = block.get("created_time")
    if creation_date_str:
        creation_date = datetime.fromisoformat(creation_date_str.rstrip("Z"))
        days_since = (datetime.now() - creation_date).days
        date_stamp = creation_date.strftime("%Y-%m-%d")
        marker = f" [{days_since} days][{date_stamp}][link]"
    else:
        marker = f" [??][link]"

    todo_blocks = []

    for todo_text in todos:
        todo_block = {
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": todo_text + " "
                        }
                    },
                    {
                        "type": "text",
                        "text": {
                            "content": marker,
                            "link": {"url": url}
                        },
                        "annotations": {
                            "italic": True,
                            "color": "gray"
                        }
                    }
                ],
                "checked": False
            }
        }
        todo_blocks.append(todo_block)

    return todo_blocks

def parse_todo_metadata(block) -> tuple[str | None, str | None, str | None]:
    """
    Parses rich_text to extract the created date and (if applicable) the completed date.
    Returns (created_date, completed_date) as strings in YYYY-MM-DD format.
    """
    rich_text = block.get("rich_text", [])
    url = myutils.find_last_url_in_block(block)

    combined = "".join(span.get("text", {}).get("content", "") for span in rich_text)

    # First pattern: [Xd][YYYY-MM-DD]
    match_active = re.search(r"\[\d+d\]\[(\d{4}-\d{2}-\d{2})\]", combined)
    if match_active:
        return match_active.group(1), None, url

    # Second pattern: [□ YYYY-MM-DD ☑ YYYY-MM-DD]
    match_completed = re.search(r"\[□ (\d{4}-\d{2}-\d{2}) ☑ (\d{4}-\d{2}-\d{2})\]", combined)
    if match_completed:
        return match_completed.group(1), match_completed.group(2), url

    return None, None, url

def format_todo_marker(created_date: str, checked: bool = False, completed_date: str | None = None, url: str | None = None) -> dict:
    """
    Formats the end-of-line rich_text block that includes metadata and a link.
    """
    if checked and completed_date:
        marker = f"[□ {created_date} ☑ {completed_date}]"
    else:
        days_since = (datetime.now().date() - datetime.strptime(created_date, "%Y-%m-%d").date()).days
        marker = f"[{days_since}d][{created_date}]"

    if url is not None:
        marker += "[link]"

    data = {
        "type": "text",
        "text": {
            "content": marker,
            #"link": {"url": url} if url else None
        },
        "annotations": {
            "italic": True,
            "color": "gray"
        }
    }
    if url is not None:
        data["text"]["link"] = url
    return data

def update_todo_heading(notion: Client, page_id: str):
    """
    Updates the first block of the page to a heading_3 with current refresh date.
    """
    today = datetime.now().strftime("%b %d - %Y")
    new_header = {
        "heading_3": {
            "rich_text": [{
                "type": "text",
                "text": {"content": f"last refreshed {today}"}
            }]
        }
    }

    response = notion.blocks.children.list(block_id=page_id, page_size=1)
    if response["results"] and response["results"][0]["type"] == "heading_3":
        notion.blocks.update(block_id=response["results"][0]["id"], **new_header)

def process_todo_blocks(notion: Client, blocks: list[dict], tasks_already_completed: set | dict, delete_old_completed: bool = False, eventlogger = None, print_dots: bool = False):
    """
    Updates all to_do blocks based on whether they're checked or not.
    Optionally deletes completed tasks that are older than 7 days.
    """
    for block in blocks:
        if print_dots:
            print(".", end="", flush=True)
        if block.get("type") != "to_do":
            continue

        to_do = block["to_do"]
        checked = to_do.get("checked", False)
        rich_text = to_do.get("rich_text", [])
        block_id = block["id"]

        created_date, completed_date, link_url = parse_todo_metadata(block)
        if not created_date:
            continue  # malformed or missing tag

        parent_uuid = None
        if link_url is not None and "#" in link_url:
            parent_uuid = link_url.split('#', 1)[1].strip() or None

        if checked:
            if not completed_date:
                completed_date = myutils.get_last_edited_datetime(block)
            # if the last editied time field does not exist, fall back to using the current time
            if not completed_date:
                completed_date = datetime.now()

            completed_date = completed_date.date().isoformat()

            if delete_old_completed:
                age = (datetime.now().date() - datetime.strptime(completed_date, "%Y-%m-%d").date()).days
                if age > 7:
                    if eventlogger is not None:
                        eventlogger.log(f"TODO-TASK-DELETE, {block_id}, {myutils.truncate_preview(pageutils.get_block_text_or_type(block))}")
                    notion.blocks.delete(block_id)
                    continue

            dict_key = f"{block_id}" if parent_uuid is None else f"{parent_uuid}#{block_id}"
            if block_id not in tasks_already_completed:
                if parent_uuid is not None:
                    mark_block_with_check(notion, parent_uuid)
                if eventlogger is not None:
                    eventlogger.log(f"TODO-TASK-DONE, {block_id}, {myutils.truncate_preview(pageutils.get_block_text_or_type(block))}", dt = completed_date)
                if isinstance(tasks_already_completed, set):
                    tasks_already_completed.add(dict_key)
                elif isinstance(tasks_already_completed, dict):
                    tasks_already_completed[dict_key] = myutils.get_created_time_datetime(block)

        # Replace trailing metadata span with updated version
        new_marker_span = format_todo_marker(
            created_date=created_date,
            checked=checked,
            completed_date=completed_date,
            url=link_url
        )
        updated_rich_text = rich_text[:-1] + [new_marker_span]

        notion.blocks.update(
            block_id=block_id,
            to_do={
                "rich_text": updated_rich_text,
                "checked": checked
            }
        )

def update_todo_page(token: str, page_id: str, tasks_already_completed: set | dict, delete_old_completed: bool = False, eventlogger = None, print_dots: bool = False):
    """
    Updates heading + all to_do blocks in a page.
    Optionally deletes completed items older than 7 days.
    """
    notion = Client(auth=token)
    update_todo_heading(notion, page_id)

    # Get all blocks
    blocks = []
    cursor = None
    while True:
        if print_dots:
            print(",", end="", flush=True)
        resp = notion.blocks.children.list(block_id=page_id, start_cursor=cursor)
        blocks.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    # Skip heading block
    todo_blocks = blocks[1:] if blocks and blocks[0]["type"] == "heading_3" else blocks
    process_todo_blocks(notion, todo_blocks, tasks_already_completed, delete_old_completed=delete_old_completed, eventlogger = eventlogger, print_dots = print_dots)

def extract_todos_from_paragraph(client, title_pathlike: str, paragraph_text: str, prev_paragraph: str | None) -> list[str]:
    """
    Extract one or more TODO items from a paragraph, using prior paragraph for context only.

    Returns a list of one-sentence actionable strings, or an empty list if nothing found.
    """
    system_prompt = (
        "You are a helpful assistant extracting actionable TODO items from journal entries.\n"
        "You will be given a journal path (like a folder structure), the current paragraph, "
        "and the previous paragraph.\n\n"
        "Your task is to extract all actionable TODOs **only from the current paragraph**. "
        "Use the previous paragraph only for context or clarification.\n"
        "If the item has hints that the TODO is completed (such as strikethrough formatting, the word DONE or FINISHED being emphasized, etc), then ignore the item.\n"
        "Each TODO output should be a clear, one-sentence item written in the imperative or future tense, with an appropriate (and short) context hint using the journal path.\n"
        "Return them as a numbered or bulleted list. If there are no TODOs, reply with 'NONE'."
    )

    user_prompt = f"""\
Journal Path: {title_pathlike}

Previous Paragraph:
{prev_paragraph or "(none)"}

Current Paragraph:
{paragraph_text}
"""

    try:
        response = client.ChatCompletion.create(
            model="gpt-4o",  # or "gpt-3.5-turbo"
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
        )

        content = response.choices[0].message.content.strip()

        if content.upper() == "NONE" or not content:
            return []

        # Extract lines that look like list items
        todos = []
        for line in content.splitlines():
            line = line.strip("-•* \t1234567890.)")  # Strip common list indicators
            if line:
                todos.append(line)

        return todos

    except Exception as e:
        logger.error(f"Error during OpenAI call: {e}")
        return []

def mark_block_with_check(notion: Client, block_id: str):
    # Fetch the block
    block = notion.blocks.retrieve(block_id)
    if block.get("type") != "paragraph":
        print("This function currently only supports paragraph blocks with rich_text.")
        return

    rich_text = block["paragraph"].get("rich_text", [])
    if not rich_text:
        print("Block has no rich_text to modify.")
        return

    # Get the text content from all segments
    full_text = ''.join([rt.get("plain_text", "") for rt in rich_text])

    checkmarks = {'✅', '☑️', '✔️', '✓', '🗸'} # Set of acceptable checkmark characters

    if full_text and full_text.strip()[-1] in checkmarks:
        print("Checkmark already present. No changes made.")
        return

    # Append robot + checkmark
    new_text = full_text + " 🤖✅"

    # Rebuild the rich_text array (simple single segment update)
    new_rich_text = [{
        "type": "text",
        "text": {
            "content": new_text
        }
    }]

    # Update the block
    notion.blocks.update(block_id, paragraph={"rich_text": new_rich_text})
    print("Block updated with 🤖✅")

def filter_recent_notion_blocks(token: str, data: set | dict, max_age_months: int = 3):
    notion = Client(auth=token)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30 * max_age_months)

    if isinstance(data, set):
        result = set()

        for entry in data:
            try:
                first_uuid = entry.split('#')[0].strip()
                block = notion.blocks.retrieve(first_uuid)
                created_time_str = block.get('created_time')
                if not created_time_str:
                    continue  # no creation time, drop it

                created_time = datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
                if created_time > cutoff:
                    result.add(entry)
            except Exception:
                # On any failure, drop the entry silently
                continue

        return result
    elif isinstance(data, dict):
        result = dict()

        for k, v in data.items():
            if v is not None:
                if v > cutoff:
                    result[k] = v
                continue
            try:
                first_uuid = k.split('#')[0].strip()
                block = notion.blocks.retrieve(first_uuid)
                created_time = myutils.get_created_time_datetime(block)
                if created_time is not None:
                    if created_time > cutoff:
                        result[k] = created_time
            except Exception:
                # On any failure, drop the entry silently
                continue
        return result
    raise TypeError("input must be a Python set or dict")
