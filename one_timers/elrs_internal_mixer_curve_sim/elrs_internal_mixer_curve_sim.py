#!/usr/bin/env python3
"""
Plot a joystick-style output curve over X = -10000 .. 10000.

Pipeline order:
1) deadzone
2) output exponential curve
3) output scale
4) output offset
5) anti-deadzone

Notes:
- This is written to be easy to port to C.
- Each math step has comments showing the straightforward C equivalent.
- The deadzone implementation below zeros the center, then linearly remaps the
  remaining range back to full scale. That is usually the nicest behavior for control inputs.
"""

import argparse
import math
import matplotlib.pyplot as plt


INPUT_MAX = 10000
INPUT_MIN = -10000


def clamp_int(v: int, lo: int, hi: int) -> int:
    # C equivalent:
    # if (v < lo) return lo;
    # if (v > hi) return hi;
    # return v;
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def clamp_float(v: float, lo: float, hi: float) -> float:
    # C equivalent:
    # if (v < lo) return lo;
    # if (v > hi) return hi;
    # return v;
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def sign_i(v: int) -> int:
    # C equivalent:
    # if (v > 0) return 1;
    # if (v < 0) return -1;
    # return 0;
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def apply_deadzone(x: int, deadzone: int) -> int:
    """
    Deadzone with rescaling:
    - |x| <= deadzone -> 0
    - outside deadzone, remap remaining travel back to full scale

    Example:
      deadzone = 1000
      x = 1000 -> 0
      x = 10000 -> 10000
    """
    # C equivalent:
    # int ax = (x >= 0) ? x : -x;
    ax = abs(x)

    if ax <= deadzone:
        return 0

    # Remaining input span after deadzone
    # C equivalent:
    # int remaining = INPUT_MAX - deadzone;
    remaining = INPUT_MAX - deadzone

    # Safety for pathological case
    if remaining <= 0:
        return 0

    # Normalize outside the deadzone back to full range
    # C equivalent:
    # int y = ((ax - deadzone) * INPUT_MAX) / remaining;
    y = ((ax - deadzone) * INPUT_MAX) // remaining

    # Restore sign
    # C equivalent:
    # return (x < 0) ? -y : y;
    return -y if x < 0 else y


def apply_expo(x: int, curve: float) -> int:
    """
    Exponential shaping on the range -10000..10000.

    The base equation over 0..1 is:
        y = x * exp(x * c) / exp(c)

    We apply it to |x| normalized to 0..1, then mirror the sign.

    For negative curve values:
    - we DO NOT calculate using negative c
    - instead, calculate using positive |c|, then flip it around the linear line:
          y_neg = 1 - y_pos(1 - t)
      This gives the opposite bend while only ever using positive c.
    """
    if x == 0:
        return 0

    # Clamp curve to requested range
    # C equivalent:
    # if (curve < -10.0f) curve = -10.0f;
    # if (curve >  10.0f) curve =  10.0f;
    curve = clamp_float(curve, -10.0, 10.0)

    s = sign_i(x)
    ax = abs(x)

    # Normalize to 0..1
    # C equivalent:
    # float t = (float)ax / 10000.0f;
    t = ax / float(INPUT_MAX)

    # Always use positive c for the actual exponential calculation
    # C equivalent:
    # float c = (curve < 0.0f) ? -curve : curve;
    c = abs(curve)

    if c == 0.0:
        shaped = t
    else:
        # Positive-curve shape:
        # y = t * exp(t*c) / exp(c)
        #
        # C equivalent:
        # float y_pos = t * expf(t * c) / expf(c);
        y_pos = t * math.exp(t * c) / math.exp(c)

        if curve >= 0.0:
            shaped = y_pos
        else:
            # "Flipped" version without using negative c:
            # y_neg(t) = 1 - y_pos(1 - t)
            #
            # C equivalent:
            # float u = 1.0f - t;
            # float y_u = u * expf(u * c) / expf(c);
            # shaped = 1.0f - y_u;
            u = 1.0 - t
            y_u = u * math.exp(u * c) / math.exp(c)
            shaped = 1.0 - y_u

    # Convert back to 0..10000 and restore sign
    # C equivalent:
    # int y = (int)lroundf(shaped * 10000.0f);
    y = int(round(shaped * INPUT_MAX))
    return s * y


