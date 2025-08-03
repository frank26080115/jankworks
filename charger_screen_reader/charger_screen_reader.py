import cv2
import numpy as np
import pytesseract

# ⚙️ REQUIRED ONCE: Path to your installed Tesseract (for Windows)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# === Step 1: Crop full screen area ===
#def crop_screen_region(image):
#    # ⚠️ Replace with actual pixel values
#    x, y, w, h = 100, 200, 400, 100  # Example values
#    return image[y:y+h, x:x+w]

def crop_screen_region(image, mask_path):
    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    assert mask is not None, "Mask image not found"
    assert image.shape[:2] == mask.shape, "Mask and image must be the same size"

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if len(contours) != 1:
        raise ValueError("Expected exactly one white rectangle in the mask.")

    x, y, w, h = cv2.boundingRect(contours[0])
    return image[y:y+h, x:x+w]


# === Step 2: Split screen into two halves ===
def split_dual_screen(screen_image):
    h, w = screen_image.shape[:2]
    left = screen_image[:, :w // 2]
    right = screen_image[:, w // 2:]
    return left, right

# === Step 3: Mask-based region extractor ===
def extract_text_regions(image_half, mask_path):
    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    if mask.shape != image_half.shape[:2]:
        print("⚠️  Resizing mask to match image dimensions...")
        mask = cv2.resize(mask, (image_half.shape[1], image_half.shape[0]), interpolation=cv2.INTER_NEAREST)

    # Find white rectangles in the mask
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cropped_regions = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        cropped = image_half[y:y+h, x:x+w]
        cropped_regions.append(cropped)
    return cropped_regions

# === Step 4: Run OCR on a list of cropped regions ===
def run_ocr_on_regions(region_images):
    results = []
    for img in region_images:
        # Optional pre-processing: convert to grayscale, threshold, etc.
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray, config="--psm 6")
        results.append(text.strip())
    return results

# === EXAMPLE USAGE ===
def main():
    full_image = cv2.imread("match_aligned.png")
    mask_path = "text_masks.png"  # Matches dimensions of each half screen

    #screen = crop_screen_region(full_image)
    screen = crop_screen_region(full_image, "screen_mask.png")
    left_half, right_half = split_dual_screen(screen)

    left_regions = extract_text_regions(left_half, mask_path)
    right_regions = extract_text_regions(right_half, mask_path)

    left_text = run_ocr_on_regions(left_regions)
    right_text = run_ocr_on_regions(right_regions)

    print("📋 Left screen text:")
    for text in left_text:
        print("-", text)

    print("\n📋 Right screen text:")
    for text in right_text:
        print("-", text)

if __name__ == "__main__":
    main()
