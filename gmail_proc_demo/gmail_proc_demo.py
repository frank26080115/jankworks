import os, json, time, base64, re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from seen import SeenManager

# ---- Config ----
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]  # use gmail.modify if you want to add labels, mark read, etc.
POLL_SECONDS = 30
ONLY_INBOX = True
LOOKBACK_DAYS = 7  # limit to last week

def gmail_service():
    """Create an authenticated Gmail API client using OAuth on first run."""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            # Local web server flow—opens a browser on first run
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

def gmail_date_7d_query() -> str:
    """
    Build a Gmail search query constrained to last week.
    We combine:
      - in:inbox (optional)
      - newer_than:7d (server-side relative)
      - after:YYYY/MM/DD (explicit absolute date for extra safety)
    """
    today_local = datetime.now().date()
    after_date = (today_local - timedelta(days=LOOKBACK_DAYS)).strftime("%Y/%m/%d")
    parts = []
    if ONLY_INBOX:
        parts.append("in:inbox")
    parts.append("newer_than:7d")
    parts.append(f"after:{after_date}")
    # You can add extra filters here, e.g. -category:social, has:attachment, etc.
    return " ".join(parts)

def list_message_ids(svc, q: str, max_page=10) -> List[str]:
    """List message IDs that match query; handles pagination."""
    ids = []
    req = svc.users().messages().list(userId="me", q=q, maxResults=100)
    page_count = 0
    while req is not None and page_count < max_page:
        resp = req.execute()
        ids.extend([m["id"] for m in resp.get("messages", [])])
        req = svc.users().messages().list_next(previous_request=req, previous_response=resp)
        page_count += 1
    return ids

def get_full_message(svc, msg_id: str) -> Dict[str, Any]:
    return svc.users().messages().get(userId="me", id=msg_id, format="full").execute()

def header_map(msg: Dict[str, Any]) -> Dict[str, str]:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return headers

def decode_part_body(part: Dict[str, Any]) -> str:
    """Decode a single MIME part's body to UTF-8 text if present."""
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    raw = base64.urlsafe_b64decode(data.encode("utf-8"))
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode("latin-1", errors="replace")

def extract_text_content(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Pull out text/plain and text/html best-effort.
    """
    if not payload:
        return {"text": "", "html": ""}

    mime_type = payload.get("mimeType", "")
    if mime_type.startswith("text/"):
        body = decode_part_body(payload)
        return {"text": body if mime_type == "text/plain" else "", "html": body if mime_type == "text/html" else ""}

    text, html = "", ""
    parts = payload.get("parts", []) or []
    for p in parts:
        mt = p.get("mimeType", "")
        if mt == "text/plain" and not text:
            text = decode_part_body(p)
        elif mt == "text/html" and not html:
            html = decode_part_body(p)
        else:
            # Some messages nest parts under parts
            if "parts" in p:
                nested = extract_text_content(p)
                text = text or nested.get("text", "")
                html = html or nested.get("html", "")
    return {"text": text, "html": html}

def process_email(msg: Dict[str, Any]):
    """
    🔧 Your message handler.
    Add your business logic here: parse, route, save, call webhooks, etc.
    This demo just prints From/Subject and a short snippet.
    """
    h = header_map(msg)
    subject = h.get("subject", "(no subject)")
    sender = h.get("from", "(unknown)")
    date = h.get("date", "")
    content = extract_text_content(msg.get("payload", {}))
    snippet = (content.get("text") or msg.get("snippet") or "").strip().replace("\n", " ")
    if len(snippet) > 160:
        snippet = snippet[:157] + "..."
    print(f"📧  {subject}\n    From: {sender}\n    Date: {date}\n    {snippet}\n")

def main():
    svc = gmail_service()
    seen = SeenManager()
    seen.prune()
    seen.load()
    print("Gmail watcher running (last 7 days, INBOX). Ctrl+C to stop.\n")

    while True:
        try:
            query = gmail_date_7d_query()
            ids = list_message_ids(svc, query)
            # Deduplicate and preserve stable ordering
            new_ids = [mid for mid in ids if mid not in seen.get_set()]

            if new_ids:
                # Process newest first (optional: reverse)
                for mid in new_ids:
                    try:
                        msg = get_full_message(svc, mid)
                        process_email(msg)
                        seen.add(mid)
                    except HttpError as e:
                        # Rate limits or transient errors—log and keep going
                        print(f"⚠️  Error reading {mid}: {e}")
                seen.save()

        except KeyboardInterrupt:
            print("\nExiting by user request.")
            break
        except Exception as e:
            print(f"⚠️  Loop error: {e}")

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
