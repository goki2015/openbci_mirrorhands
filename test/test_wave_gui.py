"""OpenBCI (Cyton) operation check: view live EMG data in a GUI. The glove is not required.

Usage: uv run test/test_wave_gui.py [--port /dev/ttyUSB0] [--seconds 0] [--release-frames 30]

This runs the same pipeline as main.py (Cyton -> scipy filter -> RMS -> calibration ->
CLOSE/OPEN decision) but nothing is sent to the glove: a dummy FakeLink is plugged
into MirrorHand, so the beacon wait is skipped and the hand never moves.

GUI layout:
  Top:    Raw       ... raw EXG Ch0 waveform
  Middle: Filtered  ... after the 50/100 Hz notch and 5-110 Hz band-pass stages
  Bottom: RMS       ... 200 ms moving RMS envelope
  Status line (top right): n / rms / calibration progress (rest/grip counts),
    or closed / grip / release / artifact / dbc after calibration completes

Procedure:
  after launch, stay relaxed for ~6 s -> press Enter -> keep gripping hard for ~6 s
  (same calibration as main.py). Quit with Ctrl+C or by closing the window.
  A summary (decision count and timestamps) is printed on exit.
"""
import argparse
import sys
import time
from pathlib import Path

# Make the repository root importable when running as a script inside test/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams

from filter_module_scipy import StreamingFilter
from mirrorhand import CLOSE, OPEN, MirrorHand
from wave_gui import LiveWave


class FakeLink:
    """Pretend the glove is connected. Records packets instead of sending them."""

    def __init__(self):
        self.ser = None
        self.last_send = 0.0
        self.packets = []  # (t, value)

    def send_all(self, value):
        self.packets.append((time.time(), int(value)))

    def stop_keepalive(self):
        pass

    def close(self):
        pass


def status_text(hand, rms, n):
    cal = hand.calib
    if cal.ready:
        return (f"n={n} rms={rms:7.2f} closed={hand.closed} "
                f"grip={cal.grip_th:6.1f} rel={cal.release_th:6.1f} "
                f"art={cal.artifact_th:6.1f} dbc={hand.release_debounce.count}/{hand.release_debounce.frames}")
    return f"n={n} rms={rms:7.2f} [calibrating] rest={len(cal.rest)}/{cal.rest_n} grip={len(cal.grip)}/{cal.grip_n}"


def main():
    parser = argparse.ArgumentParser(description="View raw OpenBCI Cyton data in a GUI (glove not required)")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--seconds", type=float, default=0.0, help="0 means run until Ctrl+C or window close")
    parser.add_argument("--release-frames", type=int, default=30)
    args = parser.parse_args()

    BoardShim.disable_board_logger()
    board_id = BoardIds.CYTON_BOARD.value
    params = BrainFlowInputParams()
    params.serial_port = args.port
    params.timeout = 15
    board = BoardShim(board_id, params)
    board.prepare_session()
    fs = BoardShim.get_sampling_rate(board_id)
    ch = BoardShim.get_exg_channels(board_id)[0]

    hand = MirrorHand(port=args.port, release_frames=args.release_frames)
    hand.link = FakeLink()      # do not call connect() - skips the beacon wait
    hand.closed = False
    filt = StreamingFilter(fs=float(fs))
    wave = LiveWave(fs=float(fs))
    wave.set_status("connected - calibrating...")

    board.start_stream(45000)
    print("[verify] Streaming started. Stay relaxed for ~6 s, press Enter,", flush=True)
    print("[verify] then grip hard for ~6 s. Nothing is sent to the glove.", flush=True)
    print("[verify] Quit with Ctrl+C or by closing the window.", flush=True)

    n = 0
    rms = 0.0
    t0 = time.time()
    try:
        while True:
            if args.seconds > 0.0 and time.time() - t0 >= args.seconds:
                break
            if not wave.is_open():
                print("[verify] Window closed - exiting", flush=True)
                break
            data = board.get_board_data()
            if data.shape[1] == 0:
                time.sleep(1 / fs)
                wave.maybe_redraw()
                continue
            for v in data[ch]:
                v = float(v)
                fval, rms = filt.process(v)
                wave.push(v, fval, rms)
                hand.update(rms)
                n += 1
            wave.set_status(status_text(hand, rms, n))
            wave.maybe_redraw()
    except KeyboardInterrupt:
        print("[verify] Interrupted by Ctrl+C", flush=True)
    finally:
        board.stop_stream()
        board.release_session()
        wave.close()
        print("===== summary =====", flush=True)
        print(f" samples: {n}", flush=True)
        print(f" bad_samples: {filt.bad_samples}", flush=True)
        cal = hand.calib
        if cal.ready:
            print(f" calibration: grip={cal.grip_th:.4f} release={cal.release_th:.4f} "
                  f"artifact={cal.artifact_th:.4f} valid={cal.valid}", flush=True)
        else:
            print(" calibration: not finished", flush=True)
        closes = sum(1 for t, v in hand.link.packets if v == CLOSE)
        opens = sum(1 for t, v in hand.link.packets if v == OPEN)
        print(f" decisions: CLOSE {closes} / OPEN {opens}", flush=True)
        for t, v in hand.link.packets:
            print(f"   [{t - t0:7.2f}s] {'CLOSE' if v == CLOSE else 'OPEN'}", flush=True)


if __name__ == "__main__":
    main()
