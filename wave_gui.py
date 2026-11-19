"""matplotlib による OpenBCI 波形の簡易ライブ表示（`main.py --gui` 起動時のみ）。

生波形（EXG Ch0）・フィルタ済み波形・RMS 包絡をスクロール表示する。

注意:
  - 描画のたびにイベントループへ処理を渡すだけなので、glove への更新は
    基本的にブロックされない。ただし GUI 描画の分だけループが遅くなる可能性はある
    （リアルタイム性を重視するなら --gui を付けずに起動すること）。
  - 表示は refresh_s 間隔で、最大 seconds 秒分を表示する。
"""
import time
from collections import deque

import matplotlib.pyplot as plt


class LiveWave:
    """スクロール式のライブ波形プロッタ（3段: Raw / Filtered / RMS）。"""

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
        """ウィンドウ右上のステータス行を更新する。"""
        self.status.set_text(text)

    def is_open(self):
        """ウィンドウが閉じられていれば False。"""
        return plt.fignum_exists(self.fig.number)

    def push(self, raw, filtered, rms):
        """1サンプル分をバッファに追加する（描画は行わない）。"""
        self.sample_count += 1
        self.t.append(self.sample_count / self.fs)
        self.raw.append(raw)
        self.filtered.append(filtered)
        self.rms.append(rms)

    def maybe_redraw(self):
        """refresh_s 経過していれば再描画する。"""
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
        """ウィンドウを閉じる。"""
        plt.ioff()
        plt.close(self.fig)
