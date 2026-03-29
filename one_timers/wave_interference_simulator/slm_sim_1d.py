import numpy as np
import cv2
import time
import argparse

def build_target(bits, N):
    chunks = len(bits)
    chunk_size = N // chunks

    target = np.zeros(N)

    for i, bit in enumerate(bits):
        if bit == '1':
            start = i * chunk_size
            end = start + chunk_size
            target[start:end] = 1.0

    return target


def gerchberg_saxton_1d(target, time_budget_sec=5, seed=0):
    """
    Gerchberg-Saxton with time budget instead of fixed iterations.

    Args:
        target: 1D array of desired intensity
        time_budget_sec: how long to run (seconds)
        seed: random seed for determinism

    Returns:
        phase array
    """

    np.random.seed(seed)

    N = len(target)

    # Initial random phase
    phase = np.random.rand(N) * 2 * np.pi
    field = np.exp(1j * phase)

    target_amp = np.sqrt(target)

    start_time = time.time()
    iterations = 0

    while True:
        # Check time
        if time.time() - start_time >= time_budget_sec:
            break

        # Forward transform
        spectrum = np.fft.fft(field)

        # Enforce target amplitude
        spectrum = target_amp * np.exp(1j * np.angle(spectrum))

        # Back transform
        field = np.fft.ifft(spectrum)

        # Enforce phase-only constraint
        field = np.exp(1j * np.angle(field))

        iterations += 1

    print(f"GS ran for {iterations} iterations in {time_budget_sec:.2f}s")

    return np.angle(field)


def generate_interference(frequency, phases, spacing, height, show_energy=False):
    num_slits = len(phases)

    width = int(height + (num_slits - 1) * spacing + height)

    x = np.arange(width)
    y = np.arange(height)
    xv, yv = np.meshgrid(x, y)

    k = 2 * np.pi / frequency

    total_wave = np.zeros((height, width), dtype=np.float32)

    for i in range(num_slits):
        slit_x = height + i * spacing
        slit_y = 0

        r = np.sqrt((xv - slit_x)**2 + (yv - slit_y)**2)

        phase = phases[i]
        wave = np.sin(k * r + phase)

        total_wave += wave

    if show_energy:
        total_wave = total_wave ** 2

    # Get extrema
    max_val = total_wave.max()
    min_val = total_wave.min()

    # Prepare HSV image
    hsv = np.zeros((height, width, 3), dtype=np.uint8)

    pos_mask = total_wave > 0
    neg_mask = total_wave < 0

    hsv[..., 0][pos_mask] = 0
    hsv[..., 0][neg_mask] = 60 if not show_energy else 0

    hsv[..., 1] = 255

    V = np.zeros_like(total_wave, dtype=np.float32)

    if max_val > 0:
        V[pos_mask] = total_wave[pos_mask] / max_val

    if min_val < 0:
        V[neg_mask] = np.abs(total_wave[neg_mask]) / abs(min_val)

    gamma = 2 if not show_energy else 1
    V = V ** gamma

    hsv[..., 2] = (V * 255).astype(np.uint8)

    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    bgr = np.flipud(bgr)

    return bgr


def simulate_interference(phases, height, frequency=5, spacing=1, show_energy=True):
    """
    Wrapper that feeds GS phases into the wave visualization.
    """

    return generate_interference(
        frequency=frequency,
        phases=phases,
        spacing=spacing,
        height=height,
        show_energy=show_energy
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bits", type=str, help="8-bit string like 10101010")
    args = parser.parse_args()

    assert len(args.bits) == 8 and all(c in "01" for c in args.bits)

    N = 32
    height = 300

    print(f"Encoding bits: {args.bits}")

    target = build_target(args.bits, N)

    phase = gerchberg_saxton_1d(target)

    image = simulate_interference(phase, height)

    # visualize target
    #target_vis = (target * 255).astype(np.uint8)
    #target_vis = cv2.resize(target_vis[np.newaxis, :], (N, 50), interpolation=cv2.INTER_NEAREST)

    #cv2.imshow("Target (desired far-field)", target_vis)
    cv2.imshow("Interference (waves doing the work)", image)

    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
