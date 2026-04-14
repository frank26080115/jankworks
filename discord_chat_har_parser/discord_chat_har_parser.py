import json
import argparse
import base64
from datetime import datetime, timedelta
from pathlib import Path


class Message:
    def __init__(self, msg_id: str, username: str, timestamp: str, content: str):
        self.id = msg_id
        self.username = username
        self.timestamp_str = timestamp
        self.timestamp = self._parse_timestamp(timestamp)
        self.content = content

    def _parse_timestamp(self, ts: str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def to_dict(self):
        return {
            "username": self.username,
            "timestamp": self.timestamp_str,
            "content": self.content
        }

    def can_merge_with(self, other, max_delta=timedelta(hours=2)):
        return (
            self.username == other.username and
            self.id != other.id and  # prevent merging duplicates
            (other.timestamp - self.timestamp) <= max_delta
        )

    def merge(self, other):
        self.content += "\n\n" + other.content


def decode_response_text(content):
    text = content.get("text")
    encoding = content.get("encoding")

    if not text:
        return None

    if encoding == "base64":
        try:
            decoded_bytes = base64.b64decode(text)
            return decoded_bytes.decode("utf-8", errors="replace")
        except Exception:
            return None

    return text


def extract_messages_from_har(har_path):
    messages = []
    seen_ids = set()

    with open(har_path, "r", encoding="utf-8") as f:
        har = json.load(f)

    entries = har.get("log", {}).get("entries", [])

    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})

        method = request.get("method", "")
        url = request.get("url", "")

        if method != "GET" or "/messages?" not in url:
            continue

        content = response.get("content", {})
        mime_type = content.get("mimeType", "")

        if "application/json" not in mime_type:
            continue

        text = decode_response_text(content)
        if not text:
            continue

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue

        if not isinstance(data, list):
            continue

        for msg in data:
            msg_id = msg.get("id")
            if not msg_id or msg_id in seen_ids:
                continue

            content_text = msg.get("content", "").strip()
            timestamp = msg.get("timestamp")
            author = msg.get("author", {})
            username = author.get("username")

            if not content_text or not timestamp or not username:
                continue

            seen_ids.add(msg_id)
            messages.append(Message(msg_id, username, timestamp, content_text))

    return messages


def merge_messages(messages):
    if not messages:
        return []

    merged = []
    current = messages[0]

    for next_msg in messages[1:]:
        if current.can_merge_with(next_msg):
            current.merge(next_msg)
        else:
            merged.append(current)
            current = next_msg

    merged.append(current)
    return merged


def main():
    parser = argparse.ArgumentParser(description="Extract Discord messages from HAR file")
    parser.add_argument("har_file", help="Path to HAR file")
    parser.add_argument("--ai", action="store_true", help="Use AI filtering")

    args = parser.parse_args()

    input_path = Path(args.har_file)
    output_path = input_path.with_suffix(".json")

    print(f"📂 Loading HAR file: {input_path}")
    messages = extract_messages_from_har(input_path)

    print(f"🧹 Extracted {len(messages)} unique messages")

    # Sort by timestamp
    messages.sort(key=lambda m: m.timestamp)

    print("🔀 Merging messages...")
    merged_messages = merge_messages(messages)

    if args.ai:
        from ai_filter import filter_useful_messages
        print("Using AI for filtering...")
        merged_messages = filter_useful_messages(merged_messages, verbose=True)

    print(f"✨ Reduced to {len(merged_messages)} merged messages")

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([m.to_dict() for m in merged_messages], f, indent=2)

    print(f"💾 Output written to: {output_path}")


if __name__ == "__main__":
    main()
