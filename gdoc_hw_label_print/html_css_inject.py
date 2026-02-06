import argparse
import os
import re
from bs4 import BeautifulSoup, NavigableString, Tag


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
    min-width: 50mm;
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

  .chkbox-column,
  .hide-me {
    display: none !important;
  }

  tr.hide-me {
    display: none !important;
  }
}
"""


INJECTED_JS = """
<script>
(function () {
  const table = document.querySelector("table");
  if (!table) {
    console.warn("No table found on page.");
    return;
  }

  const rows = table.querySelectorAll("tr");

  rows.forEach(row => {
    // Skip header rows
    const firstCell = row.querySelector("td, th");
    if (!firstCell || firstCell.tagName === "TH") {
      return;
    }

    // Create checkbox
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "chkbox-control hide-me";

    // Default state: unchecked → hide
    row.classList.add("hide-me");

    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        row.classList.add("print-me");
        row.classList.remove("hide-me");

        checkbox.classList.add("hide-me");
        checkbox.classList.remove("print-me");
      } else {
        row.classList.remove("print-me");
        row.classList.add("hide-me");

        checkbox.classList.remove("hide-me");
        checkbox.classList.add("print-me");
      }
    });

    // Insert checkbox at the start of the first cell
    firstCell.insertBefore(checkbox, firstCell.firstChild);
  });

  // Controls container
  const controls = document.createElement("div");
  controls.className = "hide-me";

  const checkAllBtn = document.createElement("button");
  checkAllBtn.textContent = "Check All";

  const uncheckAllBtn = document.createElement("button");
  uncheckAllBtn.textContent = "Uncheck All";

  checkAllBtn.addEventListener("click", () => {
    rows.forEach(row => {
      const cb = row.querySelector("input.chkbox-control");
      if (cb) {
        cb.checked = true;

        row.classList.add("print-me");
        row.classList.remove("hide-me");

        cb.classList.add("print-me");
        cb.classList.remove("hide-me");
      }
    });
  });

  uncheckAllBtn.addEventListener("click", () => {
    rows.forEach(row => {
      const cb = row.querySelector("input.chkbox-control");
      if (cb) {
        cb.checked = false;

        row.classList.remove("print-me");
        row.classList.add("hide-me");

        cb.classList.remove("print-me");
        cb.classList.add("hide-me");
      }
    });
  });

  controls.appendChild(checkAllBtn);
  controls.appendChild(uncheckAllBtn);
  document.body.appendChild(controls);
})();
</script>
"""


VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "em",
    "i",
    "img",
    "small",
    "span",
    "strong",
}


BLOCK_TAGS = {
    "html", "head", "body",
    "div", "table", "thead", "tbody", "tfoot",
    "tr", "td", "th",
    "ul", "ol", "li",
    "section", "article", "nav", "main",
    "header", "footer",
    "p", "pre",
    "style", "script",
}


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

    return tag.replace('>', f' class="{class_name}">', 1)


def pretty_print_html(html: str, indent_unit: str = "  ") -> str:
    soup = BeautifulSoup(html, "html5lib")

    lines = []

    def render(node, indent=0):
        prefix = indent_unit * indent

        if isinstance(node, NavigableString):
            text = " ".join(node.string.split())
            if text:
                lines.append(prefix + text)
            return

        if not isinstance(node, Tag):
            return

        name = node.name.lower()

        # ----- Opening tag -----
        attrs = ""
        if node.attrs:
            parts = []
            for k, v in node.attrs.items():
                if isinstance(v, list):
                    v = " ".join(v)
                parts.append(f'{k}="{v}"')
            attrs = " " + " ".join(parts)

        if name in VOID_TAGS:
            lines.append(f"{prefix}<{name}{attrs}>")
            return

        # ----- Script / Style: preserve content verbatim -----
        if name in {"script", "style"}:
            lines.append(f"{prefix}<{name}{attrs}>")
            if node.string:
                lines.append(node.string.rstrip())
            lines.append(f"{prefix}</{name}>")
            return

        lines.append(f"{prefix}<{name}{attrs}>")

        # ----- Children -----
        for child in node.children:
            render(child, indent + 1)

        # ----- Closing tag -----
        lines.append(f"{prefix}</{name}>")

    # Render only top-level nodes
    for child in soup.contents:
        render(child, 0)

    return "\n".join(lines) + "\n"


def process_html(html: str) -> str:
    # Inject CSS before </style>
    if '</style>' in html:
        html = html.replace('</style>', f'\n{INJECTED_CSS}\n</style>', 1)
    else:
        raise RuntimeError("No </style> tag found")

    # Modify <body> tag
    html = re.sub(
        r'<body([^>]*)>',
        lambda m: add_class(f'<body{m.group(1)}>', 'no-lr-space'),
        html,
        count=1,
    )

    # Modify <table> tag
    html = re.sub(
        r'<table([^>]*)>',
        lambda m: add_class(f'<table{m.group(1)}>', 'no-lr-space'),
        html,
        count=1,
    )

    # Process table rows
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

    # Remove inline style attributes from <span> and <img> tags
    html = re.sub(
        r'(<(?:span|img)\b[^>]*?)\s+style="[^"]*"([^>]*>)',
        r'\1\2',
        html,
        flags=re.IGNORECASE,
    )

    # Apply indentation so the output HTML is easy to read and diff.
    html = pretty_print_html(html)

    # Inject JS before </body>
    if '</body>' in html:
        html = html.replace('</body>', f'\n{INJECTED_JS}\n</body>', 1)

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

    # Write with CRLF line endings so the file is Windows-friendly.
    with open(output_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(modified_html)

    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
