import cv2
import numpy as np

def load_template_with_mask(template_path):
    template = cv2.imread(template_path, cv2.IMREAD_UNCHANGED)
    assert template.shape[2] == 4, "Template must have an alpha channel."

    alpha = template[:, :, 3]
    mask = alpha > 0
    gray_template = cv2.cvtColor(template[:, :, :3], cv2.COLOR_BGR2GRAY)
    return gray_template, mask.astype(np.uint8) * 255

def detect_and_match(template, template_mask, photo):
    orb = cv2.ORB_create(5000)

    kp1, des1 = orb.detectAndCompute(template, template_mask)
    kp2, des2 = orb.detectAndCompute(photo, None)

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    raw_matches = bf.match(des1, des2)

    # Filter by distance
    good_matches = [m for m in raw_matches if m.distance < 40]

    if len(good_matches) < 10:
        raise Exception("Not enough good matches found. Got only %d." % len(good_matches))

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1,1,2)
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1,1,2)

    H, inlier_mask = cv2.findHomography(pts1, pts2, cv2.RANSAC, 5.0)

    num_inliers = np.sum(inlier_mask)
    if num_inliers < 15:
        raise Exception(f"Insufficient inliers after RANSAC: {num_inliers}")

    return H, inlier_mask, kp1, kp2, good_matches

def extract_matching_region(photo, template_shape, H):
    h, w = template_shape
    template_box = np.zeros((h, w), dtype=np.uint8)
    template_box[:] = 255

    warped_mask = cv2.warpPerspective(template_box, H, (photo.shape[1], photo.shape[0]))

    # Extract region from photo
    region_only = np.zeros_like(photo)
    for c in range(photo.shape[2]):
        region_only[:, :, c] = cv2.bitwise_and(photo[:, :, c], warped_mask)

    return region_only, warped_mask

def warp_back_to_template(photo, H, template_shape):
    warped = cv2.warpPerspective(photo, np.linalg.inv(H), (template_shape[1], template_shape[0]))
    return warped

def black_out_match(photo, mask):
    inverted_mask = cv2.bitwise_not(mask)
    blacked = np.zeros_like(photo)
    for c in range(photo.shape[2]):
        blacked[:, :, c] = cv2.bitwise_and(photo[:, :, c], inverted_mask)
    return blacked

# ===== Main =====
template_path = "template.png"
photo_path = "photo.jpg"

template, template_mask = load_template_with_mask(template_path)
photo = cv2.imread(photo_path)

try:
    H, inlier_mask, kp1, kp2, good_matches = detect_and_match(template, template_mask, photo)
    matched_region, warped_mask = extract_matching_region(photo, template.shape, H)
    aligned = warp_back_to_template(photo, H, template.shape)
    photo_masked = black_out_match(photo, warped_mask)

    cv2.imwrite("match_masked.png", matched_region)
    cv2.imwrite("match_aligned.png", aligned)
    cv2.imwrite("match_blacked_out.png", photo_masked)

    print("✅ Done. Outputs:")
    print("- match_masked.png (only matching region visible)")
    print("- match_aligned.png (matching region warped to align with template)")
    print("- match_blacked_out.png (original photo with matching region masked out)")

except Exception as e:
    print(f"❌ Match failed: {e!r}")
