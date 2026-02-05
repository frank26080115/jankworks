import argparse
import os
import math

import ezdxf
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle


# =========================
# CONFIGURATION
# =========================

OUTPUT_SIZE_PX = 150
OUTPUT_DPI = 100
PADDING_RATIO = 0.05

IGNORED_ENTITY_TYPES = {
    "TEXT",
    "MTEXT",
    "DIMENSION",
    "HATCH",
    "LEADER",
    "MLEADER",
}

IGNORED_LAYERS = {
    "DIMENSIONS",
    "ANNOTATION",
    "TEXT",
    "DEFPOINTS",
}


# =========================
# UTILITIES
# =========================

def is_degenerate(xs, ys, eps=1e-6):
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    return dx < eps and dy < eps


def update_bounds(xs, ys, bounds):
    min_x, min_y, max_x, max_y = bounds
    old = bounds[:]

    min_x = min(min_x, *xs)
    min_y = min(min_y, *ys)
    max_x = max(max_x, *xs)
    max_y = max(max_y, *ys)

    if (min_x, min_y, max_x, max_y) != tuple(old):
        print(f"[BOUNDS] updated:")
        print(f"         from {old}")
        print(f"           to {(min_x, min_y, max_x, max_y)}")

    return [min_x, min_y, max_x, max_y]


def arc_bounds(cx, cy, r, start_deg, end_deg):
    """
    Compute tight bounding box for a DXF ARC.
    Angles in degrees.
    """
    def norm(a):
        return a % 360

    start = norm(start_deg)
    end = norm(end_deg)

    # Handle wraparound
    if end < start:
        end += 360

    angles = [start, end]

    # Cardinal directions where extrema occur
    for a in (0, 90, 180, 270):
        aa = a
        if aa < start:
            aa += 360
        if start <= aa <= end:
            angles.append(aa)

    xs = []
    ys = []

    for a in angles:
        rad = math.radians(a)
        xs.append(cx + r * math.cos(rad))
        ys.append(cy + r * math.sin(rad))

    return xs, ys


# =========================
# MAIN
# =========================

def main():
    parser = argparse.ArgumentParser(description="Render DXF to 150x150 PNG (black lines on white)")
    parser.add_argument("input_dxf", help="Input DXF file")
    args = parser.parse_args()

    input_path = args.input_dxf

    dxf_to_img(input_path, None)

def dxf_to_img(input_path, output_path):
    if output_path is None:
        output_path = os.path.splitext(input_path)[0] + "_img.png"

    print(f"[INFO] Loading DXF: {input_path}")
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()

    print("[INFO] DXF layers found:")
    for layer in doc.layers:
        print(f"       - {layer.dxf.name}")

    fig, ax = plt.subplots(
        figsize=(OUTPUT_SIZE_PX / OUTPUT_DPI, OUTPUT_SIZE_PX / OUTPUT_DPI),
        dpi=OUTPUT_DPI
    )

    ax.set_facecolor("white")

    bounds = [
        float("inf"),
        float("inf"),
        float("-inf"),
        float("-inf"),
    ]

    drawn_entities = 0

    print("[INFO] Beginning entity traversal")

    for e in msp:
        etype = e.dxftype()
        layer = e.dxf.layer

        print(f"[ENTITY] {etype} on layer '{layer}'")

        if etype in IGNORED_ENTITY_TYPES:
            print("         -> skipped (ignored entity type)")
            continue

        if layer in IGNORED_LAYERS:
            print("         -> skipped (ignored layer)")
            continue

        # -------------------------
        # LINE
        # -------------------------
        if etype == "LINE":
            x = [e.dxf.start.x, e.dxf.end.x]
            y = [e.dxf.start.y, e.dxf.end.y]

            if is_degenerate(x, y):
                print("         -> skipped (degenerate LINE)")
                continue

            ax.plot(x, y, color="black")
            bounds = update_bounds(x, y, bounds)
            drawn_entities += 1
            print("         -> drawn LINE")

        # -------------------------
        # POLYLINES
        # -------------------------
        elif etype in ("LWPOLYLINE", "POLYLINE"):
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) < 2:
                print("         -> skipped (too few points)")
                continue

            x, y = zip(*pts)

            if is_degenerate(x, y):
                print("         -> skipped (degenerate POLYLINE)")
                continue

            ax.plot(x, y, color="black")
            bounds = update_bounds(x, y, bounds)
            drawn_entities += 1
            print("         -> drawn POLYLINE")

        # -------------------------
        # CIRCLE
        # -------------------------
        elif etype == "CIRCLE":
            r = e.dxf.radius
            if r <= 0:
                print("         -> skipped (zero radius)")
                continue

            cx = e.dxf.center.x
            cy = e.dxf.center.y

            circ = Circle(
                (cx, cy),
                r,
                fill=False,
                color="black"
            )
            ax.add_patch(circ)

            bounds = update_bounds(
                [cx - r, cx + r],
                [cy - r, cy + r],
                bounds
            )
            drawn_entities += 1
            print("         -> drawn CIRCLE")

        # -------------------------
        # ARC
        # -------------------------
        elif etype == "ARC":
            r = e.dxf.radius
            if r <= 0:
                print("         -> skipped (zero radius)")
                continue

            cx = e.dxf.center.x
            cy = e.dxf.center.y

            arc = Arc(
                (cx, cy),
                2 * r,
                2 * r,
                theta1=e.dxf.start_angle,
                theta2=e.dxf.end_angle,
                color="black"
            )
            ax.add_patch(arc)

            xs, ys = arc_bounds(
                cx,
                cy,
                r,
                e.dxf.start_angle,
                e.dxf.end_angle
            )

            bounds = update_bounds(xs, ys, bounds)
            drawn_entities += 1
            print("         -> drawn ARC (tight bounds)")

        else:
            print("         -> skipped (unsupported entity)")

    if drawn_entities == 0:
        print("[ERROR] No drawable entities found.")
        return

    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    size = max(width, height)

    print("[INFO] Final raw bounds:")
    print(f"       min_x={min_x}, min_y={min_y}")
    print(f"       max_x={max_x}, max_y={max_y}")
    print(f"       width={width}, height={height}")

    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    padding = size * PADDING_RATIO
    half = size / 2 + padding

    print("[INFO] Applying square framing")
    print(f"       center=({cx}, {cy})")
    print(f"       half-size={half}")

    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy - half, cy + half)

    # Scale line width AFTER size known
    linewidth = 1 # size * 0.005
    print(f"[INFO] Using linewidth={linewidth}")

    for line in ax.lines:
        line.set_linewidth(linewidth)

    for patch in ax.patches:
        patch.set_linewidth(linewidth)

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    print(f"[INFO] Saving output PNG: {output_path}")
    plt.savefig(
        output_path,
        dpi=OUTPUT_DPI,
        bbox_inches="tight",
        pad_inches=0,
        facecolor="white",
    )
    plt.close(fig)

    print("[DONE]")
    return output_path


if __name__ == "__main__":
    main()
