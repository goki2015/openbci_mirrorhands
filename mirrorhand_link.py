"""Communication layer for RMTC_GLOVE: connect -> wait for the 'device' beacon -> handshake -> keepalive re-send.

Extracted from MirrorHand - only protocol I/O lives here. The open/close decision stays in MirrorHand.
"""
import threading
import time

import serial

OPEN = 10          # value for the open state (0-100)
CLOSE = 100        # value for the closed state (0-100)
SEND_INTERVAL = 0.2    # keepalive re-send interval [s]
BEACON_TIMEOUT = 180   # limit for waiting for 'device' [s]


class GloveLink:
    """Wait for the 'device' beacon, perform the RMTC_GLOVE handshake, and re-send DATA keepalives."""

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
        """Wait for 'device'. Returns True when received, False on timeout."""
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
        # send one 'DATA' + ':0:v'x5 packet (v=100 to close, 10 to open)
        packet = "DATA"
        for _ in range(5):
            packet += ":0:%d" % int(round(value))
        packet += "\r"
        self.write(packet)
        self.last_send = time.time()

    def start_keepalive(self, value_fn):
        """Start a thread that re-sends the value returned by value_fn() every SEND_INTERVAL seconds."""
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                self.send_all(value_fn())
                time.sleep(SEND_INTERVAL)

        self._ka_thread = threading.Thread(target=loop, daemon=True)
        self._ka_thread.start()

    def stop_keepalive(self):
        """Stop the keepalive thread (call before exit)."""
        self._stop.set()
        if self._ka_thread is not None:
            self._ka_thread.join(timeout=0.5)

    def close(self):
        self.ser.close()
