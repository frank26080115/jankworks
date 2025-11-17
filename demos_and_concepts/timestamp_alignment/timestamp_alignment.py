from collections import Counter
import bisect
import numpy as np

def estimate_offset(A, B, tolerance=2.0):
    """
    Estimate the best offset Δ such that B ≈ A + Δ.
    Uses RANSAC-like voting on all pairwise differences but 
    only between close-by values (to stay O(n)).
    
    A and B must be sorted.
    """

    deltas = []

    # For each A value, search for B values in a window to avoid full NxM
    # Using ±50 range (for example) to propose plausible offsets.
    # Increase if needed.
    search_window = 50

    for a in A:
        # We assume the true pair b is within a ± window (shift unknown)
        lo = bisect.bisect_left(B, a - search_window)
        hi = bisect.bisect_right(B, a + search_window)

        for b in B[lo:hi]:
            deltas.append(b - a)

    # Cluster deltas using histogram (bin at tolerance resolution)
    # This gives robustness to noise.
    binned = [round(d / tolerance) * tolerance for d in deltas]
    counts = Counter(binned)

    # Most common bin is our offset
    best_delta = counts.most_common(1)[0][0]
    return best_delta


def align_with_offset(A, B, delta, tolerance=2.0):
    """
    Given offset delta, align elements of A to B.
    Return lists of matched pairs and unmatched elements.
    """

    i = 0
    j = 0
    matched = []
    unmatched_A = []
    unmatched_B = []

    while i < len(A) and j < len(B):
        shifted = A[i] + delta
        diff = B[j] - shifted

        if abs(diff) <= tolerance:
            # match found
            matched.append((A[i], B[j]))
            i += 1
            j += 1
        elif diff > 0:
            # A[i]+delta < B[j] - tolerance → A[i] unmatched
            unmatched_A.append(A[i])
            i += 1
        else:
            # A[i]+delta > B[j] + tolerance → B[j] unmatched
            unmatched_B.append(B[j])
            j += 1

    # Remaining unmatched
    unmatched_A.extend(A[i:])
    unmatched_B.extend(B[j:])

    return matched, unmatched_A, unmatched_B


# ---------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------

A = [10, 20, 50, 60, 80, 90]
B = [29, 41, 51, 69, 79, 101, 111]   # noisy version

# 1. Estimate offset
delta = estimate_offset(A, B, tolerance=2.0)
print("Estimated offset Δ:", delta)

# 2. Align using the discovered offset
matched, unmatched_A, unmatched_B = align_with_offset(A, B, delta, tolerance=2.0)

print("Matched pairs:")
for a, b in matched:
    print(f"  {a}  ↔  {b}")

print("Unmatched A:", unmatched_A)
print("Unmatched B:", unmatched_B)
