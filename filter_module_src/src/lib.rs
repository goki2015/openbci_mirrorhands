//! Causal (real-time) EMG filter used by the OpenBCI analysis pipeline.
//!
//! `raw_filiter.py` / `emg_analysis.py` use zero-phase `filtfilt`, which needs
//! the whole recording (future samples).  This crate implements the same
//! *magnitude* response with a causal cascade:
//!
//! ```text
//! notch 50 Hz (Q=30) -> notch 100 Hz (Q=30)
//!   -> Butterworth band-pass 5-110 Hz (order 4)
//!   -> trailing moving RMS (200 ms)
//! ```
//!
//! `filtfilt` applies each section forwards and backwards, so its magnitude
//! response is `|H|^2`.  The default `passes=2` cascades the causal filter
//! twice to match that magnitude response.  The phase response cannot be made
//! zero without looking ahead, so a small causal group delay remains.
//!
//! The filter states are initialised to the steady state of the first input
//! sample, which removes the usual start-up transient.  Bad samples (`0`,
//! non-finite, or `|x| > 1e5`) are replaced by causal linear extrapolation
//! instead of the non-causal interpolation used by the offline script.

use std::f64::consts::PI;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

const BAD_ABS: f64 = 1e5;

/// `(cleaned, filtered, rms, bad_samples)`
type ProcessResult = (Vec<f64>, Vec<f64>, Vec<f64>, usize);

// ---------------------------------------------------------------------------
// Small complex helper (avoids an extra dependency)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
struct Complex {
    re: f64,
    im: f64,
}

impl Complex {
    fn new(re: f64, im: f64) -> Self {
        Self { re, im }
    }

    fn from_polar(r: f64, theta: f64) -> Self {
        Self::new(r * theta.cos(), r * theta.sin())
    }

    fn add(self, other: Self) -> Self {
        Self::new(self.re + other.re, self.im + other.im)
    }

    fn sub(self, other: Self) -> Self {
        Self::new(self.re - other.re, self.im - other.im)
    }

    fn mul(self, other: Self) -> Self {
        Self::new(
            self.re * other.re - self.im * other.im,
            self.re * other.im + self.im * other.re,
        )
    }

    fn div(self, other: Self) -> Self {
        let d = other.re * other.re + other.im * other.im;
        Self::new(
            (self.re * other.re + self.im * other.im) / d,
            (self.im * other.re - self.re * other.im) / d,
        )
    }

    fn scale(self, k: f64) -> Self {
        Self::new(self.re * k, self.im * k)
    }

    fn abs(self) -> f64 {
        self.re.hypot(self.im)
    }

    fn sqrt(self) -> Self {
        if self.im == 0.0 {
            if self.re >= 0.0 {
                Self::new(self.re.sqrt(), 0.0)
            } else {
                Self::new(0.0, (-self.re).sqrt())
            }
        } else {
            let r = self.abs();
            let re = ((r + self.re) * 0.5).sqrt();
            let im = ((r - self.re) * 0.5).sqrt() * if self.im < 0.0 { -1.0 } else { 1.0 };
            Self::new(re, im)
        }
    }
}

// ---------------------------------------------------------------------------
// Biquad (Direct Form II Transposed)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
struct Biquad {
    b0: f64,
    b1: f64,
    b2: f64,
    a1: f64,
    a2: f64,
    z1: f64,
    z2: f64,
}

impl Biquad {
    fn from_coeffs(b: [f64; 3], a: [f64; 3]) -> Self {
        let a0 = a[0];
        Self {
            b0: b[0] / a0,
            b1: b[1] / a0,
            b2: b[2] / a0,
            a1: a[1] / a0,
            a2: a[2] / a0,
            z1: 0.0,
            z2: 0.0,
        }
    }

    fn process(&mut self, x: f64) -> f64 {
        let y = self.b0 * x + self.z1;
        self.z1 = self.b1 * x - self.a1 * y + self.z2;
        self.z2 = self.b2 * x - self.a2 * y;
        y
    }

    fn reset(&mut self) {
        self.z1 = 0.0;
        self.z2 = 0.0;
    }

