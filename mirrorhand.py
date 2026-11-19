"""Driver that opens/closes an RMTC_GLOVE based on the RMS envelope.

Flow: connect via GloveLink -> wait for the 'device' beacon -> RMTC_GLOVE\r (immediately)
      -> re-send DATA:v:...\\r as keepalive (closed=100, open=10)

Thresholds are measured at startup by calibrate.AdaptiveThreshold (rest -> activity order).
Nothing moves until calibration is complete.
"""
from calibrate import AdaptiveThreshold
from release_debounce import DEFAULT_RELEASE_FRAMES, ReleaseDebounce
from mirrorhand_link import CLOSE, OPEN, GloveLink


class MirrorHand:
    def __init__(self, port="/dev/ttyUSB1", baudrate=57600,
                 release_frames=DEFAULT_RELEASE_FRAMES):
        self.port = port
        self.baudrate = baudrate
        self.release_debounce = ReleaseDebounce(frames=release_frames)
        self.link = None
        self.closed = False
        self.calib = AdaptiveThreshold()  # collect in the order: rest -> activity

    @property
    def ser(self):
        """Backward-compatible access (None if not connected)."""
        return self.link.ser if self.link is not None else None

    @property
    def last_send(self):
        """Backward-compatible access (0.0 if not connected)."""
        return self.link.last_send if self.link is not None else 0.0

    def connect(self):
        self.link = GloveLink(self.port, self.baudrate)
        print("[mirrorhand] press MIRROR GUIDE -> START on the glove body, in this order.", flush=True)
        if not self.link.wait_for_beacon():
            raise SystemExit("[mirrorhand] 'device' not received. Check the mode settings on the glove body.")
        self.link.write("RMTC_GLOVE\r")              # handshake immediately upon detection
        self.closed = False
        self._send_all(OPEN)                          # stay open initially
        # keep re-sending so the connection does not drop after the handshake
        self.link.start_keepalive(lambda: CLOSE if self.closed else OPEN)
        print(f"[mirrorhand] connected on {self.port}", flush=True)

    def _send_all(self, value):
        if self.link is not None:
            self.link.send_all(value)

    def update(self, rms_uv):
        """Receive the RMS [µV] and open/close the hand. Returns True if closed."""
        if self.link is None:
            return False
        if not self.calib.ready:              # do nothing while calibrating
            self.calib.push(rms_uv)
            return False
        if rms_uv >= self.calib.artifact_th:  # do not close on artefacts (fail-safe)
            if self.closed:
                self._transition(False, rms_uv, "ARTIFACT → OPEN")
            return False
        if self.closed:
            # do not OPEN until rms stays at/below release_th for release_frames consecutive samples
            if self.release_debounce.push(rms_uv <= self.calib.release_th):
                self._transition(False, rms_uv, "OPEN")
        else:
            if rms_uv >= self.calib.grip_th:
                self.release_debounce.reset()   # re-arm the counter when gripping begins
                self._transition(True, rms_uv, "CLOSE")
        return self.closed

    def _transition(self, closed, rms_uv, label):
        self.closed = closed
        self._send_all(CLOSE if closed else OPEN)
        print(f"[mirrorhand] {label} (rms={rms_uv:.2f})")

    def close(self):
        if self.link is None:
            return
        self.link.stop_keepalive()
        try:
            self._send_all(OPEN)              # leave the hand open on exit
        except Exception:
            pass
        self.link.close()
        self.link = None
