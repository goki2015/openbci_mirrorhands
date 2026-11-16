"""RMTC_GLOVE を RMS（包絡）で開閉するドライバ。

流れ:  57600/8N1で開く → 'device' ビーコン待ち → RMTC_GLOVE\\r（即時）
      → DATA:v:...\\r を keepalive 再送（閉=100, 開=10）

しきい値は calibrate.AdaptiveThreshold が起動時に実測（安静→活動順）。
完了までは動かしません。
"""
import time
import threading
import serial
from calibrate import AdaptiveThreshold

OPEN = 10       # 開いた状態の値 (0-100)
CLOSE = 100     # 閉じた状態の値 (0-100)
SEND_INTERVAL = 0.2     # keepalive 再送間隔 [s]
BEACON_TIMEOUT = 180    # 'device' 待ちの上限 [s]


class MirrorHand:
    def __init__(self, port="/dev/ttyUSB1", baudrate=57600):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.closed = False
        self.last_send = 0.0
        self.calib = AdaptiveThreshold()  # 安静→活動の順で集める
        self._stop_keepalive = threading.Event()
        self._ka_thread = None

    def connect(self):
        self.ser = serial.Serial(port=self.port, baudrate=self.baudrate,
                                 bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                                 stopbits=serial.STOPBITS_ONE,
                                 timeout=0.05, write_timeout=1)
        self.ser.reset_input_buffer()
        print("[mirrorhand] 本体で MIRROR GUIDE → START の順に押してください。", flush=True)
        self._wait_for_beacon()
        self._write("RMTC_GLOVE\r")              # 検出したら即ハンドシェイク
        self._send_all(OPEN)                     # 初期状態は開いたまま
        self.closed = False
        self._stop_keepalive.clear()
        self._ka_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
        self._ka_thread.start()                  # ← 握手後も切れないように常時再送
        print(f"[mirrorhand] 接続しました on {self.port}", flush=True)

    def _wait_for_beacon(self):
        t0 = time.time()
        buf = b""
        while time.time() - t0 < BEACON_TIMEOUT:
            chunk = self.ser.read(256)
            if chunk:
                buf += chunk
                if b"device" in buf:
                    return
            else:
                time.sleep(0.01)
        raise SystemExit("[mirrorhand] 'device' が届きません。本体のモード設定を確認してください。")

    def _write(self, text):
        self.ser.write(text.encode("ascii"))

    def _send_all(self, value):
        packet = "DATA"
        for _ in range(5):
            packet += ":0:%d" % int(round(value))
        packet += "\r"
        self._write(packet)
        self.last_send = time.time()

    def update(self, rms_uv):
        """RMS [µV] を受け取り開閉する。閉じていれば True を返す。"""
        if self.ser is None:
            return False
        if not self.calib.ready:              # キャリブレーション中は何もしない
            self.calib.push(rms_uv)
            return False
        if rms_uv >= self.calib.artifact_th:  # アーティファクト時は閉じない（安全側）
            if self.closed:
                self._transition(False, rms_uv, "ARTIFACT → OPEN")
            return False
        if self.closed:
            if rms_uv <= self.calib.release_th:
                self._transition(False, rms_uv, "OPEN")
        else:
            if rms_uv >= self.calib.grip_th:
                self._transition(True, rms_uv, "CLOSE")
        return self.closed

    def _transition(self, closed, rms_uv, label):
        self.closed = closed
        self._send_all(CLOSE if closed else OPEN)
        print(f"[mirrorhand] {label} (rms={rms_uv:.2f})")

    def _keepalive_loop(self):
        while not self._stop_keepalive.is_set():
            self._send_all(CLOSE if self.closed else OPEN)
            time.sleep(SEND_INTERVAL)

    def close(self):
        if self.ser is not None:
            self._stop_keepalive.set()
            if self._ka_thread is not None:
                self._ka_thread.join(timeout=0.5)
            try:
                self._send_all(OPEN)          # 終了時は開いておく
            except Exception:
                pass
            self.ser.close()
            self.ser = None
