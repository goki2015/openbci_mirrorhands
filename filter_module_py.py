"""Pure-Python port of the Rust ``filter_module`` (causal real-time EMG filter)."""
import cmath, math
from bisect import bisect_left, insort
from collections import deque
BAD_ABS, __version__ = 1e5, "0.1.0"
def _mag(b, a, w):
    z = complex(math.cos(w), -math.sin(w)); return abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z))
class _Biquad:  # Direct Form II transposed
    def __init__(self, b, a):
        a0 = a[0]
        self.b = [v / a0 for v in b]
        self.a1, self.a2 = a[1] / a0, a[2] / a0
        self.z1 = self.z2 = 0.0
    def dc_gain(self): return sum(self.b) / (1.0 + self.a1 + self.a2)
    def steady(self, x): g = self.dc_gain(); self.z1 = (g - self.b[0]) * x; self.z2 = (g - self.b[0] - self.b[1] + self.a1 * g) * x
    def __call__(self, x): y = self.b[0] * x + self.z1; self.z1 = self.b[1] * x - self.a1 * y + self.z2; self.z2 = self.b[2] * x - self.a2 * y; return y
def _notch(f0, q, fs):  # same design as scipy.signal.iirnotch
    w0 = 2.0 * math.pi * f0 / fs; gb = 1.0 / math.sqrt(2.0)
    beta = math.sqrt(1.0 - gb * gb) / gb * math.tan(w0 / (2.0 * q))
    g = 1.0 / (1.0 + beta)
    c = 2.0 * g * math.cos(w0)
    return ([g, -c, g], [1.0, -c, 2.0 * g - 1.0])
def _bandpass(o, lo, hi, fs):  # scipy.signal.butter(o, [lo, hi], "bandpass")
    wlo, whi = 2 * fs * math.tan(math.pi * lo / fs), 2 * fs * math.tan(math.pi * hi / fs)
    w0, bw, n = math.sqrt(wlo * whi), whi - wlo, float(o)
    poles = []
    for k in range(o):
        th = math.pi * (2 * k + n + 1.0) / (2.0 * n); pb = complex(math.cos(th), math.sin(th)) * bw
        d = cmath.sqrt(pb * pb - 4.0 * w0 * w0)
        poles += [(4.0 * fs + s) / (4.0 * fs - s) for s in (pb + d, pb - d)]
    poles.sort(key=lambda z: (z.imag, z.real)); secs = []
    for i in range(o):
        za, zb = poles[i], poles[2 * o - 1 - i]
        secs.append([[1.0, 0.0, -1.0], [1.0, -(za.real + zb.real), (za * zb).real]])
    fc = (fs / math.pi) * math.atan(w0 / (2.0 * fs)); wc = 2.0 * math.pi * fc / fs
    g = 1.0 / math.prod(_mag(b, a, wc) for b, a in secs); secs[0][0] = [v * g for v in secs[0][0]]
    return secs
def _validate(fs, fr, q, band, order, dc_s, rms_s, passes):
    ok = all(map(math.isfinite, [fs, q, dc_s, rms_s, *band, *fr])) and fs > 0.0 and q > 0.0
    ok = ok and 0.0 < band[0] < band[1] < fs * 0.5 and all(0.0 < f < fs * 0.5 for f in fr)
    ok = ok and 1 <= order <= 12 and 1 <= passes <= 4 and min(dc_s, rms_s) >= 0.0
    if not ok: raise ValueError("invalid filter configuration")
def _design(fs, fr, q, band, order): return [_notch(f, q, fs) for f in fr] + _bandpass(order, band[0], band[1], fs)
class _Cleaner:  # replace bad samples (0, non-finite, |x|>1e5) causally
    def __init__(self, fs): self.max_ex = max(1, int(0.1 * fs + 0.5)); self.reset()
    def reset(self): self.p2 = self.p1 = None; self.streak = self.bad = 0
    def push(self, x):
        if math.isfinite(x) and x != 0.0 and abs(x) <= BAD_ABS: self.streak = 0; self.p2, self.p1 = self.p1, x; return x
        self.bad += 1; self.streak += 1
        if self.p2 is not None and self.p1 is not None and self.streak <= self.max_ex:
            y = min(max(2.0 * self.p1 - self.p2, -BAD_ABS), BAD_ABS); self.p2, self.p1 = self.p1, y; return y
        return self.p1 if self.p1 is not None else 0.0
class _Median:  # trailing running median (DC removal); window 0 disables
    def __init__(self, win): self.win = win; self.buf = deque(maxlen=win) if win else None; self.s = []
    def reset(self): self.s.clear(); self.buf is None or self.buf.clear()
    def push(self, x):
        if not self.win: return 0.0
        if len(self.buf) == self.win: del self.s[bisect_left(self.s, self.buf[0])]
        self.buf.append(x); insort(self.s, x)
        n = len(self.s); return self.s[n // 2] if n % 2 else 0.5 * (self.s[n // 2 - 1] + self.s[n // 2])
class _Rms:  # trailing moving RMS; window 0 gives abs(x)
    def __init__(self, win): self.win = win; self.buf = deque(); self.sq = 0.0
    def reset(self): self.buf.clear(); self.sq = 0.0
    def push(self, x):
        if not self.win: return abs(x)
        if len(self.buf) == self.win: self.sq -= self.buf.popleft()
        s = x * x; self.buf.append(s); self.sq += s; return math.sqrt(self.sq / len(self.buf))
class StreamingFilter:  # causal real-time EMG filter; process(sample) -> (filtered, rms)
    def __init__(self, fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0), band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=True, passes=2):
        fr = list(notch_freqs) if notch_freqs is not None else [50.0, 100.0]
        _validate(fs, fr, notch_q, band, band_order, dc_window_s, rms_window_s, passes)
        self.secs = [_Biquad(b, a) for _ in range(passes) for b, a in _design(fs, fr, notch_q, band, band_order)]
        self.cleaner = _Cleaner(fs); self.dc = _Median(int(dc_window_s * fs + 0.5)); self.rms = _Rms(int(rms_window_s * fs + 0.5))
        self.clean = clean; self._init = False
    def process_one(self, raw):
        c = self.cleaner.push(raw) if self.clean else (raw if math.isfinite(raw) else 0.0)
        x = c - self.dc.push(c)
        if not self._init:
            lv = x
            for s in self.secs: s.steady(lv); lv *= s.dc_gain()
            self._init = True
        for s in self.secs: x = s(x)
        return c, x, self.rms.push(x)
    def process(self, v): _, f, r = self.process_one(float(v)); return f, r
    def process_many(self, vs):
        o = [self.process_one(float(v)) for v in vs]; return [t[1] for t in o], [t[2] for t in o]
    def reset(self):
        for s in self.secs: s.z1 = s.z2 = 0.0
        self.cleaner.reset(); self.dc.reset(); self.rms.reset()
        self._init = False
    @property
    def bad_samples(self): return self.cleaner.bad
def process_array(x, fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0), band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=True, passes=2):
    f = StreamingFilter(fs, notch_freqs, notch_q, band, band_order, dc_window_s, rms_window_s, clean, passes)
    o = [f.process_one(float(v)) for v in x]
    return ([t[0] for t in o], [t[1] for t in o], [t[2] for t in o], f.bad_samples)
def apply_filter(raw_buf, fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0), band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=True, passes=2):
    return process_array(raw_buf, fs, notch_freqs, notch_q, band, band_order, dc_window_s, rms_window_s, clean, passes)[1]