    fn dc_gain(&self) -> f64 {
        (self.b0 + self.b1 + self.b2) / (1.0 + self.a1 + self.a2)
    }

    /// Set the internal state so that a constant input `x` produces the
    /// steady-state output immediately (no start-up transient).
    fn set_steady_state(&mut self, x: f64) {
        let g = self.dc_gain();
        self.z1 = (g - self.b0) * x;
        self.z2 = (g - self.b0 - self.b1 + self.a1 * g) * x;
    }

    fn magnitude_at(&self, w: f64) -> f64 {
        let z1 = Complex::new(w.cos(), -w.sin());
        let z2 = z1.mul(z1);
        let num = Complex::new(self.b0, 0.0)
            .add(Complex::new(self.b1, 0.0).mul(z1))
            .add(Complex::new(self.b2, 0.0).mul(z2));
        let den = Complex::new(1.0, 0.0)
            .add(Complex::new(self.a1, 0.0).mul(z1))
            .add(Complex::new(self.a2, 0.0).mul(z2));
        num.div(den).abs()
    }
}

// ---------------------------------------------------------------------------
// Filter design (identical coefficients to scipy)
// ---------------------------------------------------------------------------

/// Same design as `scipy.signal.iirnotch(f0, q, fs)`.
fn design_notch(f0: f64, q: f64, fs: f64) -> Biquad {
    let w0 = 2.0 * PI * f0 / fs;
    let bw = w0 / q;
    let gb = 1.0 / 2.0_f64.sqrt();
    let beta = ((1.0 - gb * gb).sqrt() / gb) * (bw * 0.5).tan();
    let gain = 1.0 / (1.0 + beta);
    let two_cos = 2.0 * gain * w0.cos();
    let b = [gain, -two_cos, gain];
    let a = [1.0, -two_cos, 2.0 * gain - 1.0];
    Biquad::from_coeffs(b, a)
}

/// Same response as `scipy.signal.butter(order, [lo, hi], "bandpass", fs=fs,
/// output="sos")`, factored as `order` biquads.
fn design_butterworth_bandpass(order: usize, lo: f64, hi: f64, fs: f64) -> Vec<Biquad> {
    let wlo = 2.0 * fs * (PI * lo / fs).tan();
    let whi = 2.0 * fs * (PI * hi / fs).tan();
    let w0 = (wlo * whi).sqrt();
    let bw = whi - wlo;
    let n = order as f64;

    // Analog low-pass prototype poles, transformed to a band-pass and then
    // mapped through the bilinear transform.
    let mut poles: Vec<Complex> = Vec::with_capacity(2 * order);
    for k in 0..order {
        let theta = PI * (2.0 * k as f64 + n + 1.0) / (2.0 * n);
        let p = Complex::from_polar(1.0, theta);
        let pb = p.scale(bw);
        let disc = pb.mul(pb).sub(Complex::new(4.0 * w0 * w0, 0.0)).sqrt();
        for s in [pb.add(disc).scale(0.5), pb.sub(disc).scale(0.5)] {
            let two_fs = Complex::new(2.0 * fs, 0.0);
            poles.push(two_fs.add(s).div(two_fs.sub(s)));
        }
    }

    poles.sort_by(|a, b| a.im.total_cmp(&b.im).then(a.re.total_cmp(&b.re)));

    let mut sections = Vec::with_capacity(order);
    for i in 0..order {
        // Pair the outermost poles: they are conjugates (or a real pair).
        let za = poles[i];
        let zb = poles[2 * order - 1 - i];
        let a1 = -(za.re + zb.re);
        let a2 = za.mul(zb).re;
        sections.push(Biquad::from_coeffs([1.0, 0.0, -1.0], [1.0, a1, a2]));
    }

    // Normalise the complete cascade to unity gain at the centre frequency.
    let fc = (fs / PI) * (w0 / (2.0 * fs)).atan();
    let wc = 2.0 * PI * fc / fs;
    let mag: f64 = sections.iter().map(|s| s.magnitude_at(wc)).product();
    let g = 1.0 / mag;
    sections[0].b0 *= g;
    sections[0].b1 *= g;
    sections[0].b2 *= g;

    sections
}

