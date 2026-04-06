import argparse
import numpy as np
import cv2


# -----------------------------
# Utility functions
# -----------------------------
def center_crop_square(img):
    h, w = img.shape[:2]
    size = min(h, w)
    y = (h - size) // 2
    x = (w - size) // 2
    return img[y:y+size, x:x+size]


def fft2c(img):
    return np.fft.fftshift(np.fft.fft2(img))


def ifft2c(freq):
    return np.fft.ifft2(np.fft.ifftshift(freq))


def normalize_for_display(img):
    img = np.abs(img)
    img = np.log1p(img)
    img = img / np.max(img)
    return img


def load_rgb_image(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Failed to load image: {path}")

    # BGR → RGB
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # uint8 [0,255] → float32 [0,1]
    img = img.astype(np.float32) / 255.0

    return img


def show_rgb(title, img):
    # clip just in case FFT math went spicy 🌶️
    img = np.clip(img, 0.0, 1.0)

    # float [0,1] → uint8 [0,255]
    img_u8 = (img * 255).astype(np.uint8)

    # RGB → BGR for OpenCV
    img_bgr = cv2.cvtColor(img_u8, cv2.COLOR_RGB2BGR)

    cv2.imshow(title, img_bgr)


def percent_to_pixels(shift_percent, size):
    return int((shift_percent / 100.0) * size)


def shift_fft(f, shift_x, shift_y):
    h, w = f.shape

    sx = percent_to_pixels(shift_x, w)
    sy = percent_to_pixels(shift_y, h)

    # Note: axis 1 = x (cols), axis 0 = y (rows)
    f_shifted = np.roll(f, shift=sy, axis=0)
    f_shifted = np.roll(f_shifted, shift=sx, axis=1)

    return f_shifted


# -----------------------------
# Procedural masks
# -----------------------------
def generate_mask(name, size):
    mask = np.ones((size, size), dtype=np.float32)
    cx, cy = size // 2, size // 2

    Y, X = np.ogrid[:size, :size]
    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)

    if name == "LPF":
        mask[:] = 0
        mask[dist < size * 0.1] = 1

    elif name == "HPF":
        mask[:] = 1
        mask[dist < size * 0.2] = 0

    elif name == "crossbar":
        thickness = int(size * 0.02)
        mask[:, cx - thickness:cx + thickness] = 0
        mask[cy - thickness:cy + thickness, :] = 0
        mask[dist < size * 0.1] = 1

    elif name == "ring":
        mask[:] = 0
        mask[(dist > size * 0.15) & (dist < size * 0.3)] = 1

    elif name == "diag":
        thickness = int(size * 0.02)
        for i in range(size):
            mask[max(0, i-thickness):min(size, i+thickness), i] = 0
            mask[max(0, size-i-thickness):min(size, size-i+thickness), i] = 0

    elif name == "notch":
        mask[:] = 1
        mask[cy-5:cy+5, cx+50:cx+60] = 0  # remove specific frequency

    else:
        raise ValueError(f"Unknown mask keyword: {name}")

    return mask


# -----------------------------
# Main processing
# -----------------------------
def process_rgb(img, mask, shift_x, shift_y):
    channels = cv2.split(img)
    fft_channels = []
    fft_filtered = []
    result_channels = []

    for ch in channels:
        f = fft2c(ch)
        f = shift_fft(f, shift_x, shift_y)

        fft_channels.append(f)

        f_filtered = f * mask
        fft_filtered.append(f_filtered)

        img_back = ifft2c(f_filtered)
        result_channels.append(np.abs(img_back))

    return fft_channels, fft_filtered, cv2.merge(result_channels)


def process_gray(img, mask, shift_x, shift_y):
    f = fft2c(img)
    f = shift_fft(f, shift_x, shift_y)
    f_filtered = f * mask
    result = np.abs(ifft2c(f_filtered))
    return f, f_filtered, result


# -----------------------------
# Matching visualization
# -----------------------------
def matching_overlay(freq, mask):
    freq_norm = normalize_for_display(freq)
    mask_norm = mask

    mismatch = np.abs(freq_norm - mask_norm)
    mismatch = mismatch > 0.5

    overlay = np.dstack([freq_norm]*3)
    overlay[mismatch] = [1, 0, 0]  # red

    return overlay


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--mask", default=None)
    parser.add_argument("--match", action="store_true")

    parser.add_argument(
        "--shift_x",
        type=float,
        default=0.0,
        help="Shift the FT in X as percentage of image size (-100 to 100)"
    )

    parser.add_argument(
        "--shift_y",
        type=float,
        default=0.0,
        help="Shift the FT in Y as percentage of image size (-100 to 100)"
    )

    args = parser.parse_args()

    img = cv2.imread(args.input)
    img = center_crop_square(img)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    size = img.shape[0]

    # Mask handling
    if args.mask is None:
        mask = np.ones((size, size), dtype=np.float32)

    elif args.mask in ["LPF", "HPF", "crossbar", "ring", "diag", "notch"]:
        mask = generate_mask(args.mask, size)

    else:
        mask_img = cv2.imread(args.mask, cv2.IMREAD_GRAYSCALE)
        mask_img = center_crop_square(mask_img)
        mask = cv2.resize(mask_img, (size, size)) / 255.0

    # Matching mode
    if args.match:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        f, f_filtered, result = process_gray(gray, mask, args.shift_x, args.shift_y)

        overlay = matching_overlay(f, mask)

        cv2.imshow("Input", gray / 255.0)
        cv2.imshow("FFT", normalize_for_display(f))
        cv2.imshow("Filtered FFT", normalize_for_display(f_filtered))
        cv2.imshow("Matching Overlay", overlay)

    else:
        fft_ch, fft_filt, result = process_rgb(img, mask, args.shift_x, args.shift_y)

        fft_display = normalize_for_display(np.mean(np.abs(fft_ch), axis=0))
        fft_filt_display = normalize_for_display(np.mean(np.abs(fft_filt), axis=0))

        result = result / np.max(result)

        show_rgb("Input", img / 255.0)
        cv2.imshow("FFT (unfiltered)", fft_display)
        cv2.imshow("FFT (filtered)", fft_filt_display)
        show_rgb("Result", result)

    cv2.waitKey(0)


if __name__ == "__main__":
    main()
