# openbci_mirrorhands

English | [日本語](README.ja.md) | [繁體中文（台灣）](README.zh-TW.md)

EMG-controlled mirror hand (glove) driven by an OpenBCI Cyton board.
Raw EMG is filtered online on a PC, a per-user threshold model is calibrated at
startup, and the glove opens/closes in real time via USB serial.

```
OpenBCI Cyton (EXG Ch0)
    │  250 Hz
    ▼
causal filter chain (scipy): notch 50 Hz → notch 100 Hz → band-pass 5–110 Hz (4th) → RMS (200 ms)
    ▼
AdaptiveThreshold: rest phase → grip phase → grip / release / artifact thresholds
    ▼  rms ≥ grip_th                    ▼  rms ≤ release_th (30 consecutive samples)
MirrorHand: CLOSE                    MirrorHand: OPEN
    ▼
RMTC_GLOVE protocol over USB serial (57600 8N1, keepalive every 0.2 s)
```

## Requirements

- Linux PC (paths `/dev/ttyUSB*` are assumed)
- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/)
- Hardware: OpenBCI Cyton, and a RMTC_GLOVE-compatible mirror hand glove
- Dependencies (installed by `uv sync`): brainflow, numpy, pyserial, scipy

## Setup

```bash
git clone <this repo>
cd openbci_mirrorhands
uv sync
```

## Usage

```bash
uv run main.py
```

1. Plug the Cyton into `/dev/ttyUSB0` and the glove into `/dev/ttyUSB1`
   (edit `main.py` if your device nodes differ: `settings["port"]` for the board,
   `MirrorHand(port=...)` for the glove).
2. On the glove body, press **MIRROR GUIDE → START**. The program waits for the
   `device` beacon, handshakes with `RMTC_GLOVE`, and keeps the hand open.
3. Calibration runs: stay relaxed for ~6 s → press **Enter** → grip strongly and
   keep gripping for ~6 s. Thresholds are printed when done (`grip=… release=… artifact=… gap=… dB`).
4. Running mode: `rms ≥ grip_th` closes the hand; the hand opens only after
   `release_th` is **stayed below for 30 consecutive samples** (debounce,
   see `release_debounce.py`). Large artefacts (`rms ≥ artifact_th`) force-open
   the hand as a safety measure.
5. **Ctrl+C** to quit: the glove opens and the board session is released.

## Verification scripts (local development)

- `test_emg_pipeline.py` — runs the same pipeline against the Cyton **without
  the glove** and prints thresholds/decisions plus a scipy-vs-Rust filter
  comparison (uses a stub link). Not tracked in this repository (gitignored).
- `test_glove_buttons.py` — glove-only smoke test (handshake → CLOSE → OPEN).

## Project structure

| File | Role |
|---|---|
| `main.py` | Entry point: Cyton stream → filter → glove |
| `mirrorhand.py` | Open/close decision logic, calibration orchestration |
| `mirrorhand_link.py` | Glove serial protocol (beacon wait, handshake, keepalive) |
| `release_debounce.py` | Release debounce (N consecutive samples below threshold) |
| `calibrate.py` | `AdaptiveThreshold`: rest→grip calibration, percentile-based thresholds |
| `filter_module_scipy.py` | Causal real-time EMG filter, scipy-designed coefficients |
| `filter_module_py.py` | Same filter in pure stdlib Python (drop-in alternative) |
| `filter_module/`, `filter_module_src/` | Rust extension and its source (local only, not tracked) |
| `docs/` | Extended documentation (Japanese, HTML) |
| `test_emg_pipeline.py` | OpenBCI-only verification script (local only) |
| `test_glove_buttons.py` | Glove-only smoke test |

## Implementation notes

- **Real-time filter**: causal cascade (50/100 Hz notches → 4th-order band-pass
  5–110 Hz → 200 ms trailing RMS). `passes=2` reproduces `filtfilt`'s \|H\|²
  magnitude response without look-ahead; states are initialised to the
  steady state of the first sample; bad samples (0 / non-finite / \|x\|>1e5) are
  replaced by causal linear extrapolation (max 0.1 s).
- **Threshold calibration** (`calibrate.py`): median (p50) based anchor
  (geometric mean), worst-case separation `gap_db = 20·log10(grip_p10 / rest_p90)`
  with percentile p10/p90 as a conservative bound; the final grip threshold is
  never placed below `rest_p90 × 1.5`.
- **Release debounce** (`release_debounce.py`): the hand stays closed until the
  RMS stays at/below `release_th` for `release_frames` consecutive samples
  (default 30 = 0.12 s at 250 Hz). Any sample above the threshold resets the
  counter. CLOSE always re-arms the counter.
- **Glove protocol**: `device` beacon → immediate `RMTC_GLOVE\r` → five
  `DATA:0:v` fields per packet (`v=100` closed, `v=10` open), re-sent every
  0.2 s (keepalive).
- **Rust filter**: the original implementation was a Rust extension. The
  repository now uses the numerically identical scipy-based Python filter
  (verified to ≤5e-13 absolute difference). The Rust build tree remains usable
  locally but is intentionally not tracked.

## License

MIT (see `LICENSE`).