// ---------------------------------------------------------------------------
// Causal building blocks
// ---------------------------------------------------------------------------

struct CausalCleaner {
    prev2: Option<f64>,
    prev1: Option<f64>,
    bad_streak: usize,
    max_extrapolate: usize,
    bad_count: usize,
}

impl CausalCleaner {
    fn new(fs: f64) -> Self {
        let max_extrapolate = ((0.1 * fs).round() as usize).max(1);
        Self {
            prev2: None,
            prev1: None,
            bad_streak: 0,
            max_extrapolate,
            bad_count: 0,
        }
    }

    fn reset(&mut self) {
        self.prev2 = None;
        self.prev1 = None;
        self.bad_streak = 0;
        self.bad_count = 0;
    }

    /// Replace `0`, non-finite, and saturated samples using only past data.
    fn push(&mut self, x: f64) -> f64 {
        let bad = !x.is_finite() || x == 0.0 || x.abs() > BAD_ABS;
        if !bad {
            self.bad_streak = 0;
            self.prev2 = self.prev1;
            self.prev1 = Some(x);
            return x;
        }

        self.bad_count += 1;
        self.bad_streak += 1;

        match (self.prev2, self.prev1) {
            (Some(a), Some(b)) if self.bad_streak <= self.max_extrapolate => {
                // Linear extrapolation from the last two valid samples.
                let y = (2.0 * b - a).clamp(-BAD_ABS, BAD_ABS);
                self.prev2 = Some(b);
                self.prev1 = Some(y);
                y
            }
            (_, Some(b)) => b, // longer gap: hold the last valid value
            _ => 0.0,          // no valid sample yet
        }
    }
}

struct RunningMedian {
    window: usize,
    ring: Vec<f64>,
    sorted: Vec<f64>,
    pos: usize,
    count: usize,
}

impl RunningMedian {
    fn new(window: usize) -> Self {
        Self {
            window,
            ring: vec![0.0; window],
            sorted: Vec::with_capacity(window),
            pos: 0,
            count: 0,
        }
    }

    fn reset(&mut self) {
        self.ring.iter_mut().for_each(|v| *v = 0.0);
        self.sorted.clear();
        self.pos = 0;
        self.count = 0;
    }

    /// Return the median of the last `window` samples (including `x`).
    /// A window of 0 disables DC removal.
    fn push(&mut self, x: f64) -> f64 {
        if self.window == 0 {
            return 0.0;
        }

        if self.count == self.window {
            let old = self.ring[self.pos];
            if let Ok(idx) = self.sorted.binary_search_by(|v| v.total_cmp(&old)) {
                self.sorted.remove(idx);
            } else {
                let idx = self.sorted.partition_point(|v| v.total_cmp(&old).is_lt());
                if idx < self.sorted.len() {
                    self.sorted.remove(idx);
                }
            }
        } else {
            self.count += 1;
        }

        self.ring[self.pos] = x;
        let idx = self.sorted.partition_point(|v| v.total_cmp(&x).is_lt());
        self.sorted.insert(idx, x);
        self.pos += 1;
        if self.pos == self.window {
            self.pos = 0;
        }

        let n = self.sorted.len();
        if n % 2 == 1 {
            self.sorted[n / 2]
        } else {
            0.5 * (self.sorted[n / 2 - 1] + self.sorted[n / 2])
        }
    }
}

struct RunningRms {
    window: usize,
    buf: Vec<f64>,
    pos: usize,
    count: usize,
    sum_sq: f64,
}

impl RunningRms {
    fn new(window: usize) -> Self {
        Self {
            window,
            buf: vec![0.0; window],
            pos: 0,
            count: 0,
            sum_sq: 0.0,
        }
    }

    fn reset(&mut self) {
        self.buf.iter_mut().for_each(|v| *v = 0.0);
        self.pos = 0;
        self.count = 0;
        self.sum_sq = 0.0;
    }

