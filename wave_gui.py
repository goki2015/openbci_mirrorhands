"""Simple live display of OpenBCI waveforms with matplotlib (only with `main.py --gui`).

Scrolls the raw waveform (EXG Ch0), the filtered waveform and the RMS envelope.

Notes:
  - Each redraw just hands control back to the event loop, so updates to the
    glove are not blocked in general. The loop may get slower though, because
    of the GUI drawing (omit --gui if real-time performance matters).
  - Redraws at refresh_s intervals, showing up to seconds of history.
"""
import time
from collections import deque

import matplotlib.pyplot as plt


class LiveWave:
    """Scrolling live plotter (3 rows: Raw / Filtered / RMS)."""

    def __init__(self, fs=250.0, seconds=10.0, refresh_s=0.05):
        self.fs = fs
        self.refresh_s = refresh_s
        maxlen = max(1, int(fs * seconds))
        self.t = deque(maxlen=maxlen)
        self.raw = deque(maxlen=maxlen)
        self.filtered = deque(maxlen=maxlen)
        self.rms = deque(maxlen=maxlen)
        self.sample_count = 0
        self.last_draw = 0.0

        self.fig, self.axes = plt.subplots(3, 1, sharex=True, figsize=(10, 7))
        self.fig.suptitle("OpenBCI EXG Ch0 (--gui)")
        self.status = self.fig.text(0.99, 0.99, "", ha="right", va="top", fontsize=9)
        self.line_raw, = self.axes[0].plot([], [], color="tab:gray", lw=0.8)
        self.axes[0].set_ylabel("Raw [µV]")
        self.line_flt, = self.axes[1].plot([], [], color="tab:blue", lw=0.8)
        self.axes[1].set_ylabel("Filtered [µV]")
        self.line_rms, = self.axes[2].plot([], [], color="tab:red", lw=0.8)
        self.axes[2].set_ylabel("RMS [µV]")
        self.axes[2].set_xlabel("Time [s]")
        for ax in self.axes:
            ax.grid(True)
        self.fig.tight_layout()

        plt.ion()
        plt.show()

    def set_status(self, text):
        """Update the status line at the top-right of the window."""
        self.status.set_text(text)

    def is_open(self):
        """Returns False if the window has been closed."""
        return plt.fignum_exists(self.fig.number)

    def push(self, raw, filtered, rms):
        """Append one sample to the buffer (no redraw)."""
        self.sample_count += 1
        self.t.append(self.sample_count / self.fs)
        self.raw.append(raw)
        self.filtered.append(filtered)
        self.rms.append(rms)

    def maybe_redraw(self):
        """Redraw if refresh_s has elapsed."""
        now = time.time()
        if now - self.last_draw < self.refresh_s:
            return
        self.last_draw = now
        t = list(self.t)
        lines = ((self.line_raw, self.raw), (self.line_flt, self.filtered), (self.line_rms, self.rms))
        for line, data in lines:
            line.set_data(t, list(data))
        if t and t[-1] > t[0]:
            for ax in self.axes:
                ax.set_xlim(t[0], t[-1])
            for ax in self.axes:
                ax.relim()
                ax.autoscale_view(scalex=False, scaley=True)
        plt.pause(0.001)

    def close(self):
        """Close the window."""
        plt.ioff()
        plt.close(self.fig)
