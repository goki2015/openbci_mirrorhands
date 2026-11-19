"""RMTC_GLOVE との通信層: 接続 → 'device' ビーコン待ち → 握手 → keepalive 再送。

MirrorHand から通信手順だけを切り出したもの。開閉の判定は MirrorHand 側が持つ。
"""
import threading
import time

import serial

OPEN = 10          # 開いた状態の値 (0-100)
CLOSE = 100        # 閉じた状態の値 (0-100)
SEND_INTERVAL = 0.2    # keepalive 再送間隔 [s]
BEACON_TIMEOUT = 180   # 'device' 待ちの上限 [s]


class GloveLink:
    """'device' ビーコン待ち→RMTC_GLOVE 握手→DATA keepalive 再送を担当する。"""

    def __init__(self, port, baudrate=57600):
        self.ser = serial.Serial(port=port, baudrate=baudrate,
                                 bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                                 stopbits=serial.STOPBITS_ONE,
                                 timeout=0.05, write_timeout=1)
        self.ser.reset_input_buffer()
        self.last_send = 0.0
        self._stop = threading.Event()
        self._ka_thread = None

    def wait_for_beacon(self):
        """'device' を待つ。届いたら True、タイムアウトなら False。"""
        t0 = time.time()
        buf = b""
        while time.time() - t0 < BEACON_TIMEOUT:
            chunk = self.ser.read(256)
            if chunk:
                buf += chunk
                if b"device" in buf:
                    return True
            else:
                time.sleep(0.01)
        return False

    def write(self, text):
        self.ser.write(text.encode("ascii"))

    def send_all(self, value):
        # 'DATA' + ':0:v'×5 の1パケットを送る（v=100 で閉、10 で開）
        packet = "DATA"
        for _ in range(5):
            packet += ":0:%d" % int(round(value))
        packet += "\r"
        self.write(packet)
        self.last_send = time.time()

    def start_keepalive(self, value_fn):
        """value_fn() が返す値を SEND_INTERVAL 秒ごとに再送し続けるスレッドを起動する。"""
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                self.send_all(value_fn())
                time.sleep(SEND_INTERVAL)

        self._ka_thread = threading.Thread(target=loop, daemon=True)
        self._ka_thread.start()

    def stop_keepalive(self):
        """keepalive スレッドを止める（終了前に呼ぶ）。"""
        self._stop.set()
        if self._ka_thread is not None:
            self._ka_thread.join(timeout=0.5)

    def close(self):
        self.ser.close()
