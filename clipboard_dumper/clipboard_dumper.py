import win32clipboard
import win32con
import pprint

# Known standard formats
STANDARD_FORMATS = {
    win32con.CF_TEXT: "CF_TEXT",
    win32con.CF_BITMAP: "CF_BITMAP",
    win32con.CF_UNICODETEXT: "CF_UNICODETEXT",
    win32con.CF_DIB: "CF_DIB",
    win32con.CF_DIBV5: "CF_DIBV5",
    win32con.CF_HDROP: "CF_HDROP",
}

def get_format_name(fmt):
    # First check standard formats
    if fmt in STANDARD_FORMATS:
        return STANDARD_FORMATS[fmt]

    # Otherwise try to get registered name
    try:
        return win32clipboard.GetClipboardFormatName(fmt)
    except:
        return f"UNKNOWN_FORMAT_{fmt}"

def try_decode(data):
    if isinstance(data, bytes):
        for enc in ["utf-8", "utf-16", "latin-1"]:
            try:
                return data.decode(enc)
            except:
                continue
    return data

def inspect_clipboard():
    results = {}

    win32clipboard.OpenClipboard()
    try:
        fmt = 0
        while True:
            fmt = win32clipboard.EnumClipboardFormats(fmt)
            if fmt == 0:
                break

            name = get_format_name(fmt)

            try:
                data = win32clipboard.GetClipboardData(fmt)
            except Exception as e:
                data = f"<ERROR: {e}>"

            decoded = try_decode(data)

            results[name] = {
                "format_id": fmt,
                "type": str(type(data)),
                "preview": str(decoded)[:500],
                "raw_length": len(data) if hasattr(data, "__len__") else "N/A"
            }

    finally:
        win32clipboard.CloseClipboard()

    print("\n=== CLIPBOARD CONTENTS ===\n")
    pprint.pprint(results, width=120)

if __name__ == "__main__":
    inspect_clipboard()