    /// Trailing moving RMS (the current sample is the newest one).
    fn push(&mut self, x: f64) -> f64 {
        if self.window == 0 {
            return x.abs();
        }

        if self.count == self.window {
            self.sum_sq -= self.buf[self.pos];
        } else {
            self.count += 1;
        }

        let sq = x * x;
        self.buf[self.pos] = sq;
        self.sum_sq += sq;
        self.pos += 1;
        if self.pos == self.window {
            self.pos = 0;
        }

        (self.sum_sq / self.count as f64).sqrt()
    }
}

struct FilterChain {
    sections: Vec<Biquad>,
    initialized: bool,
}

impl FilterChain {
    fn new(sections: Vec<Biquad>) -> Self {
        Self {
            sections,
            initialized: false,
        }
    }

    fn reset(&mut self) {
        for s in &mut self.sections {
            s.reset();
        }
        self.initialized = false;
    }

    fn process(&mut self, x: f64) -> f64 {
        if !self.initialized {
            // Steady state for the first sample = no start-up transient.
            let mut level = x;
            for s in &mut self.sections {
                s.set_steady_state(level);
                level *= s.dc_gain();
            }
            self.initialized = true;
        }

        let mut y = x;
        for s in &mut self.sections {
            y = s.process(y);
        }
        y
    }
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

struct Config {
    fs: f64,
    notch_freqs: Vec<f64>,
    notch_q: f64,
    band_lo: f64,
    band_hi: f64,
    band_order: usize,
    dc_window: usize,
    rms_window: usize,
    clean: bool,
    passes: usize,
}

impl Config {
    #[allow(clippy::too_many_arguments)]
    fn new(
        fs: f64,
        notch_freqs: Option<Vec<f64>>,
        notch_q: f64,
        band: (f64, f64),
        band_order: usize,
        dc_window_s: f64,
        rms_window_s: f64,
        clean: bool,
        passes: usize,
    ) -> PyResult<Self> {
        if !fs.is_finite() || fs <= 0.0 {
            return Err(PyValueError::new_err("fs must be a positive number"));
        }
        if !notch_q.is_finite() || notch_q <= 0.0 {
            return Err(PyValueError::new_err("notch_q must be positive"));
        }
        if !band.0.is_finite()
            || !band.1.is_finite()
            || band.0 <= 0.0
            || band.0 >= band.1
            || band.1 >= fs * 0.5
        {
            return Err(PyValueError::new_err(
                "band must satisfy 0 < lo < hi < fs/2",
            ));
        }
        if band_order == 0 || band_order > 12 {
            return Err(PyValueError::new_err("band_order must be in 1..=12"));
        }
        if !dc_window_s.is_finite() || dc_window_s < 0.0 {
            return Err(PyValueError::new_err("dc_window_s must be >= 0"));
        }
        if !rms_window_s.is_finite() || rms_window_s < 0.0 {
            return Err(PyValueError::new_err("rms_window_s must be >= 0"));
        }
        if passes == 0 || passes > 4 {
            return Err(PyValueError::new_err("passes must be in 1..=4"));
        }

        let notch_freqs = notch_freqs.unwrap_or_else(|| vec![50.0, 100.0]);
        for f0 in &notch_freqs {
            if !f0.is_finite() || *f0 <= 0.0 || *f0 >= fs * 0.5 {
                return Err(PyValueError::new_err(
                    "each notch frequency must satisfy 0 < f0 < fs/2",
                ));
            }
        }

        let dc_window = (dc_window_s * fs).round() as usize;
        let rms_window = (rms_window_s * fs).round() as usize;

        Ok(Self {
            fs,
            notch_freqs,
            notch_q,
            band_lo: band.0,
            band_hi: band.1,
            band_order,
            dc_window,
            rms_window,
            clean,
            passes,
        })
    }

