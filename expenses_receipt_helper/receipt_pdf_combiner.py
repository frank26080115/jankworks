import argparse
import os
import re
import sys
from collections import defaultdict
from pypdf import PdfReader, PdfWriter


def parse_args():
    parser = argparse.ArgumentParser(
        description="Concatenate related receipt PDFs based on _visa / _bank suffixes."
    )
    parser.add_argument(
        "input_dir",
        help="Input directory containing PDF files"
    )
    return parser.parse_args()


def ensure_output_dir(input_dir):
    output_dir = os.path.join(input_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


# Regex breakdown:
# base_name(_visa|_bank)(optional_number).pdf
SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)(?:_(visa|bank))(?P<order>\d*)\.pdf$",
    re.IGNORECASE
)


def collect_pdfs(input_dir):
    all_pdfs = [
        f for f in os.listdir(input_dir)
        if f.lower().endswith(".pdf")
    ]

    grouped = defaultdict(dict)
    standalone = []

    for filename in all_pdfs:
        match = SUFFIX_RE.match(filename)
        full_path = os.path.join(input_dir, filename)

        if match:
            base = match.group("base")
            order = match.group("order")
            order = int(order) if order else 1

            grouped[base][order] = full_path
        else:
            standalone.append(filename)

    return grouped, standalone


def find_primary_pdf(input_dir, base):
    """
    Primary PDF is exactly '<base>.pdf'
    """
    candidate = os.path.join(input_dir, f"{base}.pdf")
    return candidate if os.path.exists(candidate) else None


def concatenate_pdfs(base, primary_pdf, ordered_parts, output_dir):
    writer = PdfWriter()

    for path in [primary_pdf] + ordered_parts:
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)

    output_path = os.path.join(output_dir, f"{base}_combined.pdf")
    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"✔ Created: {output_path}")


def main():
    args = parse_args()
    input_dir = os.path.abspath(args.input_dir)

    if not os.path.isdir(input_dir):
        print(f"ERROR: '{input_dir}' is not a directory", file=sys.stderr)
        sys.exit(1)

    output_dir = ensure_output_dir(input_dir)
    grouped, standalone = collect_pdfs(input_dir)

    used_files = set()

    for base, parts in grouped.items():
        primary_pdf = find_primary_pdf(input_dir, base)

        if not primary_pdf:
            print(f"⚠ WARNING: Found bank/visa PDFs for '{base}' but no primary PDF")
            continue

        ordered_parts = [
            parts[k] for k in sorted(parts.keys())
        ]

        concatenate_pdfs(base, primary_pdf, ordered_parts, output_dir)

        used_files.add(os.path.basename(primary_pdf))
        for p in ordered_parts:
            used_files.add(os.path.basename(p))

    # Warn about PDFs that weren't part of any concatenation
    unused = [
        f for f in standalone
        if f not in used_files and f != "output"
    ]

    if unused:
        print("\n⚠ WARNING: PDFs with no concatenations:")
        for f in unused:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
