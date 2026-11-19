"""RMTC_GLOVE を RMS（包絡）で開閉するドライバ。

流れ:  GloveLink で接続 → 'device' ビーコン待ち → RMTC_GLOVE\r（即時）
      → DATA:v:...\\r を keepalive 再送（閉=100, 開=10）

しきい値は calibrate.AdaptiveThreshold が起動時に実測（安静→活動順）。
完了までは動かしません。
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
        self.calib = AdaptiveThreshold()  # 安静→活動の順で集める

    @property
    def ser(self):
        """後方互換のための参照（未接続なら None）。"""
        return self.link.ser if self.link is not None else None

    @property
    def last_send(self):
        """後方互換のための参照（未接続なら 0.0）。"""
        return self.link.last_send if self.link is not None else 0.0

    def connect(self):
        self.link = GloveLink(self.port, self.baudrate)
        print("[mirrorhand] 本体で MIRROR GUIDE → START の順に押してください。", flush=True)
        if not self.link.wait_for_beacon():
            raise SystemExit("[mirrorhand] 'device' が届きません。本体のモード設定を確認してください。")
        self.link.write("RMTC_GLOVE\r")              # 検出したら即ハンドシェイク
        self.closed = False
        self._send_all(OPEN)                          # 初期状態は開いたまま
        # 握手後も切れないように常時再送
        self.link.start_keepalive(lambda: CLOSE if self.closed else OPEN)
        print(f"[mirrorhand] 接続しました on {self.port}", flush=True)

    def _send_all(self, value):
        if self.link is not None:
            self.link.send_all(value)

    def update(self, rms_uv):
        """RMS [µV] を受け取り開閉する。閉じていれば True を返す。"""
        if self.link is None:
            return False
        if not self.calib.ready:              # キャリブレーション中は何もしない
            self.calib.push(rms_uv)
            return False
        if rms_uv >= self.calib.artifact_th:  # アーティファクト時は閉じない（安全側）
            if self.closed:
                self._transition(False, rms_uv, "ARTIFACT → OPEN")
            return False
        if self.closed:
            # release_th を連続 release_frames サンプル下回るまで OPEN しない
            if self.release_debounce.push(rms_uv <= self.calib.release_th):
                self._transition(False, rms_uv, "OPEN")
        else:
            if rms_uv >= self.calib.grip_th:
                self.release_debounce.reset()   # 握り始めたら数え直し
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
            self._send_all(OPEN)              # 終了時は開いておく
        except Exception:
            pass
        self.link.close()
        self.link = None
