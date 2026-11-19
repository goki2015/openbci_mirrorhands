"""read_from_cython の emg-calibration に倣った適用型しきい値。

安静フェーズ→活動フェーズの順で RMS を収集する:
  1. マイグレーション: 起動過渡を捨てる (flush_samples サンプル破棄後から計測)
  2. 安静フェーズ: rest_s 秒収集
  3. Enter 待ち → 捨てタイマ開始 (flush_samples サンプル破棄後から握り計測)
  4. 活動フェーズ: grip_s 秒収集
  5. クランプつき幾何平均でしきい値を決定し ready=True にする

クランプ: しきい値は他のパラメータにかかわらず rest_p90 × 1.5 以下にはしない
(無効な校正で走り出さないようにするため)

使い方:
    from calibrate import AdaptiveThreshold
    cal = AdaptiveThreshold()
    cal.push(env)
    if cal.ready:
        cal.grip_th, cal.release_th, cal.artifact_th
"""

import math


def percentile(values, p):
    """線形補間のパーセンタイル。空なら 0.0。"""
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
    """安静→活動の順で collectする方式のしきい値算出器。"""

    def __init__(self, fs=250.0, rest_s=6.0, grip_s=6.0,
                 release_ratio=0.4, artifact_ratio=4.0, threshold_bias=0.5,
                 interactive=True, flush_samples=250):
        self.rest_n = max(1, int(fs * rest_s))
        self.grip_n = max(1, int(fs * grip_s))
        self.release_ratio = release_ratio
        self.artifact_ratio = artifact_ratio
        self.threshold_bias = threshold_bias
        self.interactive = interactive
        self.flush_left = flush_samples     # 起動過渡を破棄
        self.flush_samples = flush_samples
        self.rest = []
        self.grip = []
        self.ready = False
        self.valid = False
        self.grip_th = 30.0
        self.release_th = 15.0
        self.artifact_th = 200.0

    def push(self, env):
        """RMS 包絡 [uVrms] を 1 つ投入する。完了後は何もしない。"""
        if self.ready:
            return
        if self.flush_left > 0:              # 過渡区間を捨てる
            self.flush_left -= 1
            return
        if len(self.rest) < self.rest_n:
            self.rest.append(env)
            if len(self.rest) == self.rest_n:
                rest_med = max(percentile(self.rest, 50.0), 1e-6)
                print(f"[calib] rest_med = {rest_med:.2f} µV", flush=True)
                if self.interactive:
                    print("[calib] 強く握り続けて Enter を押してください → ", flush=True, end="")
                    try:
                        input()
                    except EOFError:
                        pass
                    print("[calib] 1秒間のバッファを捨ててから測定を再開します", flush=True)
                self.flush_left = self.flush_samples    # Enter待ちのバックログを捨てる
            return
        self.grip.append(env)
        if len(self.grip) == self.grip_n:
            self._compute()

    def _compute(self):
        rest_med = max(percentile(self.rest, 50.0), 1e-6)   #restの50％付近の値を取るなければ線形補間で作り1e-6より下回ればこっち。
        grip_med = max(percentile(self.grip, 50.0), rest_med * 2.0)
        anchor = math.sqrt(rest_med * grip_med)
        rest_ub = max(percentile(self.rest, 90.0), 1e-6)
        grip_lb = max(percentile(self.grip, 10.0), 1e-6)
        gap_db = 20.0 * math.log10(grip_lb / rest_ub)

        # gap > 0 のときだけ bias シフトを適用（負ならゼロシフト=anchor据え置き）
        grip = anchor if gap_db <= 0.0 else anchor * 10.0 ** (self.threshold_bias * gap_db / 20.0)
        grip = max(grip, rest_ub * 1.5)            # 安静の上裾 ×1.5 より下には置かない

        self.grip_th = grip
        self.release_th = grip * self.release_ratio
        self.artifact_th = grip_med * self.artifact_ratio
        self.ready = True
        self.valid = (gap_db > 0.0)
        note = "" if self.valid else "  [WARN: gap<=0 — 分離不足のため anchor + クランプで動作]"
        print(f"[calib] 完了: grip={grip:.4f} µV release={self.release_th:.4f} µV "
              f"artifact={self.artifact_th:.4f} µV gap={gap_db:+.2f} dB{note}", flush=True)
