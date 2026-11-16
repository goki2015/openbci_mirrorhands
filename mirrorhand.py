"""RMTC_GLOVE ロボットグローブを RMS（包絡）値で開閉する小さなドライバ。

Archive/robot/update_project の SerialService と UDP 検証版 mirrorhand_udp.py の
手順を組み合わせたもの:

  1. 57600 / 8N1 で開く
  2. グローブが発する 'device' ビーコンを待つ         ← 本体で MIRROR GUIDE → START を押す
  3. ビーコンを見つけたら即 "RMTC_GLOVE\\r" を送る    （更新プログラムと同じハンドシェイク）
  4. "DATA:0:v:0:v:0:v:0:v:0:v\\r" (指5本分, 各0-100) を送り続ける
       閉=[100]*5, 開=[10]*5  (SerialService.send_grip / send_relax と同じ値)

main.py からの使い方:

    from mirrorhand import MirrorHand
    hand = MirrorHand(port="/dev/ttyUSB1")  # ボードは ttyUSB0。グローブはこちら推定
    hand.connect()        # ビーコン待ちでブロック（本体で MIRROR GUIDE → START を押す）
    # ...ループ内（新着サンプル処理後）:
    hand.update(float(rms[-1]))
    # ...finally 内:
    hand.close()

しきい値 GRIP_UV / RELEASE_UV は各人の電極・筋で変わるので要実測調整。
（参考実測: 安静 median 7.5 µV / 強握り median 39.7 µV、read_from_cython）
"""

"""

"""

import time

import serial

OPEN = 10       # 開いた状態のグローブ値 (0-100)
CLOSE = 100     # 握りの状態のグローブ値 (0-100)
GRIP_UV = 30.0      # これ以上で閉じる（µV）
RELEASE_UV = 15.0   # これ以下で開く（µV・差がヒステリシス）
SEND_INTERVAL = 0.2  # コマンドの再送間隔 [s]（keepalive）
BEACON_TIMEOUT = 180  # 'device' 待ちの上限 [s]


class MirrorHand:
    def __init__(self, port="/dev/ttyUSB1", baudrate=57600):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.closed = False
        self.last_send = 0.0

    def connect(self):
        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=1,
        )
        self.ser.reset_input_buffer()
        print("[mirrorhand] 本体で MIRROR GUIDE → START の順に押してください。")
        print("[mirrorhand] 'device' ビーコン待機中…", flush=True)
        self._wait_for_beacon()
        self._write("RMTC_GLOVE\r")    # ビーコン検出から即時にハンドシェイク
        self._send_all(OPEN)           # 初期状態は開いたまま
        self.closed = False
        print(f"[mirrorhand] 接続しました on {self.port}")

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
        v = int(round(value))
        packet = "DATA"
        for _ in range(5):
            packet += ":0:%d" % v
        packet += "\r"
        self._write(packet)
        self.last_send = time.time()

    def update(self, rms_uv):
        """RMS [µV] を受け取り開閉する。閉じていれば True を返す。"""
        if self.ser is None:
            return False

        if self.closed:
            if rms_uv <= RELEASE_UV:
                self.closed = False
                self._send_all(OPEN)
                print(f"[mirrorhand] OPEN  (rms={rms_uv:.2f})")
        else:
            if rms_uv >= GRIP_UV:
                self.closed = True
                self._send_all(CLOSE)
                print(f"[mirrorhand] CLOSE (rms={rms_uv:.2f})")

        # keepalive: 状態が変わっても変わらなくても一定間隔で送る
        now = time.time()
        if now - self.last_send >= SEND_INTERVAL:
            self._send_all(CLOSE if self.closed else OPEN)

        return self.closed

    def close(self):
        if self.ser is not None:
            try:
                self._send_all(OPEN)      # 終了時は開いておく
            except Exception:
                pass
            self.ser.close()
            self.ser = None
