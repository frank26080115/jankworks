import os, time
import pickle
from datetime import datetime, timedelta

from notion_client import Client

from notion_authtoken_reader import AuthTokenFileReader
from openai_credloader import OpenAICredentialsLoader

import pageutils, myutils, todohelper

from simplelog import SimpleLog
from logger_setup import logger

# Constants
CACHE_DIR = "cache"
BLOCKS_PARSED_FILE = "blocks_already_parsed.pkl"
TASKS_COMPLETED_FILE = "tasks_already_completed.pkl"
MASTER_TODO_PAGE_URL = "https://www.notion.so/Daily-TODOs-Report-23bdfffdf25c8069b411c7b7531bb37c"
MASTER_TODO_PAGE_ID = MASTER_TODO_PAGE_URL.split("-")[-1]

def main():
    logger.info("Running TODO Extractor")

    # Load credentials
    notion_token = AuthTokenFileReader().get_token()
    openai_apikey = OpenAICredentialsLoader().get_api_key()
    os.environ["OPENAI_API_KEY"] = openai_apikey
    from openai import OpenAI, OpenAIError
    openai_client = OpenAI()

    # a different rotating logger simply tracks when todo-tasks are created and when todo-tasks are completed
    simplelogger = SimpleLog("notion_todo_extractor_log", logger, "logs")

    os.makedirs(CACHE_DIR, exist_ok=True)
    blocks_already_parsed   = myutils.load_cache_dict(os.path.join(CACHE_DIR, BLOCKS_PARSED_FILE))    # prevent repeated processing by AI, saving token usage
    tasks_already_completed = myutils.load_cache_dict(os.path.join(CACHE_DIR, TASKS_COMPLETED_FILE))  # track if an item was previously unfinished, so when it's marked as finished, an event can be generated
    blocks_already_parsed = todohelper.filter_recent_notion_blocks(notion_token, blocks_already_parsed)

    # Load page info, this will use the cache if available, refresh the cache if it is too old
    uid_to_title = pageutils.load_or_refresh_pages_cache(notion_token, paths=True, print_dots=True)

    # Update existing TODOs
    print("Updating the master TODO page...", end="", flush=True)
    todohelper.update_todo_page(notion_token, MASTER_TODO_PAGE_ID, tasks_already_completed, delete_old_completed=True, eventlogger = simplelogger, print_dots = True)
    tasks_already_completed = todohelper.filter_recent_notion_blocks(notion_token, tasks_already_completed)
    with open(os.path.join(CACHE_DIR, TASKS_COMPLETED_FILE), 'wb') as f:
        pickle.dump(tasks_already_completed, f)
    print(" done!")

    print("Performing TODO extraction and generation...", end="", flush=True)

    # Iterate and extract TODOs
    for page_id, title_pathlike in uid_to_title.items():
        bot_enabled = True

        # obviously don't process the page that is the master TODO page, it would make a duplicate of itself
        if myutils.uuids_equal(page_id, MASTER_TODO_PAGE_URL):
            continue

        try:
            blocks = pageutils.get_blocks_from_page(notion_token, page_id)
            print(",", end="", flush=True)
            prev_paragraph = ""
            for i, block in enumerate(blocks):
                if 'paragraph' in block or 'bulleted_list_item' in block or 'numbered_list_item' in block or 'to_do' in block:
                    block_id = block['id']

                    # only if we have not already processed this item already, save on token usage
                    if block_id in blocks_already_parsed:
                        continue

                    # only use items that are within 2 months of today
                    if not myutils.is_recent_block(block):
                        continue

                    # summarizes into a single string from a multi-part rich_text
                    paragraph_text = myutils.get_rich_text_content(block)

                    # content wayyyy too short to care about
                    if len(paragraph_text) <= 10:
                        continue

                    # there are meta instructions for bots inside the Notion, sometimes I don't want a page to be parsed at all, or I want a part of a page to be ignored
                    if "!bot-disable" in paragraph_text:
                        bot_enabled = False
                    if "!bot-enable" in paragraph_text:
                        bot_enabled = True
                    if not bot_enabled:
                        continue

                    # if an actual Notion-todo block is encountered, then prepend the input to the AI with TODO to make sure it actually considers it a TODO item.
                    if 'to_do' in block:
                        paragraph_text = "TODO: " + paragraph_text
                        # ignore the item if it is marked as done
                        is_checked = block['to_do'].get('checked', False)
                        if is_checked:
                            continue
                    elif "TODO" in paragraph_text: # not a TODO item, but I wrote "TODO" in there... see if other automation tools added a checkmark at the end
                        checkmarks = {'✅', '☑️', '✔️', '✓', '🗸'} # Set of acceptable checkmark characters
                        if paragraph_text[-1] in checkmarks:
                            continue

                    print(".", end="", flush=True)

                    try:
                        todo_blocks = todohelper.create_todo_blocks_from_journal_paragraph(openai_client, block, page_id, title_pathlike, prev_paragraph)
                        if todo_blocks:
                            pageutils.append_blocks_to_page(notion_token, MASTER_TODO_PAGE_ID, todo_blocks, eventlogger = simplelogger)
                        # mark as already processed so we don't waste tokens redoing it
                        blocks_already_parsed[block_id] = myutils.get_created_time_datetime(block)
                        with open(os.path.join(CACHE_DIR, BLOCKS_PARSED_FILE), 'wb') as f:
                            pickle.dump(blocks_already_parsed, f)
                    except OpenAIError as e:
                        logger.error(f"Error from OpenAI API: {e}")

                    # remember the previous paragraph only if we are not inside of a list, otherwise, we need the paragraph before the whole list, not just the previous list item
                    if 'paragraph' in block:
                        prev_paragraph = paragraph_text

                    time.sleep(1.33) # this is 80% of maximum allowed rate

        except Exception as e:
            logger.exception(f"Failed processing page {title_pathlike} ({page_id}): {e}")

    print(" done!")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception(f"Fatal unhandled exception: {e}")
        import traceback
        traceback.print_exc()
