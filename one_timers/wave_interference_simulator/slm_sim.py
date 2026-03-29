import numpy as np
import argparse
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# -----------------------------
# Cube generation
# -----------------------------
def generate_cube_points(size=0.8, resolution=10):
    coords = np.linspace(-size, size, resolution)
    points = []

    for x in coords:
        for y in coords:
            for z in coords:
                edge_count = sum([
                    abs(x) == size,
                    abs(y) == size,
                    abs(z) == size
                ])
                if edge_count >= 2:
                    points.append([x, y, z])

    return np.array(points)

# -----------------------------
# GS
# -----------------------------
def gerchberg_saxton_2d(target, iterations=100):
    h, w = target.shape

    phase = np.random.rand(h, w) * 2 * np.pi
    field = np.exp(1j * phase)

    target_amp = np.sqrt(target)

    for _ in range(iterations):
        spectrum = np.fft.fft2(field)
        spectrum = target_amp * np.exp(1j * np.angle(spectrum))
        field = np.fft.ifft2(spectrum)
        field = np.exp(1j * np.angle(field))

    return np.angle(field)


# -----------------------------
# Reconstruction (Intensity)
# -----------------------------
def reconstruct_intensity_from_phase(phase_map):
    field = np.exp(1j * phase_map)

    fft = np.fft.fftshift(np.fft.fft2(field))
    intensity = np.abs(fft) ** 2

    # normalize for visualization
    intensity /= np.max(intensity) + 1e-8

    return intensity


# -----------------------------
# Rotation
# -----------------------------
def rotation_matrix(roll, pitch, yaw):
    Rx = np.array([
        [1, 0, 0],
        [0, np.cos(roll), -np.sin(roll)],
        [0, np.sin(roll),  np.cos(roll)]
    ])

    Ry = np.array([
        [ np.cos(pitch), 0, np.sin(pitch)],
        [0, 1, 0],
        [-np.sin(pitch), 0, np.cos(pitch)]
    ])

    Rz = np.array([
        [np.cos(yaw), -np.sin(yaw), 0],
        [np.sin(yaw),  np.cos(yaw), 0],
        [0, 0, 1]
    ])

    return Rz @ Ry @ Rx


# -----------------------------
# Phase map (SLM)
# -----------------------------
def cube_phase(width, height, points):
    x = np.linspace(-1, 1, width)
    y = np.linspace(-1, 1, height)
    xv, yv = np.meshgrid(x, y)

    field = np.zeros((height, width), dtype=np.complex64)

    for (px, py, pz) in points:
        scale = 1.0 / (pz + 2.0)

        kx = px * scale * 20
        ky = py * scale * 20

        phase = kx * xv + ky * yv
        field += np.exp(1j * phase)

    phase_map = np.angle(field)

    return phase_map


def cube_to_target(points, width, height):
    target = np.zeros((height, width), dtype=np.float32)

    for (px, py, pz) in points:
        scale = 1.0 / (pz + 2.0)

        x = int((px * scale * 0.5 + 0.5) * (width - 1))
        y = int((py * scale * 0.5 + 0.5) * (height - 1))

        if 0 <= x < width and 0 <= y < height:
            target[y, x] = 1.0

    return target


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--size", type=float, default=0.8)
    parser.add_argument("--points", type=int, default=10)

    parser.add_argument("--roll", type=float, default=0.0)
    parser.add_argument("--pitch", type=float, default=0.0)
    parser.add_argument("--yaw", type=float, default=0.0)

    parser.add_argument("--method", choices=["direct", "gs"], default="direct")
    parser.add_argument("--iterations", type=int, default=100)

    args = parser.parse_args()

    # Convert degrees → radians
    roll = np.deg2rad(args.roll)
    pitch = np.deg2rad(args.pitch)
    yaw = np.deg2rad(args.yaw)

    # Generate cube
    points = generate_cube_points(args.size, args.points)

    # Apply rotation
    R = rotation_matrix(roll, pitch, yaw)
    points = points @ R.T

    # Generate phase map
    width = 128
    height = 128

    start_time = time.time()

    if args.method == "direct":
        phase_map = cube_phase(width, height, points)

    elif args.method == "gs":
        target = cube_to_target(points, width, height)
        phase_map = gerchberg_saxton_2d(target, iterations=args.iterations)

    end_time = time.time()
    elapsed = end_time - start_time

    intensity = reconstruct_intensity_from_phase(phase_map)

    print("\n--- Performance Stats ---")
    print(f"Method: {args.method}")
    print(f"Points: {len(points)}")
    print(f"Resolution: {width}x{height}")

    if args.method == "gs":
        print(f"Iterations: {args.iterations}")
        print(f"Time per iteration: {elapsed / args.iterations:.6f} s")

    print(f"Total time: {elapsed:.4f} s")
    print("------------------------\n")

    # -----------------------------
    # Plotting
    # -----------------------------
    fig = make_subplots(
        rows=1, cols=3,
        specs=[[{"type": "scatter3d"}, {"type": "surface"}, {"type": "surface"}]],
        subplot_titles=(
            "3D Cube (Point Cloud)",
            "SLM Phase Map",
            "Reconstructed Intensity (Far Field)"
        )
    )

    # Cube plot
    fig.add_trace(
        go.Scatter3d(
            x=points[:, 0],
            y=points[:, 1],
            z=points[:, 2],
            mode='markers',
            marker=dict(size=3)
        ),
        row=1, col=1
    )

    # Phase surface (scaled by pi)
    fig.add_trace(
        go.Surface(
            z=phase_map / np.pi,
            colorscale='HSV'
        ),
        row=1, col=2
    )

    # Reconstructed
    fig.add_trace(
        go.Surface(
            z=intensity,
            colorscale='Viridis'
        ),
        row=1, col=3
    )

    fig.update_layout(
        title="SLM Cube Projection Visualization",
        showlegend=False,
        scene=dict(aspectmode='cube'),
        scene2=dict(aspectmode='cube'),
        scene3=dict(aspectmode='cube')
    )

    fig.show()


if __name__ == "__main__":
    main()
