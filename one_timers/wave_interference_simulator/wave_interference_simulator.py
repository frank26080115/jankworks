import os
import argparse
import numpy as np
import cv2

def generate_interference(frequency, num_slits, spacing, phase_step, height, init_phase = 0, show_energy = False, show_positive = False):
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

        phase = init_phase + ((i + 1) * phase_step)
        wave = np.sin(k * r + phase)

        if not show_positive:
            total_wave += wave
        else:
            total_wave += np.abs(wave)

    if show_energy:
        total_wave = total_wave ** 2

    # Get extrema
    max_val = total_wave.max()
    min_val = total_wave.min()

    # Prepare HSV image
    hsv = np.zeros((height, width, 3), dtype=np.uint8)

    # Masks
    pos_mask = total_wave > 0
    neg_mask = total_wave < 0

    # Hue: OpenCV uses 0–179
    # Red = 0, Green ≈ 60
    hsv[..., 0][pos_mask] = 0
    hsv[..., 0][neg_mask] = 60 if not show_energy else 0

    # Saturation = max
    hsv[..., 1] = 255

    
    # Normalize first
    V = np.zeros_like(total_wave, dtype=np.float32)

    if max_val > 0:
        V[pos_mask] = total_wave[pos_mask] / max_val

    if min_val < 0:
        V[neg_mask] = np.abs(total_wave[neg_mask]) / abs(min_val)

    # perceptual curve
    gamma = 2 if not show_energy else 1
    V = V ** gamma

    # Convert to 0–255
    hsv[..., 2] = (V * 255).astype(np.uint8)

    # Convert to BGR for saving/display
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    # Flip vertically to fix orientation
    bgr = np.flipud(bgr)

    filename = f"{frequency}-{num_slits}-{spacing}-{phase_step}-{height}.png"
    cv2.imwrite(filename, bgr)
    print(f"Saved {filename}")

    cv2.imshow("Interference Pattern", bgr)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="N-slit interference with signed HSV visualization.")
    parser.add_argument("frequency", type=float)
    parser.add_argument("num_slits", type=int)
    parser.add_argument("spacing", type=float)
    parser.add_argument("phase_step", type=float)
    parser.add_argument("height", type=int)
    parser.add_argument("--init-phase", type=float, default=0)
    parser.add_argument("--show-energy", action='store_true')
    parser.add_argument("--show-positive", action='store_true')

    args = parser.parse_args()

    generate_interference(
        args.frequency,
        args.num_slits,
        args.spacing,
        args.phase_step,
        args.height,
        args.init_phase,
        args.show_energy,
        args.show_positive
    )