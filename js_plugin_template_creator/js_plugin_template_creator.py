#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import mimetypes
import re
from pathlib import Path
from urllib.parse import quote

import minify_html
try:
    from PIL import Image
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'Pillow'. Install it with: pip install pillow"
    ) from exc
from rcssmin import cssmin
from rjsmin import jsmin

DATA_URL_EXTENSIONS = [
    ".aac",
    ".apng",
    ".avif",
    ".bmp",
#    ".css",
    ".csv",
    ".cur",
    ".eot",
    ".flac",
    ".gif",
#    ".htm",
#    ".html",
    ".ico",
    ".jpeg",
    ".jpg",
#    ".js",
    ".json",
    ".m4a",
    ".m4v",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".ogv",
    ".opus",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".svgz",
    ".ttf",
#    ".txt",
    ".wasm",
    ".wav",
    ".weba",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
#    ".xml",
]

DATA_URL_MIME_OVERRIDES = {
    ".css": "text/css",
    ".csv": "text/csv",
    ".htm": "text/html",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".m4a": "audio/mp4",
    ".m4v": "video/mp4",
    ".svg": "image/svg+xml",
    ".svgz": "image/svg+xml",
    ".txt": "text/plain",
    ".wasm": "application/wasm",
    ".xml": "application/xml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minify JS/CSS/HTML assets, emit debug files, and generate plugin_template.js"
    )
    parser.add_argument(
        "directory",
        help="Directory to scan for .js, .css, .html/.htm, and data URL asset files",
    )
    return parser.parse_args()


def find_assets(
    root: Path,
    output_dir: Path,
) -> tuple[list[Path], list[Path], list[Path], list[Path], list[Path]]:
    cfg_js_files: list[Path] = []
    js_files: list[Path] = []
    css_files: list[Path] = []
    html_files: list[Path] = []
    dataurl_files: list[Path] = []

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
        if path.name.lower().endswith(".cfg.js"):
            cfg_js_files.append(path)
        elif suffix == ".js":
            js_files.append(path)
        elif suffix == ".css":
            css_files.append(path)
        elif suffix in {".htm", ".html"}:
            html_files.append(path)

        if suffix in DATA_URL_EXTENSIONS:
            dataurl_files.append(path)

    cfg_js_files.sort(key=lambda p: str(p.relative_to(root)).lower())
    js_files.sort(key=lambda p: str(p.relative_to(root)).lower())
    css_files.sort(key=lambda p: str(p.relative_to(root)).lower())
    html_files.sort(key=lambda p: str(p.relative_to(root)).lower())
    dataurl_files.sort(key=lambda p: str(p.relative_to(root)).lower())
    return cfg_js_files, js_files, css_files, html_files, dataurl_files


def minify_text(text: str, suffix: str) -> str:
    if suffix == ".js":
        return jsmin(text)
    if suffix == ".css":
        return cssmin(text)
    if suffix in {".htm", ".html"}:
        return minify_html.minify(text)
    raise ValueError(f"Unsupported suffix: {suffix}")


