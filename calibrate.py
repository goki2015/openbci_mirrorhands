"""Adaptive threshold modelled after the emg-calibration in read_from_cython.

Collects RMS envelope samples in the order: rest phase -> activity phase:
  1. Migration: discard the start-up transient (measurements begin after flush_samples samples are discarded)
  2. Rest phase: collect for rest_s seconds
  3. Wait for Enter -> start discard timer (grip measurement begins after flush_samples samples are discarded)
  4. Activity phase: collect for grip_s seconds
  5. Fix the thresholds with a clamped geometric mean and set ready=True

Clamp: the threshold is never placed below rest_p90 x 1.5 regardless of other parameters
(so the device cannot run with an invalid calibration).

Usage:
    from calibrate import AdaptiveThreshold
    cal = AdaptiveThreshold()
    cal.push(env)
    if cal.ready:
        cal.grip_th, cal.release_th, cal.artifact_th
"""

import math


def percentile(values, p):
    """Percentile with linear interpolation. Returns 0.0 if empty."""
    if not values:
        return 0.0
    v = sorted(values)
    idx = (p / 100.0) * (len(v) - 1)
    lo = int(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return v[lo]
    return v[lo] + (v[hi] - v[lo]) * (idx - lo)


class AdaptiveThreshold:
    """Adaptive threshold calculator; collect in the order: rest -> activity."""

    def __init__(self, fs=250.0, rest_s=6.0, grip_s=6.0,
                 release_ratio=0.4, artifact_ratio=4.0, threshold_bias=0.0,
                 interactive=True, flush_samples=250):
        self.rest_n = max(1, int(fs * rest_s))
        self.grip_n = max(1, int(fs * grip_s))
        self.release_ratio = release_ratio
        self.artifact_ratio = artifact_ratio
        self.threshold_bias = threshold_bias
        self.interactive = interactive
        self.flush_left = flush_samples     # discard the start-up transient
        self.flush_samples = flush_samples
        self.rest = []
        self.grip = []
        self.ready = False
        self.valid = False
        self.grip_th = 30.0
        self.release_th = 15.0
        self.artifact_th = 200.0

    def push(self, env):
        """Push one RMS envelope sample [uVrms]. Does nothing after completion."""
        if self.ready:
            return
        if self.flush_left > 0:              # discard the transient interval
            self.flush_left -= 1
            return
        if len(self.rest) < self.rest_n:
            self.rest.append(env)
            if len(self.rest) == self.rest_n:
                rest_med = max(percentile(self.rest, 50.0), 1e-6)
                print(f"[calib] rest_med = {rest_med:.2f} µV", flush=True)
                if self.interactive:
                    print("[calib] Keep gripping hard and press Enter -> ", flush=True, end="")
                    try:
                        input()
                    except EOFError:
                        pass
                    print("[calib] Discarding the 1 s backlog buffer, then resuming measurement", flush=True)
                self.flush_left = self.flush_samples    # discard the backlog while waiting for Enter
            return
        self.grip.append(env)
        if len(self.grip) == self.grip_n:
            self._compute()

    def _compute(self):
        rest_med = max(percentile(self.rest, 50.0), 1e-6)   # take the value around the 50th percentile of rest; clamped to >= 1e-6
        grip_med = max(percentile(self.grip, 50.0), rest_med * 2.0)
        anchor = math.sqrt(rest_med * grip_med)
        rest_ub = max(percentile(self.rest, 90.0), 1e-6) # take the value around the 90th percentile of sorted self.rest; prefer 1e-6 (1 µV) if it is larger
        grip_lb = max(percentile(self.grip, 10.0), 1e-6)  # likewise, take the value around the 10th percentile of self.grip. No strong basis - 95-5 would be stricter and less stable, 85-15 looser
        gap_db = 20.0 * math.log10(grip_lb / rest_ub) # above 20 dB: good, above 10 dB: marginal, <= 0: suspicious

        # apply the bias shift only when gap > 0 (if negative, zero shift = keep anchor); shift by self.threshold_bias [dB]
        grip = anchor if gap_db <= 0.0 else anchor * 10.0 ** (self.threshold_bias * gap_db / 20.0)
        grip = max(grip, rest_ub * 1.5)            # never place it below the rest upper tail x 1.5

        self.grip_th = grip
        self.release_th = grip * self.release_ratio
        self.artifact_th = grip_med * self.artifact_ratio
        self.ready = True
        self.valid = (gap_db > 0.0)
        note = "" if self.valid else "  [WARN: gap<=0 - insufficient separation; running on anchor + clamp]"
        print(f"[calib] done: grip={grip:.4f} µV release={self.release_th:.4f} µV "
              f"artifact={self.artifact_th:.4f} µV gap={gap_db:+.2f} dB{note}", flush=True)
