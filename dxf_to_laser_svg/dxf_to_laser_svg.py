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
        self.is_closed = False

    def add_path(self, path: PathElement):
        self.paths.append(path)

    def to_svg(self, stroke_width):
        content = "\n".join(p.to_svg(stroke_width) for p in self.paths)
        closed_flag = "true" if self.is_closed else "false"
        return f'<g id="{self.name}" data-closed="{closed_flag}">\n{content}\n</g>'


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
# Path grouping helpers


def endpoints_of_path(p):
    return [p.start_point(), p.end_point()]


def group_is_closed(group, tol):
    """
    Determine if a group forms a fully enclosed loop.
    Each endpoint must have another endpoint within tolerance.
    """

    endpoints = []

    for p in group:
        endpoints.extend(endpoints_of_path(p))

    used = [False] * len(endpoints)

    for i, a in enumerate(endpoints):

        if used[i]:
            continue

        found = False

        for j, b in enumerate(endpoints):

            if i == j or used[j]:
                continue

            if distance(a, b) <= tol:
                used[i] = True
                used[j] = True
                found = True
                break

        if not found:
            return False

    return True


# -----------------------------
# Path grouping helpers
# -----------------------------

def distance(a, b):
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.hypot(dx, dy)


def paths_touch(p1: PathElement, p2: PathElement, tol):
    """Return True if endpoints of two paths are within tolerance."""

    s1 = p1.start_point()
    e1 = p1.end_point()
    s2 = p2.start_point()
    e2 = p2.end_point()

    if distance(e1, s2) <= tol:
        return True

    if distance(e1, e2) <= tol:
        return True

    if distance(s1, s2) <= tol:
        return True

    if distance(s1, e2) <= tol:
        return True

    return False


def group_paths(paths, tol):
    """
    Group paths that share endpoints within tolerance.
    Each path will belong to exactly one group.
    """

    groups = []
    used = set()

    for i, path_i in enumerate(paths):

        if i in used:
            continue

        group = [path_i]
        used.add(i)

        changed = True

        while changed:
            changed = False

            for j, path_j in enumerate(paths):

                if j in used:
                    continue

                for g in group:
                    if paths_touch(g, path_j, tol):
                        group.append(path_j)
                        used.add(j)
                        changed = True
                        break

        groups.append(group)

    return groups


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

    # Convert DXF entities into PathElement list
    paths = []

    for entity in msp:
        path = entity_to_path(entity)
        if path:
            paths.append(path)

    # Group paths based on endpoint proximity
    path_groups = group_paths(paths, join_tolerance)

    # ---- Compute bounding boxes for each group ----
    def group_bbox(group):
        xs = []
        ys = []
        for p in group:
            xs.extend([p.start_point()[0], p.end_point()[0]])
            ys.extend([p.start_point()[1], p.end_point()[1]])
        return min(xs), min(ys), max(xs), max(ys)

    def bbox_size(bbox):
        minx, miny, maxx, maxy = bbox
        w = maxx - minx
        h = maxy - miny
        return max(w, h)

    # attach metadata to groups
    groups_meta = []
    for g in path_groups:
        bbox = group_bbox(g)
        groups_meta.append({
            "paths": g,
            "bbox": bbox,
            "size": bbox_size(bbox),
            "closed": group_is_closed(g, join_tolerance)
        })

    # sort by size (smallest first)
    groups_meta.sort(key=lambda x: x["size"])

    # simple point-in-bbox test used as fast prefilter
    def bbox_contains(b1, b2):
        return b1[0] <= b2[0] and b1[1] <= b2[1] and b1[2] >= b2[2] and b1[3] >= b2[3]

    # determine containment relationships
    for g in groups_meta:
        g["contains"] = []
        g["contained_by"] = None

    for i, small in enumerate(groups_meta):
        for j, big in enumerate(groups_meta):
            if i == j:
                continue
            if bbox_contains(big["bbox"], small["bbox"]):
                small["contained_by"] = big
                big["contains"].append(small)
                break

    tiny_islands = []
    tiny_holes = []
    enclosing_roots = []
    remaining = []

    for g in groups_meta:
        if not g["contains"] and g["contained_by"] is None:
            tiny_islands.append(g)
        elif not g["contains"]:
            tiny_holes.append(g)
        elif g["contains"] and g["contained_by"] is None:
            enclosing_roots.append(g)
        else:
            remaining.append(g)

    # bottom layer 1 (standalone islands)
    islands_layer = Layer("islands")
    for idx, g in enumerate(tiny_islands):
        svg_group = Group(f"island_{idx}")
        svg_group.is_closed = g["closed"]
        for p in g["paths"]:
            svg_group.add_path(p)
        holes_layer.add_group(svg_group)

    # bottom layer 2 (tiny holes)
    holes_layer = Layer("tiny_holes")
    for idx, g in enumerate(tiny_holes):
        svg_group = Group(f"tiny_{idx}")
        svg_group.is_closed = g["closed"]
        for p in g["paths"]:
            svg_group.add_path(p)
        holes_layer.add_group(svg_group)

    # middle layer (nested remaining groups)
    middle_layer = Layer("nested_geometry")
    for idx, g in enumerate(remaining):
        svg_group = Group(f"nested_{idx}")
        svg_group.is_closed = g["closed"]
        for p in g["paths"]:
            svg_group.add_path(p)
        middle_layer.add_group(svg_group)

    # top layer (large enclosing shapes)
    outer_layer = Layer("outer_loops")
    for idx, g in enumerate(enclosing_roots):
        svg_group = Group(f"outer_{idx}")
        svg_group.is_closed = g["closed"]
        for p in g["paths"]:
            svg_group.add_path(p)
        outer_layer.add_group(svg_group)

    # SVG layer order: outer first (top), nested middle, holes last
    svg.add_layer(outer_layer)
    svg.add_layer(middle_layer)
    svg.add_layer(holes_layer)
    svg.add_layer(islands_layer)

    svg_text = svg.to_svg()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_text)


if __name__ == "__main__":
    main()
