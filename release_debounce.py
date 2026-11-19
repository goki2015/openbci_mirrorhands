"""Debounce for the release side (temporal stabilisation).

The EMG RMS may drop below release_th for just a single sample (a moment that
looks like rest). Sending OPEN at that exact moment would make the glove chatter,
so "OPEN is allowed only after release_th has been stayed below for frames
consecutive samples".

Usage (inside MirrorHand.update):

    if self.release_debounce.push(rms_uv <= release_th):
        ...  # opening the hand is allowed

- Passing True (below release_th) increments the counter by 1
- Passing False (above release_th) resets the counter to 0
- True is returned only after frames consecutive True samples
"""

DEFAULT_RELEASE_FRAMES = 30  # 0.12 s at 250 Hz sampling


class ReleaseDebounce:
    """Counts consecutive samples below release_th."""

    def __init__(self, frames=DEFAULT_RELEASE_FRAMES):
        # 1 is the minimum meaningful value - clamp to it
        self.frames = max(1, int(frames))
        self.count = 0

    def reset(self):
        """Reset the count to re-count from scratch (call right after CLOSE)."""
        self.count = 0

    def push(self, is_below_release):
        """Push one sample and return True if opening the hand is allowed.

        Args:
            is_below_release: True if this RMS is at/below release_th.

        Returns:
            True only if is_below_release has been True for frames consecutive samples.
        """
        if is_below_release:
            self.count += 1
        else:
            self.count = 0
        return self.count >= self.frames
