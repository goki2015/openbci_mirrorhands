"""scipy-based version of the causal real-time EMG filter.

Same chain, API and behaviour as ``filter_module_py`` (and the Rust extension),
but the iirnotch / Butterworth band-pass coefficients are designed with
``scipy.signal`` instead of being derived in-module. Streaming math
(biquad DF-II transposed, rolling median + RMS) is reused from
``filter_module_py``.

    from filter_module_scipy import StreamingFilter   # drop-in replacement
"""
import math

from scipy.signal import butter, iirnotch

import filter_module_py as _p

__version__ = "0.1.0"
BAD_ABS = _p.BAD_ABS


def _design(fs, fr, q, band, order):
    secs = []
    for f in fr:  # scipy.signal.iirnotch (same formulas as the Rust design)
        b, a = iirnotch(f, q, fs)
        secs.append((b.tolist(), a.tolist()))
    sos = butter(order, list(band), "bandpass", fs=fs, output="sos")  # band-pass biquads
    for r in sos:
        secs.append(((r[:3] / r[3]).tolist(), (r[3:] / r[3]).tolist()))  # normalise a0 to 1
    i = len(fr)  # first band-pass section: normalise the cascade to unity gain at f_c
    wlo = 2 * fs * math.tan(math.pi * band[0] / fs)
    whi = 2 * fs * math.tan(math.pi * band[1] / fs)
    fc = (fs / math.pi) * math.atan(math.sqrt(wlo * whi) / (2 * fs))
    g = 1.0 / math.prod(_p._mag(b, a, 2.0 * math.pi * fc / fs) for b, a in secs[i:])
    b, a = secs[i]
    secs[i] = ([v * g for v in b], a)
    return secs


class StreamingFilter(_p.StreamingFilter):
    """Causal real-time EMG filter with scipy-designed coefficients."""

    def __init__(self, fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0),
                 band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=True, passes=2):
        fr = list(notch_freqs) if notch_freqs is not None else [50.0, 100.0]
        _p._validate(fs, fr, notch_q, band, band_order, dc_window_s, rms_window_s, passes)
        secs = _design(fs, fr, notch_q, band, band_order)
        self.secs = [_p._Biquad(b, a) for _ in range(passes) for b, a in secs]
        self.cleaner = _p._Cleaner(fs)
        self.dc = _p._Median(int(dc_window_s * fs + 0.5))
        self.rms = _p._Rms(int(rms_window_s * fs + 0.5))
        self.clean = clean
        self._init = False


def process_array(x, fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0),
                  band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=True, passes=2):
    f = StreamingFilter(fs, notch_freqs, notch_q, band, band_order, dc_window_s, rms_window_s, clean, passes)
    o = [f.process_one(float(v)) for v in x]
    return ([t[0] for t in o], [t[1] for t in o], [t[2] for t in o], f.bad_samples)


def apply_filter(raw_buf, fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0),
                 band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=True, passes=2):
    return process_array(raw_buf, fs, notch_freqs, notch_q, band, band_order,
                         dc_window_s, rms_window_s, clean, passes)[1]