def encode_base64_utf8(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def make_debug_output_path(output_dir: Path, root: Path, source_path: Path) -> Path:
    rel = source_path.relative_to(root)
    return output_dir / rel


def write_debug_file(debug_path: Path, minified: str, encoded: str, suffix: str) -> None:
    debug_path.parent.mkdir(parents=True, exist_ok=True)

    if suffix == ".js":
        debug_text = f"{minified}\n// BASE64: {encoded}\n"
    elif suffix == ".css":
        debug_text = f"{minified}\n/* BASE64: {encoded} */\n"
    elif suffix in {".htm", ".html"}:
        debug_text = f"{minified}\n<!-- BASE64: {encoded} -->\n"
    else:
        raise ValueError(f"Unsupported suffix: {suffix}")

    debug_path.write_text(debug_text, encoding="utf-8", newline="\n")


def js_string_literal(s: str) -> str:
    # Base64 is ASCII-safe, but this keeps escaping robust if requirements change later.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sanitize_js_suffix(name: str) -> str:
    suffix = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
    return suffix or "file"


def build_dataurl_variable_names(paths: list[Path]) -> dict[Path, str]:
    names: dict[Path, str] = {}
    counts: dict[str, int] = {}

    for path in paths:
        base_name = f"filedataurl_{sanitize_js_suffix(path.name)}"
        count = counts.get(base_name, 0) + 1
        counts[base_name] = count
        names[path] = base_name if count == 1 else f"{base_name}_{count}"

    return names


def guess_data_url_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in DATA_URL_MIME_OVERRIDES:
        return DATA_URL_MIME_OVERRIDES[suffix]

    mime_type, _ = mimetypes.guess_type(path.name, strict=False)
    return mime_type or "application/octet-stream"


def encode_base64_bytes(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def minify_svg_text(svg_text: str) -> str:
    try:
        from scour import scour
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency 'scour'. Install it with: pip install scour"
        ) from exc

    return scour.scourString(svg_text)


def write_minified_svg_copy(source_path: Path, output_dir: Path, root: Path) -> Path:
    minified_path = make_debug_output_path(output_dir, root, source_path)
    minified_path.parent.mkdir(parents=True, exist_ok=True)
    minified_svg = minify_svg_text(source_path.read_text(encoding="utf-8"))
    minified_path.write_text(minified_svg, encoding="utf-8", newline="\n")
    return minified_path


def build_svg_data_url(path: Path) -> str:
    encoded_svg = quote(path.read_text(encoding="utf-8"), safe="")
    return f"data:image/svg+xml,{encoded_svg}"


def write_optimized_image_copy(source_path: Path, output_dir: Path, root: Path) -> Path:
    optimized_path = make_debug_output_path(output_dir, root, source_path)
    optimized_path.parent.mkdir(parents=True, exist_ok=True)

    suffix = source_path.suffix.lower()
    with Image.open(source_path) as image:
        if suffix == ".png":
            image.save(optimized_path, format="PNG", optimize=True)
        elif suffix in {".jpg", ".jpeg"}:
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(optimized_path, format="JPEG", quality=50, optimize=True)
        else:
            raise ValueError(f"Unsupported image suffix: {suffix}")

    return optimized_path


def build_data_url(path: Path) -> str:
    if path.suffix.lower() == ".svg":
        return build_svg_data_url(path)

    mime_type = guess_data_url_mime_type(path)
    encoded = encode_base64_bytes(path.read_bytes())
    return f"data:{mime_type};base64,{encoded}"


def build_plugin_template(
    root: Path,
    cfg_js_files: list[Path],
    js_files: list[Path],
    css_files: list[Path],
    html_files: list[Path],
    encoded_by_path: dict[Path, str],
    dataurl_files: list[Path],
    dataurl_by_path: dict[Path, str],
) -> str:
    lines: list[str] = []

    cfg_js_files.sort(key=lambda path: path.name)
    for path in cfg_js_files:
        rel = path.relative_to(root).as_posix()
        if len(cfg_js_files) > 1:
            lines.append(f"// {rel}")
        lines.extend(path.read_text(encoding="utf-8").splitlines())
        lines.append("")

    dataurl_variable_names = build_dataurl_variable_names(dataurl_files)

    for path in dataurl_files:
        rel = path.relative_to(root).as_posix()
        variable_name = dataurl_variable_names[path]
        data_url = dataurl_by_path[path]
        lines.append(
            f"const {variable_name}={js_string_literal(data_url)}; // {rel}"
        )

    if dataurl_files:
        lines.append("")

    lines.append("function __plugin_b64_to_text(b64){const bin=atob(b64);const bytes=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);return new TextDecoder().decode(bytes);}")
    lines.append("function __plugin_global_eval(js){(0,eval)(js);}")
    lines.append("function plugin_load_assets(){")

    for path in js_files:
        rel = path.relative_to(root).as_posix()
        encoded = encoded_by_path[path]
        lines.append(
            f'    __plugin_global_eval(__plugin_b64_to_text({js_string_literal(encoded)})); // {rel}'
        )

    for path in css_files:
        rel = path.relative_to(root).as_posix()
        encoded = encoded_by_path[path]
        lines.append(
            f'    (()=>{{const s=document.createElement("style");s.textContent=__plugin_b64_to_text({js_string_literal(encoded)});document.head.appendChild(s);}})(); // {rel}'
        )

    if html_files:
        lines.append('    const plugin_dom_parser=new DOMParser();')
        html_dom_names: list[str] = []

        for index, path in enumerate(html_files, start=1):
            rel = path.relative_to(root).as_posix()
            encoded = encoded_by_path[path]
            dom_name = f"__plugin_html_dom_{index}"
            html_dom_names.append(dom_name)
            lines.append(
                f'    const {dom_name}=plugin_dom_parser.parseFromString(__plugin_b64_to_text({js_string_literal(encoded)}),"text/html"); // {rel}'
            )

        lines.append("    // Example body swap from one parsed HTML document:")
        lines.append(f"    // const nextBody={html_dom_names[0]}.body;")
        lines.append("    // document.body.replaceWith(nextBody);")

    lines.append("}")
    lines.append("")
    lines.append("function elrs_plugin_init(arg){")
    lines.append("    let plugin_config=null;")
    lines.append("    if(arg!==undefined){")
    lines.append('        if(arg!==null&&typeof arg==="object"&&!Array.isArray(arg)){')
    lines.append("            plugin_config=arg;")
    lines.append("        }")
    lines.append("    }")
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

    cfg_js_files, js_files, css_files, html_files, dataurl_files = find_assets(root, output_dir)
    all_files = js_files + css_files + html_files

    encoded_by_path: dict[Path, str] = {}
    dataurl_by_path: dict[Path, str] = {}
    dataurl_source_by_path: dict[Path, Path] = {}

    for source_path in all_files:
        original = source_path.read_text(encoding="utf-8")
        minified = minify_text(original, source_path.suffix.lower())
        encoded = encode_base64_utf8(minified)
        encoded_by_path[source_path] = encoded

        debug_path = make_debug_output_path(output_dir, root, source_path)
        write_debug_file(debug_path, minified, encoded, source_path.suffix.lower())

    for source_path in dataurl_files:
        suffix = source_path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg"}:
            dataurl_source_by_path[source_path] = write_optimized_image_copy(
                source_path,
                output_dir,
                root,
            )
        elif suffix == ".svg":
            dataurl_source_by_path[source_path] = write_minified_svg_copy(
                source_path,
                output_dir,
                root,
            )
        else:
            dataurl_source_by_path[source_path] = source_path

        dataurl_by_path[source_path] = build_data_url(dataurl_source_by_path[source_path])

    plugin_template = build_plugin_template(
        root,
        cfg_js_files,
        js_files,
        css_files,
        html_files,
        encoded_by_path,
        dataurl_files,
        dataurl_by_path,
    )

    plugin_template_path = output_dir / "plugin_template.js"
    plugin_template_path.write_text(plugin_template, encoding="utf-8", newline="\n")
    plugin_template_size = plugin_template_path.stat().st_size

    print(f"Scanned: {root}")
    print(f"Output:  {output_dir}")
    print(f"Config JS files: {len(cfg_js_files)}")
    print(f"JS files:  {len(js_files)}")
    print(f"CSS files: {len(css_files)}")
    print(f"HTML files: {len(html_files)}")
    print(f"Data URL files: {len(dataurl_files)}")
    print(f"Wrote: {plugin_template_path}")
    print(f"plugin_template.js size: {plugin_template_size} bytes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
