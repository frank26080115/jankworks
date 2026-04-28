import argparse
import base64
import math
import xml.sax.saxutils as xml_escape
from dataclasses import dataclass
from pathlib import Path

import cv2
import ezdxf
import numpy as np


DPI = 400
PX_PER_MM = DPI / 25.4
DEFAULT_STROKE_WIDTH_MM = 0.05
RENDER_STROKE_WIDTH_MM = 1.0
FILE_A_COLOUR = "#0066FF"
FILE_B_COLOUR = "#CC00CC"
DIFF_COLOUR = (255, 0, 0, 255)
ROTATIONS = (0, 90, 180, 270)


@dataclass
class SvgPath:
    d: str
    points: list[tuple[float, float]]


@dataclass
class Geometry:
    name: str
    paths: list[SvgPath]

    @property
    def points(self) -> list[tuple[float, float]]:
        out = []
        for path in self.paths:
            out.extend(path.points)
        return out

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        points = self.points
        if not points:
            raise ValueError(f"{self.name} contains no supported DXF geometry")
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class MatchResult:
    rotation: int
    offset: tuple[float, float]
    score: float
    rotated_min: tuple[float, float]
    rotated_size: tuple[float, float]


def fmt(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def arc_points(
    center: tuple[float, float],
    radius: float,
    start_angle: float,
    end_angle: float,
    segments_per_circle: int = 144,
) -> list[tuple[float, float]]:
    delta = (end_angle - start_angle) % 360
    if delta == 0:
        delta = 360
    steps = max(6, math.ceil(segments_per_circle * delta / 360))
    return [
        (
            center[0] + radius * math.cos(math.radians(start_angle + delta * i / steps)),
            center[1] + radius * math.sin(math.radians(start_angle + delta * i / steps)),
        )
        for i in range(steps + 1)
    ]


def arc_to_svg_path(center, radius, start_angle, end_angle) -> SvgPath:
    points = arc_points(center, radius, start_angle, end_angle)
    delta = (end_angle - start_angle) % 360
    if delta == 0:
        delta = 360
    large_arc = 1 if delta > 180 else 0
    d = (
        f"M {fmt(points[0][0])} {fmt(points[0][1])} "
        f"A {fmt(radius)} {fmt(radius)} 0 {large_arc} 1 {fmt(points[-1][0])} {fmt(points[-1][1])}"
    )
    return SvgPath(d, points)


def circle_to_svg_path(center, radius) -> SvgPath:
    x, y = center
    points = arc_points(center, radius, 0, 360)
    d = (
        f"M {fmt(x + radius)} {fmt(y)} "
        f"A {fmt(radius)} {fmt(radius)} 0 1 0 {fmt(x - radius)} {fmt(y)} "
        f"A {fmt(radius)} {fmt(radius)} 0 1 0 {fmt(x + radius)} {fmt(y)}"
    )
    return SvgPath(d, points)


def line_to_svg_path(start, end) -> SvgPath:
    points = [(float(start[0]), float(start[1])), (float(end[0]), float(end[1]))]
    d = f"M {fmt(points[0][0])} {fmt(points[0][1])} L {fmt(points[1][0])} {fmt(points[1][1])}"
    return SvgPath(d, points)


def polyline_to_svg_path(points, closed=False) -> SvgPath | None:
    if not points:
        return None
    clean = [(float(x), float(y)) for x, y in points]
    d_parts = [f"M {fmt(clean[0][0])} {fmt(clean[0][1])}"]
    d_parts.extend(f"L {fmt(x)} {fmt(y)}" for x, y in clean[1:])
    if closed:
        d_parts.append("Z")
        if clean[0] != clean[-1]:
            clean.append(clean[0])
    return SvgPath(" ".join(d_parts), clean)


def entity_to_paths(entity) -> list[SvgPath]:
    etype = entity.dxftype()

    if etype == "LINE":
        return [line_to_svg_path(entity.dxf.start, entity.dxf.end)]

    if etype == "LWPOLYLINE":
        if entity.has_arc:
            flattened = [(p[0], p[1]) for p in entity.flattening(distance=0.05)]
            path = polyline_to_svg_path(flattened, entity.closed)
        else:
            path = polyline_to_svg_path([(p[0], p[1]) for p in entity], entity.closed)
        return [path] if path else []

    if etype == "POLYLINE":
        points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        path = polyline_to_svg_path(points, entity.is_closed)
        return [path] if path else []

    if etype == "ARC":
        return [
            arc_to_svg_path(
                (entity.dxf.center.x, entity.dxf.center.y),
                entity.dxf.radius,
                entity.dxf.start_angle,
                entity.dxf.end_angle,
            )
        ]

    if etype == "CIRCLE":
        return [circle_to_svg_path((entity.dxf.center.x, entity.dxf.center.y), entity.dxf.radius)]

    return []


def read_dxf(path: Path) -> Geometry:
    if not path.exists():
        raise FileNotFoundError(path)
    doc = ezdxf.readfile(path)
    paths = []
    for entity in doc.modelspace():
        paths.extend(entity_to_paths(entity))
    return Geometry(path.stem, paths)


def rotation_matrix(rotation: int) -> tuple[tuple[float, float], tuple[float, float]]:
    if rotation == 0:
        return ((1, 0), (0, 1))
    if rotation == 90:
        return ((0, -1), (1, 0))
    if rotation == 180:
        return ((-1, 0), (0, -1))
    if rotation == 270:
        return ((0, 1), (-1, 0))
    raise ValueError(rotation)


def apply_matrix(point, matrix):
    return (
        matrix[0][0] * point[0] + matrix[0][1] * point[1],
        matrix[1][0] * point[0] + matrix[1][1] * point[1],
    )


def rotate_geometry_points(
    points: list[tuple[float, float]],
    source_bbox: tuple[float, float, float, float],
    rotation: int,
) -> tuple[list[tuple[float, float]], tuple[float, float], tuple[float, float]]:
    minx, miny, _, _ = source_bbox
    matrix = rotation_matrix(rotation)
    rotated = [apply_matrix((x - minx, y - miny), matrix) for x, y in points]
    xs = [p[0] for p in rotated]
    ys = [p[1] for p in rotated]
    rotated_min = (min(xs), min(ys))
    normalized = [(x - rotated_min[0], y - rotated_min[1]) for x, y in rotated]
    size = (max(x for x, _ in normalized), max(y for _, y in normalized))
    return normalized, rotated_min, size


def normalize_paths(points: list[tuple[float, float]], bbox) -> list[tuple[float, float]]:
    minx, miny, _, _ = bbox
    return [(x - minx, y - miny) for x, y in points]


def render_points(
    path_points: list[list[tuple[float, float]]],
    width_mm: float,
    height_mm: float,
    offset: tuple[float, float] = (0, 0),
    stroke_width_mm: float = RENDER_STROKE_WIDTH_MM,
) -> np.ndarray:
    width_px = max(1, int(math.ceil(width_mm * PX_PER_MM)))
    height_px = max(1, int(math.ceil(height_mm * PX_PER_MM)))
    image = np.zeros((height_px, width_px), dtype=np.uint8)
    thickness = max(1, int(round(stroke_width_mm * PX_PER_MM)))

    for points in path_points:
        if len(points) < 2:
            continue
        pixel_points = np.array(
            [
                [
                    int(round((x + offset[0]) * PX_PER_MM)),
                    int(round((y + offset[1]) * PX_PER_MM)),
                ]
                for x, y in points
            ],
            dtype=np.int32,
        )
        cv2.polylines(image, [pixel_points], False, 255, thickness, lineType=cv2.LINE_AA)

    return image


def transformed_path_point_lists(geometry: Geometry, bbox, rotation=0, offset=(0, 0), rotated_min=(0, 0)):
    matrix = rotation_matrix(rotation)
    minx, miny, _, _ = bbox
    out = []
    for path in geometry.paths:
        transformed = []
        for x, y in path.points:
            rx, ry = apply_matrix((x - minx, y - miny), matrix)
            transformed.append((rx - rotated_min[0] + offset[0], ry - rotated_min[1] + offset[1]))
        out.append(transformed)
    return out


def find_best_match(first: Geometry, second: Geometry, search_padding_mm: float = 25.0) -> MatchResult:
    first_bbox = first.bbox
    second_bbox = second.bbox
    first_width = first_bbox[2] - first_bbox[0]
    first_height = first_bbox[3] - first_bbox[1]
    first_paths = transformed_path_point_lists(first, first_bbox)
    first_canvas = render_points(
        first_paths,
        first_width + search_padding_mm * 2,
        first_height + search_padding_mm * 2,
        offset=(search_padding_mm, search_padding_mm),
    )

    best = None
    template_padding_mm = 1.0
    for rotation in ROTATIONS:
        _, rotated_min, rotated_size = rotate_geometry_points(second.points, second_bbox, rotation)
        candidate_paths = transformed_path_point_lists(second, second_bbox, rotation, rotated_min=rotated_min)
        candidate = render_points(
            candidate_paths,
            rotated_size[0] + template_padding_mm * 2,
            rotated_size[1] + template_padding_mm * 2,
            offset=(template_padding_mm, template_padding_mm),
        )

        if candidate.shape[0] > first_canvas.shape[0] or candidate.shape[1] > first_canvas.shape[1]:
            pad_y = max(0, candidate.shape[0] - first_canvas.shape[0])
            pad_x = max(0, candidate.shape[1] - first_canvas.shape[1])
            match_canvas = cv2.copyMakeBorder(first_canvas, 0, pad_y, 0, pad_x, cv2.BORDER_CONSTANT, value=0)
        else:
            match_canvas = first_canvas

        result = cv2.matchTemplate(match_canvas, candidate, cv2.TM_CCORR_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        offset = (
            location[0] / PX_PER_MM + template_padding_mm - search_padding_mm,
            location[1] / PX_PER_MM + template_padding_mm - search_padding_mm,
        )
        match = MatchResult(rotation, offset, score, rotated_min, rotated_size)
        if best is None or match.score > best.score:
            best = match

    return best


def make_xor_png(first_paths, second_paths, width_mm, height_mm) -> str:
    first_mask = render_points(first_paths, width_mm, height_mm, stroke_width_mm=RENDER_STROKE_WIDTH_MM)
    second_mask = render_points(second_paths, width_mm, height_mm, stroke_width_mm=RENDER_STROKE_WIDTH_MM)
    xor = cv2.bitwise_xor(first_mask, second_mask)
    _, alpha = cv2.threshold(xor, 1, 255, cv2.THRESH_BINARY)

    rgba = np.zeros((xor.shape[0], xor.shape[1], 4), dtype=np.uint8)
    rgba[alpha > 0] = DIFF_COLOUR
    ok, encoded = cv2.imencode(".png", rgba)
    if not ok:
        raise RuntimeError("OpenCV failed to encode XOR PNG")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def svg_layer(name, content, transform=None, opacity=None):
    attrs = [
        f'inkscape:label="{xml_escape.escape(name)}"',
        'inkscape:groupmode="layer"',
    ]
    if transform:
        attrs.append(f'transform="{transform}"')
    if opacity is not None:
        attrs.append(f'opacity="{fmt(opacity)}"')
    return f"<g {' '.join(attrs)}>\n{content}\n</g>"


def svg_paths(geometry: Geometry, colour: str, stroke_width: str, hairline: bool) -> str:
    vector_effect = ' vector-effect="non-scaling-stroke"' if hairline else ""
    paths = []
    for idx, path in enumerate(geometry.paths):
        paths.append(
            f'<path id="{xml_escape.escape(geometry.name)}_{idx}" d="{xml_escape.escape(path.d)}" '
            f'fill="none" stroke="{colour}" stroke-width="{stroke_width}"{vector_effect} />'
        )
    return f'<g id="{xml_escape.escape(geometry.name)}_geometry">\n' + "\n".join(paths) + "\n</g>"


def matrix_to_svg(matrix, tx, ty) -> str:
    return (
        f"matrix({fmt(matrix[0][0])} {fmt(matrix[1][0])} "
        f"{fmt(matrix[0][1])} {fmt(matrix[1][1])} {fmt(tx)} {fmt(ty)})"
    )


def build_svg(first: Geometry, second: Geometry, match: MatchResult, stroke_width_mm: float, hairline: bool) -> str:
    first_bbox = first.bbox
    second_bbox = second.bbox
    first_width = first_bbox[2] - first_bbox[0]
    first_height = first_bbox[3] - first_bbox[1]

    first_paths_aligned = transformed_path_point_lists(first, first_bbox)
    second_paths_aligned = transformed_path_point_lists(
        second,
        second_bbox,
        match.rotation,
        offset=match.offset,
        rotated_min=match.rotated_min,
    )

    all_points = []
    for path in first_paths_aligned + second_paths_aligned:
        all_points.extend(path)
    minx = min(x for x, _ in all_points)
    miny = min(y for _, y in all_points)
    maxx = max(x for x, _ in all_points)
    maxy = max(y for _, y in all_points)

    margin = 5.0
    doc_shift = (margin - minx, margin - miny)
    doc_width = maxx - minx + margin * 2
    doc_height = maxy - miny + margin * 2

    first_doc_paths = [[(x + doc_shift[0], y + doc_shift[1]) for x, y in path] for path in first_paths_aligned]
    second_doc_paths = [[(x + doc_shift[0], y + doc_shift[1]) for x, y in path] for path in second_paths_aligned]
    xor_png = make_xor_png(first_doc_paths, second_doc_paths, doc_width, doc_height)

    stroke_width = "0.001mm" if hairline else f"{fmt(stroke_width_mm)}mm"
    first_transform = matrix_to_svg(rotation_matrix(0), -first_bbox[0] + doc_shift[0], -first_bbox[1] + doc_shift[1])

    second_matrix = rotation_matrix(match.rotation)
    rel_min = (second_bbox[0], second_bbox[1])
    rotated_origin = apply_matrix((-rel_min[0], -rel_min[1]), second_matrix)
    second_tx = rotated_origin[0] - match.rotated_min[0] + match.offset[0] + doc_shift[0]
    second_ty = rotated_origin[1] - match.rotated_min[1] + match.offset[1] + doc_shift[1]
    second_transform = matrix_to_svg(second_matrix, second_tx, second_ty)

    diff_layer = svg_layer(
        "XOR differences",
        (
            f'<image x="0" y="0" width="{fmt(doc_width)}" height="{fmt(doc_height)}" '
            f'preserveAspectRatio="none" href="data:image/png;base64,{xor_png}" />'
        ),
    )
    first_layer = svg_layer("File 1 - ground truth", svg_paths(first, FILE_A_COLOUR, stroke_width, hairline), first_transform)
    second_layer = svg_layer("File 2 - aligned", svg_paths(second, FILE_B_COLOUR, stroke_width, hairline), second_transform)

    return f'''<svg xmlns="http://www.w3.org/2000/svg"
    xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
    width="{fmt(doc_width)}mm" height="{fmt(doc_height)}mm"
    viewBox="0 0 {fmt(doc_width)} {fmt(doc_height)}">
{diff_layer}
{first_layer}
{second_layer}
</svg>
'''


def parse_args():
    parser = argparse.ArgumentParser(description="Compare two laser/waterjet DXF files and write an SVG overlay.")
    parser.add_argument("first_file", type=Path, help="Ground-truth DXF file")
    parser.add_argument("second_file", type=Path, help="DXF file to rotate and align against the first")
    parser.add_argument("output_file", nargs="?", type=Path, help="Output SVG file")
    parser.add_argument(
        "--hairline",
        action="store_true",
        help="Use a near-zero SVG stroke with non-scaling strokes instead of 0.05 mm.",
    )
    parser.add_argument(
        "--stroke-width",
        type=float,
        default=DEFAULT_STROKE_WIDTH_MM,
        help="Vector overlay stroke width in mm. Ignored when --hairline is used.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_path = args.output_file or args.first_file.with_suffix(".compare.svg")

    first = read_dxf(args.first_file)
    second = read_dxf(args.second_file)
    match = find_best_match(first, second)
    svg_text = build_svg(first, second, match, args.stroke_width, args.hairline)

    output_path.write_text(svg_text, encoding="utf-8")
    print(f"Best orientation: {match.rotation} degrees")
    print(f"Alignment offset: {match.offset[0]:.3f} mm, {match.offset[1]:.3f} mm")
    print(f"Template score: {match.score:.4f}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
