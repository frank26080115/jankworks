import argparse
import os
import re
import sys
import tempfile
from collections import defaultdict
from pypdf import PdfReader, PdfWriter
from PIL import Image
import io


MAX_MB = 3
MAX_PX = 2000


def parse_args():
    parser = argparse.ArgumentParser(
        description="Concatenate related receipt PDFs with optional image downscaling."
    )
    parser.add_argument("input_dir", help="Input directory containing PDF files")
    return parser.parse_args()


def ensure_output_dir(input_dir):
    output_dir = os.path.join(input_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)(?:_(visa|bank))(?P<order>\d*)\.pdf$",
    re.IGNORECASE
)


def collect_pdfs(input_dir):
    grouped = defaultdict(dict)
    standalone = []

    for f in os.listdir(input_dir):
        if not f.lower().endswith(".pdf"):
            continue

        m = SUFFIX_RE.match(f)
        if m:
            base = m.group("base")
            order = int(m.group("order")) if m.group("order") else 1
            grouped[base][order] = os.path.join(input_dir, f)
        else:
            standalone.append(f)

    return grouped, standalone


def find_primary_pdf(input_dir, base):
    p = os.path.join(input_dir, f"{base}.pdf")
    return p if os.path.exists(p) else None


def needs_optimization(path):
    return os.path.getsize(path) > MAX_MB * 1024 * 1024


def optimize_pdf(path):
    """
    Returns path to optimized PDF (temp file) or original path if no changes needed
    """
    reader = PdfReader(path)
    writer = PdfWriter()
    modified = False

    for page in reader.pages:
        if "/Resources" in page and "/XObject" in page["/Resources"]:
            xobjects = page["/Resources"]["/XObject"]

            for name in list(xobjects.keys()):
                xobj = xobjects[name]
                if xobj.get("/Subtype") == "/Image":
                    width = xobj["/Width"]
                    height = xobj["/Height"]
                    data = xobj.get_data()
                    try:
                        img = Image.open(io.BytesIO(data))
                        img.load()  # force decode now, not lazily

                        if max(img.size) <= MAX_PX:
                            continue

                        img = img.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)

                        out = io.BytesIO()
                        img.convert("RGB").save(out, format="JPEG", quality=85)
                        out.seek(0)

                        xobj._data = out.read()
                        xobj["/Filter"] = "/DCTDecode"
                        xobj["/Width"], xobj["/Height"] = img.size
                        modified = True

                    except Exception as e:
                        # Not a Pillow-decodable image — leave it completely untouched
                        print(
                            f"⚠ Skipping non-decodable image XObject in "
                            f"{os.path.basename(path)} ({type(e).__name__})"
                        )
                        continue


        writer.add_page(page)

    if not modified:
        return path

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with open(tmp.name, "wb") as f:
        writer.write(f)

    print(f"🗜 Optimized: {os.path.basename(path)} → {os.path.basename(tmp.name)}")
    return tmp.name


def concatenate_pdfs(base, files, output_dir):
    writer = PdfWriter()

    for path in files:
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)

    out_path = os.path.join(output_dir, f"{base}_combined.pdf")
    with open(out_path, "wb") as f:
        writer.write(f)

    print(f"✔ Created: {out_path}")


def main():
    args = parse_args()
    input_dir = os.path.abspath(args.input_dir)

    if not os.path.isdir(input_dir):
        print("ERROR: input is not a directory", file=sys.stderr)
        sys.exit(1)

    output_dir = ensure_output_dir(input_dir)
    grouped, standalone = collect_pdfs(input_dir)

    used = set()

    for base, parts in grouped.items():
        primary = find_primary_pdf(input_dir, base)
        if not primary:
            print(f"⚠ WARNING: Missing primary PDF for '{base}'")
            continue

        ordered = [primary] + [parts[k] for k in sorted(parts)]
        processed = []

        for path in ordered:
            if needs_optimization(path):
                processed.append(optimize_pdf(path))
            else:
                processed.append(path)

            used.add(os.path.basename(path))

        concatenate_pdfs(base, processed, output_dir)

    unused = [f for f in standalone if f not in used]
    if unused:
        print("\n⚠ WARNING: PDFs with no concatenations:")
        for f in unused:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
