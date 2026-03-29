import numpy as np
import cv2

MODES = ["beam", "lens", "vortex", "cube"]

def generate_phase_pattern(width, height, mode, angle_x, angle_y):
    x = np.linspace(-1, 1, width)
    y = np.linspace(-1, 1, height)
    xv, yv = np.meshgrid(x, y)

    if mode == "beam":
        phase = angle_x * xv + angle_y * yv

    elif mode == "lens":
        phase = (xv**2 + yv**2) * 10.0

    elif mode == "vortex":
        phase = np.arctan2(yv, xv)

    elif mode == "cube":
        points = generate_cube_points()
        phase = cube_phase(width, height, points)

    else:
        phase = np.zeros_like(xv)

    return phase


def simulate_slm(phase):
    field = np.exp(1j * phase)

    fft = np.fft.fftshift(np.fft.fft2(field))
    intensity = np.abs(fft) ** 2

    intensity /= np.max(intensity) + 1e-8

    # Log scaling for visibility
    intensity = np.log1p(10 * intensity) / np.log1p(10)

    return (intensity * 255).astype(np.uint8)


def cube_phase(width, height, points):
    x = np.linspace(-1, 1, width)
    y = np.linspace(-1, 1, height)
    xv, yv = np.meshgrid(x, y)

    field = np.zeros((height, width), dtype=np.complex64)

    for (px, py, pz) in points:
        # Perspective-ish projection
        scale = 1.0 / (pz + 2.0)

        kx = px * scale * 20
        ky = py * scale * 20

        phase = kx * xv + ky * yv

        field += np.exp(1j * phase)

    # Convert to phase-only SLM
    phase_only = np.angle(field)

    return phase_only


def generate_cube_points(size=0.8, resolution=12):
    points = []

    coords = np.linspace(-size, size, resolution)

    # Only edges of cube
    for x in coords:
        for y in coords:
            for z in coords:
                edge_count = sum([
                    abs(x) == size,
                    abs(y) == size,
                    abs(z) == size
                ])
                if edge_count >= 2:
                    points.append((x, y, z))

    return points


def print_state(action, mode, angle_x, angle_y):
    print(f"[{action}] Mode={mode} | angle_x={angle_x:.1f} | angle_y={angle_y:.1f}")


def main():
    width, height = 512, 512

    angle_x = 0.0
    angle_y = 0.0
    step = 5.0
    max_angle = 100.0

    mode_index = 0
    mode = MODES[mode_index]

    print("Controls: Arrow keys = steer | m = change mode | ESC = exit")
    print_state("INIT", mode, angle_x, angle_y)

    while True:
        phase = generate_phase_pattern(width, height, mode, angle_x, angle_y)
        image = simulate_slm(phase)

        cv2.imshow("SLM Simulator", image)

        key = cv2.waitKeyEx(0)

        if key == 27:  # ESC
            print("Exiting.")
            break

        elif key == ord('m'):
            mode_index = (mode_index + 1) % len(MODES)
            mode = MODES[mode_index]
            print_state("MODE CHANGE", mode, angle_x, angle_y)

        elif key == 2424832:  # LEFT
            angle_x = max(angle_x - step, -max_angle)
            print_state("LEFT", mode, angle_x, angle_y)

        elif key == 2555904:  # RIGHT
            angle_x = min(angle_x + step, max_angle)
            print_state("RIGHT", mode, angle_x, angle_y)

        elif key == 2490368:  # UP
            angle_y = max(angle_y - step, -max_angle)
            print_state("UP", mode, angle_x, angle_y)

        elif key == 2621440:  # DOWN
            angle_y = min(angle_y + step, max_angle)
            print_state("DOWN", mode, angle_x, angle_y)

        else:
            print(f"Unknown key: {key}")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