    fn build_chain(&self) -> Vec<Biquad> {
        let mut base = Vec::new();
        for f0 in &self.notch_freqs {
            base.push(design_notch(*f0, self.notch_q, self.fs));
        }
        base.extend(design_butterworth_bandpass(
            self.band_order,
            self.band_lo,
            self.band_hi,
            self.fs,
        ));

        // `filtfilt` has a |H|^2 magnitude response.  Cascading the causal
        // filter `passes` times reproduces that magnitude without look-ahead.
        let mut sections = Vec::with_capacity(base.len() * self.passes);
        for _ in 0..self.passes {
            sections.extend_from_slice(&base);
        }
        sections
    }
}

// ---------------------------------------------------------------------------
// Streaming filter
// ---------------------------------------------------------------------------

/// Causal real-time EMG filter.
///
/// Feed samples one by one with :meth:`process` (or in blocks with
/// :meth:`process_many`).  Every output depends only on past and current
/// input, so the class is usable in a real-time loop.
#[pyclass(module = "filter_module")]
struct StreamingFilter {
    chain: FilterChain,
    cleaner: CausalCleaner,
    dc: RunningMedian,
    rms: RunningRms,
    clean: bool,
}

impl StreamingFilter {
    fn from_config(cfg: &Config) -> Self {
        Self {
            chain: FilterChain::new(cfg.build_chain()),
            cleaner: CausalCleaner::new(cfg.fs),
            dc: RunningMedian::new(cfg.dc_window),
            rms: RunningRms::new(cfg.rms_window),
            clean: cfg.clean,
        }
    }

    fn process_one(&mut self, raw: f64) -> (f64, f64, f64) {
        let cleaned = if self.clean {
            self.cleaner.push(raw)
        } else if raw.is_finite() {
            raw
        } else {
            0.0
        };

        let dc = self.dc.push(cleaned);
        let centered = cleaned - dc;
        let filtered = self.chain.process(centered);
        let rms = self.rms.push(filtered);
        (cleaned, filtered, rms)
    }
}

#[pymethods]
impl StreamingFilter {
    /// Create a filter.
    ///
    /// Parameters match `process_array`; see the module docstring.
    #[new]
    #[pyo3(signature = (fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0),
                        band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=true,
                        passes=2))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        fs: f64,
        notch_freqs: Option<Vec<f64>>,
        notch_q: f64,
        band: (f64, f64),
        band_order: usize,
        dc_window_s: f64,
        rms_window_s: f64,
        clean: bool,
        passes: usize,
    ) -> PyResult<Self> {
        let cfg = Config::new(
            fs,
            notch_freqs,
            notch_q,
            band,
            band_order,
            dc_window_s,
            rms_window_s,
            clean,
            passes,
        )?;
        Ok(Self::from_config(&cfg))
    }

    /// Process one sample and return `(filtered, rms)`.
    fn process(&mut self, sample: f64) -> (f64, f64) {
        let (_, filtered, rms) = self.process_one(sample);
        (filtered, rms)
    }

    /// Process a block of samples and return `(filtered, rms)` lists.
    fn process_many(&mut self, samples: Vec<f64>) -> (Vec<f64>, Vec<f64>) {
        let mut filtered = Vec::with_capacity(samples.len());
        let mut rms = Vec::with_capacity(samples.len());
        for sample in samples {
            let (_, f, r) = self.process_one(sample);
            filtered.push(f);
            rms.push(r);
        }
        (filtered, rms)
    }

    /// Reset all filter state (start a new recording).
    fn reset(&mut self) {
        self.chain.reset();
        self.cleaner.reset();
        self.dc.reset();
        self.rms.reset();
    }

    /// Number of samples classified as bad (`0`, non-finite or `|x| > 1e5`).
    #[getter]
    fn bad_samples(&self) -> usize {
        self.cleaner.bad_count
    }
}

