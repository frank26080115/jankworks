from typing import Dict, List, Optional
from datetime import datetime
import pickle
import myutils
import os

CACHE_DIR = "cache"

class NotionPageCache(object):
    def __init__(self, uuid:str, dt:datetime, data:Dict[str, str] = {}, children:List[str] = []):
        self.uuid = myutils.extract_uuids(uuid)[0]
        self.dt = dt
        self.chunks = data
        self.child_pages = children

    def save(self):
        make_cache_dir()
        with open(os.path.join(CACHE_DIR, myutils.shorten_id(self.uuid).lower() + ".pkl"), "wb") as f:
            pickle.dump(self, f)

def make_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)

def load_page_cache(page_id):
    fn = myutils.shorten_id(myutils.extract_uuids(page_id)[0]).lower() + ".pkl"
    fp = os.path.join(CACHE_DIR, fn)
    if os.path.exists(fp):
        with open(fp, 'rb') as f:
            return pickle.load(f)
    return None

class NotionTextChunk(object):
    def __init__(self, page_id:str, block_id:str, text:str, score:float = 0):
        self.page_id = myutils.shorten_id(page_id)
        self.block_id = myutils.shorten_id(block_id)
        self.text = text
        self.score = score

    def get_url(self):
        tail = "" if not self.block_id else f"#{self.block_id}"
        return f"https://www.notion.so/{self.page_id}" + tail

    def is_eof(self):
        return self.page_id.lower() == "eof" and self.block_id.lower() == "eof"