def apply_scale(x: int, scale_percent: float) -> int:
    """
    Scale output by 0..100 percent.
    """
    scale_percent = clamp_float(scale_percent, 0.0, 10000.0)

    # C equivalent:
    # int y = (int)lroundf((float)x * (scale_percent / 100.0f));
    y = int(round(x * (scale_percent / 100.0)))
    return y


def apply_offset(x: int, offset: int) -> int:
    """
    Add raw offset in the same -10000..10000 style units.
    """
    # C equivalent:
    # int y = x + offset;
    y = x + offset
    return clamp_int(y, INPUT_MIN, INPUT_MAX)


def apply_anti_deadzone(x: int, anti_deadzone: int) -> int:
    """
    If output is non-zero, add anti-deadzone in the output direction.
    This helps punch through a downstream deadzone.
    """
    anti_deadzone = clamp_int(anti_deadzone, 0, INPUT_MAX)

    if x == 0:
        return 0

    # C equivalent:
    # if (x > 0) x += anti_deadzone;
    # else       x -= anti_deadzone;
    y = x + anti_deadzone if x > 0 else x - anti_deadzone
    return clamp_int(y, INPUT_MIN, INPUT_MAX)


def output_curve(
    x: int,
    deadzone: int,
    curve: float,
    scale_percent: float,
    offset: int,
    anti_deadzone: int,
) -> int:
    """
    Full pipeline:
    deadzone -> expo -> scale -> offset -> anti-deadzone
    """
    # C equivalent:
    # x = apply_deadzone(x, deadzone);
    x = apply_deadzone(x, deadzone)

    # x = apply_expo(x, curve);
    x = apply_expo(x, curve)

    # x = apply_scale(x, scale_percent);
    x = apply_scale(x, scale_percent)

    # x = apply_offset(x, offset);
    x = apply_offset(x, offset)

    # x = apply_anti_deadzone(x, anti_deadzone);
    x = apply_anti_deadzone(x, anti_deadzone)

    # Final clamp just to be safe
    # C equivalent:
    # x = clamp_int(x, -10000, 10000);
    x = clamp_int(x, INPUT_MIN, INPUT_MAX)

    return x


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot the output curve for X in -10000..10000."
    )
    parser.add_argument(
        "--deadzone",
        type=int,
        default=0,
        help="Input deadzone in raw units, 0..10000",
    )
    parser.add_argument(
        "--curve",
        type=float,
        default=0.0,
        help="Expo curve parameter, -10..10",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=100.0,
        help="Output scale in percent, 0..100",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Output offset in raw units, typically around -10000..10000",
    )
    parser.add_argument(
        "--anti-deadzone",
        dest="anti_deadzone",
        type=int,
        default=0,
        help="Anti-deadzone in raw units, 0..10000",
    )

    args = parser.parse_args()

    deadzone = clamp_int(args.deadzone, 0, INPUT_MAX)
    curve = clamp_float(args.curve, -10.0, 10.0)
    scale = clamp_float(args.scale, 0.0, 100.0)
    offset = clamp_int(args.offset, INPUT_MIN, INPUT_MAX)
    anti_deadzone = clamp_int(args.anti_deadzone, 0, INPUT_MAX)

    xs = list(range(INPUT_MIN, INPUT_MAX + 1))
    ys = [
        output_curve(x, deadzone, curve, scale, offset, anti_deadzone)
        for x in xs
    ]

    # 800-pixel wide window: 8 inches * 100 DPI = 800 px
    plt.figure(figsize=(8, 6), dpi=100)
    plt.plot(xs, ys)
    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.xlim(INPUT_MIN, INPUT_MAX)
    plt.ylim(INPUT_MIN, INPUT_MAX)
    plt.xlabel("Input X")
    plt.ylabel("Output Y")
    plt.title(
        f"deadzone={deadzone}, curve={curve}, scale={scale}%, "
        f"offset={offset}, anti_deadzone={anti_deadzone}"
    )
    plt.grid(True)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