/// Causal, real-time version of `emg_analysis.clean` + `filter_emg` +
/// `moving_rms`.
///
/// Returns `(cleaned, filtered, rms, bad_samples)`.
///
/// Parameters
/// ----------
/// x : sequence of float
///     Raw OpenBCI EXG Ch0 samples.
/// fs : float, default 250.0
/// notch_freqs : sequence of float, default (50, 100)
/// notch_q : float, default 30.0
/// band : (float, float), default (5, 110)
/// band_order : int, default 4
/// dc_window_s : float, default 1.0
///     Window of the causal running-median DC remover. 0 disables it.
/// rms_window_s : float, default 0.2
///     Trailing RMS window. 0 gives `abs(filtered)`.
/// clean : bool, default True
///     Replace bad samples using causal extrapolation.
/// passes : int, default 2
///     Number of cascaded causal passes. 2 matches `filtfilt`'s |H|^2
///     magnitude response; 1 minimises phase delay.
#[pyfunction]
#[pyo3(signature = (x, fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0),
                    band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=true,
                    passes=2))]
#[allow(clippy::too_many_arguments)]
fn process_array(
    x: Vec<f64>,
    fs: f64,
    notch_freqs: Option<Vec<f64>>,
    notch_q: f64,
    band: (f64, f64),
    band_order: usize,
    dc_window_s: f64,
    rms_window_s: f64,
    clean: bool,
    passes: usize,
) -> PyResult<ProcessResult> {
    process_array_impl(
        x,
        fs,
        notch_freqs,
        notch_q,
        band,
        band_order,
        dc_window_s,
        rms_window_s,
        clean,
        passes,
    )
}

#[allow(clippy::too_many_arguments)]
fn process_array_impl(
    x: Vec<f64>,
    fs: f64,
    notch_freqs: Option<Vec<f64>>,
    notch_q: f64,
    band: (f64, f64),
    band_order: usize,
    dc_window_s: f64,
    rms_window_s: f64,
    clean: bool,
    passes: usize,
) -> PyResult<ProcessResult> {
    let cfg = Config::new(
        fs,
        notch_freqs,
        notch_q,
        band,
        band_order,
        dc_window_s,
        rms_window_s,
        clean,
        passes,
    )?;
    let mut filter = StreamingFilter::from_config(&cfg);

    let mut cleaned = Vec::with_capacity(x.len());
    let mut filtered = Vec::with_capacity(x.len());
    let mut rms = Vec::with_capacity(x.len());
    for sample in x {
        let (c, f, r) = filter.process_one(sample);
        cleaned.push(c);
        filtered.push(f);
        rms.push(r);
    }

    Ok((cleaned, filtered, rms, filter.cleaner.bad_count))
}

/// Drop-in replacement for `openbci_mirrorhands/main.py`'s `filter` function.
///
/// `apply_filter(raw_buf, fs)` accepts the same arguments (a deque/list/NumPy
/// array and the sampling rate) and returns only the filtered samples, so this:
///
/// ```python
/// filtered_buf = apply_filter(raw_buf, fs)
/// ```
///
/// keeps working after replacing the local `filter` definition with
/// `from filter_module import apply_filter`.
///
/// The name avoids shadowing Python's built-in `filter`.
///
/// The whole buffer is filtered from scratch on every call (like the original
/// BrainFlow implementation).  For a continuous stream, prefer
/// :class:`StreamingFilter` and process only the newly arrived samples.
#[pyfunction]
#[pyo3(signature = (raw_buf, fs=250.0, notch_freqs=None, notch_q=30.0, band=(5.0, 110.0),
                    band_order=4, dc_window_s=1.0, rms_window_s=0.2, clean=true,
                    passes=2))]
#[allow(clippy::too_many_arguments)]
fn apply_filter(
    raw_buf: Vec<f64>,
    fs: f64,
    notch_freqs: Option<Vec<f64>>,
    notch_q: f64,
    band: (f64, f64),
    band_order: usize,
    dc_window_s: f64,
    rms_window_s: f64,
    clean: bool,
    passes: usize,
) -> PyResult<Vec<f64>> {
    let (_, filtered, _, _) = process_array_impl(
        raw_buf,
        fs,
        notch_freqs,
        notch_q,
        band,
        band_order,
        dc_window_s,
        rms_window_s,
        clean,
        passes,
    )?;
    Ok(filtered)
}

#[pymodule]
fn _filter_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(process_array, m)?)?;
    m.add_function(wrap_pyfunction!(apply_filter, m)?)?;
    m.add_class::<StreamingFilter>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
