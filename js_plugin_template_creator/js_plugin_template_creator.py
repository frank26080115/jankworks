#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import shutil
from pathlib import Path

from rcssmin import cssmin
from rjsmin import jsmin


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minify JS/CSS assets, emit debug files, and generate plugin_template.js"
    )
    parser.add_argument(
        "directory",
        help="Directory to scan for .js and .css files",
    )
    return parser.parse_args()


def find_assets(root: Path, output_dir: Path) -> tuple[list[Path], list[Path]]:
    js_files: list[Path] = []
    css_files: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        # Skip anything inside the output workspace
        try:
            path.relative_to(output_dir)
            continue
        except ValueError:
            pass

        suffix = path.suffix.lower()
        if suffix == ".js":
            js_files.append(path)
        elif suffix == ".css":
            css_files.append(path)

    js_files.sort(key=lambda p: str(p.relative_to(root)).lower())
    css_files.sort(key=lambda p: str(p.relative_to(root)).lower())
    return js_files, css_files


def minify_text(text: str, suffix: str) -> str:
    if suffix == ".js":
        return jsmin(text)
    if suffix == ".css":
        return cssmin(text)
    raise ValueError(f"Unsupported suffix: {suffix}")


def encode_base64_utf8(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def make_debug_output_path(output_dir: Path, root: Path, source_path: Path) -> Path:
    rel = source_path.relative_to(root)
    return output_dir / rel


def comment_for_suffix(suffix: str) -> str:
    if suffix == ".js":
        return "//"
    if suffix == ".css":
        return "/*"
    raise ValueError(f"Unsupported suffix: {suffix}")


def comment_close_for_suffix(suffix: str) -> str:
    if suffix == ".js":
        return ""
    if suffix == ".css":
        return " */"
    raise ValueError(f"Unsupported suffix: {suffix}")


def write_debug_file(debug_path: Path, minified: str, encoded: str, suffix: str) -> None:
    debug_path.parent.mkdir(parents=True, exist_ok=True)

    if suffix == ".js":
        debug_text = f"{minified}\n// BASE64: {encoded}\n"
    elif suffix == ".css":
        debug_text = f"{minified}\n/* BASE64: {encoded} */\n"
    else:
        raise ValueError(f"Unsupported suffix: {suffix}")

    debug_path.write_text(debug_text, encoding="utf-8", newline="\n")


def js_string_literal(s: str) -> str:
    # Base64 is ASCII-safe, but this keeps escaping robust if requirements change later.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_plugin_template(
    root: Path,
    js_files: list[Path],
    css_files: list[Path],
    encoded_by_path: dict[Path, str],
) -> str:
    lines: list[str] = []

    lines.append("function __plugin_b64_to_text(b64){const bin=atob(b64);const bytes=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);return new TextDecoder().decode(bytes);}")
    lines.append("function plugin_load_assets(){")

    for path in js_files:
        rel = path.relative_to(root).as_posix()
        encoded = encoded_by_path[path]
        lines.append(
            f'    eval(__plugin_b64_to_text({js_string_literal(encoded)})); // {rel}'
        )

    for path in css_files:
        rel = path.relative_to(root).as_posix()
        encoded = encoded_by_path[path]
        lines.append(
            f'    (()=>{{const s=document.createElement("style");s.textContent=__plugin_b64_to_text({js_string_literal(encoded)});document.head.appendChild(s);}})(); // {rel}'
        )

    lines.append("}")
    lines.append("")
    lines.append("function elrs_plugin_init(){")
    lines.append("    plugin_load_assets();")
    lines.append("}")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    root = Path(args.directory).expanduser().resolve()

    if not root.exists():
        raise SystemExit(f"Directory does not exist: {root}")
    if not root.is_dir():
        raise SystemExit(f"Path is not a directory: {root}")

    output_dir = root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    js_files, css_files = find_assets(root, output_dir)
    all_files = js_files + css_files

    encoded_by_path: dict[Path, str] = {}

    for source_path in all_files:
        original = source_path.read_text(encoding="utf-8")
        minified = minify_text(original, source_path.suffix.lower())
        encoded = encode_base64_utf8(minified)
        encoded_by_path[source_path] = encoded

        debug_path = make_debug_output_path(output_dir, root, source_path)
        write_debug_file(debug_path, minified, encoded, source_path.suffix.lower())

    plugin_template = build_plugin_template(root, js_files, css_files, encoded_by_path)
    (output_dir / "plugin_template.js").write_text(plugin_template, encoding="utf-8", newline="\n")

    print(f"Scanned: {root}")
    print(f"Output:  {output_dir}")
    print(f"JS files:  {len(js_files)}")
    print(f"CSS files: {len(css_files)}")
    print(f"Wrote: {output_dir / 'plugin_template.js'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
