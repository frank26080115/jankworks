import argparse
from pathlib import Path
import math

# NOTE: requires: pip install ezdxf
import ezdxf


class PathElement:
    """
    Represents a single SVG path. Internally stores the SVG 'd' string
    plus the explicit start/end coordinates for later path joining logic.
    """

    def __init__(self, d, start, end):
        self.d = d
        self.start = start
        self.end = end

    def start_point(self):
        return self.start

    def end_point(self):
        return self.end

    def to_svg(self, stroke_width):
        return f'<path d="{self.d}" fill="none" stroke="black" stroke-width="{stroke_width}mm" />'


class Group:
    def __init__(self, name):
        self.name = name
        self.paths = []

    def add_path(self, path: PathElement):
        self.paths.append(path)

    def to_svg(self, stroke_width):
        content = "\n".join(p.to_svg(stroke_width) for p in self.paths)
        return f'<g id="{self.name}">{content}</g>'


class Layer:
    def __init__(self, name):
        self.name = name
        self.groups = []

    def add_group(self, group: Group):
        self.groups.append(group)

    def to_svg(self, stroke_width):
        content = "\n".join(g.to_svg(stroke_width) for g in self.groups)
        return (
            f'<g inkscape:label="{self.name}" inkscape:groupmode="layer">\n'
            f'{content}\n'
            f'</g>'
        )


class SVG:
    def __init__(self, width=1000, height=1000, stroke_width=0.1):
        self.width = width
        self.height = height
        self.stroke_width = stroke_width
        self.layers = []

    def add_layer(self, layer: Layer):
        self.layers.append(layer)

    def to_svg(self):
        layers_svg = "\n".join(layer.to_svg(self.stroke_width) for layer in self.layers)
        return f'''<svg xmlns="http://www.w3.org/2000/svg"
    xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
    width="{self.width}mm" height="{self.height}mm"
    viewBox="0 0 {self.width} {self.height}">
{layers_svg}
</svg>'''


# -----------------------------
# Geometry helpers
# -----------------------------

def arc_to_svg_path(center, radius, start_angle, end_angle):
    """Convert DXF arc parameters to an SVG path.

    DXF arcs are always counter‑clockwise from start_angle → end_angle.
    Angles wrap at 360°, so we must normalize the sweep to determine
    the correct SVG large‑arc flag.
    """

    start_rad = math.radians(start_angle)
    end_rad = math.radians(end_angle)

    x1 = center[0] + radius * math.cos(start_rad)
    y1 = center[1] + radius * math.sin(start_rad)

    x2 = center[0] + radius * math.cos(end_rad)
    y2 = center[1] + radius * math.sin(end_rad)

    # DXF arcs sweep CCW. Normalize delta into [0,360)
    delta = (end_angle - start_angle) % 360

    # Determine SVG arc flags
    large_arc = 1 if delta > 180 else 0
    sweep = 1  # CCW

    d = f"M {x1} {y1} A {radius} {radius} 0 {large_arc} {sweep} {x2} {y2}"

    return d, (x1, y1), (x2, y2)


def circle_to_svg_path(center, radius):
    """Represent circle as two arcs."""

    x = center[0]
    y = center[1]

    start = (x + radius, y)

    d = (
        f"M {x + radius} {y} "
        f"A {radius} {radius} 0 1 0 {x - radius} {y} "
        f"A {radius} {radius} 0 1 0 {x + radius} {y}"
    )

    return d, start, start


# -----------------------------
# DXF Parsing
# -----------------------------

def entity_to_path(entity):
    """Convert a DXF entity to a PathElement."""

    etype = entity.dxftype()

    if etype == "LINE":
        x1, y1, _ = entity.dxf.start
        x2, y2, _ = entity.dxf.end

        d = f"M {x1} {y1} L {x2} {y2}"
        return PathElement(d, (x1, y1), (x2, y2))

    elif etype == "LWPOLYLINE":
        points = [(p[0], p[1]) for p in entity]

        if not points:
            return None

        d = f"M {points[0][0]} {points[0][1]} "
        for p in points[1:]:
            d += f"L {p[0]} {p[1]} "

        if entity.closed:
            d += "Z"

        return PathElement(d, points[0], points[-1])

    elif etype == "POLYLINE":
        points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]

        if not points:
            return None

        d = f"M {points[0][0]} {points[0][1]} "
        for p in points[1:]:
            d += f"L {p[0]} {p[1]} "

        return PathElement(d, points[0], points[-1])

    elif etype == "ARC":
        center = (entity.dxf.center.x, entity.dxf.center.y)
        radius = entity.dxf.radius
        start_angle = entity.dxf.start_angle
        end_angle = entity.dxf.end_angle

        d, start, end = arc_to_svg_path(center, radius, start_angle, end_angle)
        return PathElement(d, start, end)

    elif etype == "CIRCLE":
        center = (entity.dxf.center.x, entity.dxf.center.y)
        radius = entity.dxf.radius

        d, start, end = circle_to_svg_path(center, radius)
        return PathElement(d, start, end)

    else:
        return None


# -----------------------------
# CLI
# -----------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Convert DXF to laser-cutting SVG")

    parser.add_argument("input_file", type=Path, help="Input DXF file")

    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output SVG file"
    )

    parser.add_argument(
        "--join-tolerance",
        type=float,
        default=0.2,
        help="Tolerance (mm) when joining path endpoints"
    )

    parser.add_argument(
        "--stroke-width",
        type=float,
        default=0.1,
        help="SVG stroke width in mm"
    )

    return parser.parse_args()


# -----------------------------
# Main
# -----------------------------

def main():

    args = parse_args()

    input_path = args.input_file

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    if args.output:
        output_path = args.output
    else:
        output_path = input_path.with_suffix(".svg")

    join_tolerance = args.join_tolerance

    print(f"Join tolerance: {join_tolerance} mm")

    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()

    svg = SVG(stroke_width=args.stroke_width)

    layer = Layer("geometry")
    group = Group("dxf_entities")

    for entity in msp:
        path = entity_to_path(entity)
        if path:
            group.add_path(path)

    layer.add_group(group)
    svg.add_layer(layer)

    svg_text = svg.to_svg()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_text)


if __name__ == "__main__":
    main()
