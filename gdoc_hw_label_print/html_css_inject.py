import argparse
import os
import re


INJECTED_CSS = """
/* === Injected label-print CSS === */
@media print {
  @page {
    margin: 0;
  }

  .no-lr-space {
    border-collapse: collapse;
    border: none;
    margin-left: 0;
    margin-right: 0;
    padding-left: 0;
    padding-right: 0;
    padding: 0;
  }

  table {
    border-collapse: collapse;
    border: none;
    margin-left: 0;
    margin-right: 0;
    padding-left: 0;
    padding-right: 0;
  }

  tr {
    height: 24mm;
    break-after: page;
    page-break-after: always;
    break-inside: avoid;
    page-break-inside: avoid;
  }

  td {
    border: none;
    padding-top: 0;
    padding-bottom: 0;
    vertical-align: middle;
  }

  td:first-child {
    padding-left: 0;
    padding-right: 0;
    border: none;
    width: 0;
  }

  td:last-child {
    padding-left: 0;
    padding-right: 0;
    border: none;
    width: 0;
  }

  td p span img {
    max-height: 20mm;
    width: auto;
    height: auto;
    object-fit: contain;
    display: block;
  }

  td.left-most-column {
    display: none;
  }
}
"""


def add_class(tag: str, class_name: str) -> str:
    """
    Add a class to an HTML tag string.
    If class attribute exists, append.
    If not, create it.
    """
    if 'class=' in tag:
        return re.sub(
            r'class="([^"]*)"',
            lambda m: f'class="{m.group(1)} {class_name}"',
            tag,
            count=1,
        )
    else:
        return tag.replace('>', f' class="{class_name}">', 1)


def process_html(html: str) -> str:
    # 1. Inject CSS before </style>
    if '</style>' in html:
        html = html.replace('</style>', f'\n{INJECTED_CSS}\n</style>', 1)
    else:
        raise RuntimeError("No </style> tag found")

    # 2. Modify <body> tag
    html = re.sub(
        r'<body([^>]*)>',
        lambda m: add_class(f'<body{m.group(1)}>', 'no-lr-space'),
        html,
        count=1,
    )

    # 3. Modify <table> tag
    html = re.sub(
        r'<table([^>]*)>',
        lambda m: add_class(f'<table{m.group(1)}>', 'no-lr-space'),
        html,
        count=1,
    )

    # 4. Process table rows
    def process_row(match):
        row = match.group(0)

        # Find all <td> opening tags
        tds = list(re.finditer(r'<td([^>]*)>', row))
        if len(tds) == 3:
            first_td = tds[0]
            new_td = add_class(first_td.group(0), 'left-most-column')
            row = row[:first_td.start()] + new_td + row[first_td.end():]

        return row

    html = re.sub(
        r'<tr[\s\S]*?</tr>',
        process_row,
        html,
    )

    # 5. Remove inline style attributes from <span> and <img> tags
    html = re.sub(
        r'(<(?:span|img)\b[^>]*?)\s+style="[^"]*"([^>]*>)',
        r'\1\2',
        html,
        flags=re.IGNORECASE,
    )

    return html


def main():
    parser = argparse.ArgumentParser(description="Modify Google Docs HTML for label printing")
    parser.add_argument("html_file", help="Input HTML file")
    args = parser.parse_args()

    input_path = args.html_file
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_modified.html"

    with open(input_path, "r", encoding="utf-8") as f:
        html = f.read()

    modified_html = process_html(html)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(modified_html)

    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
