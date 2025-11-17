import bisect
import numpy as np
from typing import List, Tuple, Dict, Any

def initial_scale_offset_from_stats(A: List[float], B: List[float]) -> Tuple[float, float]:
    """
    Fast initial guess for scale s and offset t using statistics:
        s ≈ std(B) / std(A)
        t ≈ median(B) - s * median(A)
    """
    A_arr = np.array(A, dtype=float)
    B_arr = np.array(B, dtype=float)

    # Guard against degenerate std
    std_A = np.std(A_arr)
    std_B = np.std(B_arr)
    if std_A == 0:
        s0 = 1.0
    else:
        s0 = std_B / std_A

    t0 = np.median(B_arr) - s0 * np.median(A_arr)
    return s0, t0


def score_model(A: List[float], B: List[float], s: float, t: float, tol: float) -> int:
    """
    Count how many A points have a matching B within tolerance
    under model B ≈ s*A + t.
    """
    inliers = 0
    for a in A:
        b_pred = s * a + t
        j = bisect.bisect_left(B, b_pred)

        candidates = []
        if j < len(B):
            candidates.append(B[j])
        if j > 0:
            candidates.append(B[j - 1])

        if any(abs(b - b_pred) <= tol for b in candidates):
            inliers += 1

    return inliers


def refine_scale_offset_local(
    A: List[float],
    B: List[float],
    s0: float,
    t0: float,
    tol: float = 2.0,
    s_rel_range: float = 0.1,
    s_steps: int = 7,
    t_abs_range: float = 5.0,
    t_steps: int = 9,
) -> Tuple[float, float]:
    """
    Do a small grid search around (s0, t0) to improve them.
    This is MUCH cheaper than blind RANSAC over all scales.
    """

    best_s, best_t = s0, t0
    best_score = score_model(A, B, s0, t0, tol)

    # Grid around s0: e.g. ±10% by default
    s_min = s0 * (1.0 - s_rel_range)
    s_max = s0 * (1.0 + s_rel_range)

    # Grid around t0: e.g. ±5 units
    t_min = t0 - t_abs_range
    t_max = t0 + t_abs_range

    for si in np.linspace(s_min, s_max, s_steps):
        for ti in np.linspace(t_min, t_max, t_steps):
            score = score_model(A, B, si, ti, tol)
            if score > best_score:
                best_score = score
                best_s, best_t = si, ti

    return best_s, best_t


def align_with_scale_offset(
    A: List[float],
    B: List[float],
    s: float,
    t: float,
    tol: float = 2.0,
) -> Dict[str, Any]:
    """
    Given scale s and offset t (B ≈ s*A + t),
    align A and B and return matches + unmatched.
    """
    i = 0
    j = 0
    matched: List[Tuple[float, float]] = []
    unmatched_A: List[float] = []
    unmatched_B: List[float] = []

    while i < len(A) and j < len(B):
        b_pred = s * A[i] + t
        diff = B[j] - b_pred

        if abs(diff) <= tol:
            matched.append((A[i], B[j]))
            i += 1
            j += 1
        elif diff > 0:
            # Predicted B is smaller than actual B[j] by more than tol
            unmatched_A.append(A[i])
            i += 1
        else:
            # Predicted B is larger than B[j] by more than tol
            unmatched_B.append(B[j])
            j += 1

    unmatched_A.extend(A[i:])
    unmatched_B.extend(B[j:])

    return {
        "matched": matched,
        "unmatched_A": unmatched_A,
        "unmatched_B": unmatched_B,
        "s": s,
        "t": t,
    }


# ---------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------
if __name__ == "__main__":
    A = [1, 2, 5, 6, 8, 9]
    B = [29, 41, 51, 69, 79, 101, 111]   # noisy, scaled+shifted-ish

    # 1. Fast statistical guess
    s0, t0 = initial_scale_offset_from_stats(A, B)
    print(f"Initial guess: s0={s0:.4f}, t0={t0:.4f}")

    # 2. Local refinement around that guess
    s, t = refine_scale_offset_local(A, B, s0, t0, tol=2.0)
    print(f"Refined model: s={s:.4f}, t={t:.4f}")

    # 3. Align based on refined model
    result = align_with_scale_offset(A, B, s, t, tol=2.0)

    print("Matched pairs:")
    for a, b in result["matched"]:
        print(f"  A={a}  ↔  B={b}")

    print("Unmatched A:", result["unmatched_A"])
    print("Unmatched B:", result["unmatched_B"])
