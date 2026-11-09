from brainflow.board_shim import BoardIds,BoardShim,BrainFlowInputParams
from brainflow.data_filter import DataFilter, FilterTypes
import time
from collections import deque
import numpy as np
from filter_module import apply_filter
from scipy import signal

settings = {
    "port":"/dev/ttyUSB0",
    "BAND":(5.0,110),
    "BAND_ORDER":4,
    "NOTCH_F":((48,52),(98,102)), #for 50Hz in JP
    "RMS_MS":200/1000,
}

def temp_rms(buf,fs) -> np.ndarray:
    x = np.array(buf,dtype=float)
    w = max(1, int(round( settings["RMS_MS"] * fs)))
    return np.sqrt(signal.lfilter(np.ones(w) / w, [1.0], x * x))

def main():
    board_id = BoardIds.CYTON_BOARD.value
    params = BrainFlowInputParams()
    params.serial_port = settings["port"]
    params.timeout = 15
    BoardShim.disable_board_logger()

    print(str(board_id)+"\n"+str(params))
    board = BoardShim(board_id,params)
    board.prepare_session()
    fs = BoardShim.get_sampling_rate(board_id)

    board.start_stream(45000)

    raw_buf:deque[float] = deque(maxlen=int(fs*(settings["RMS_MS"])))
    ch = BoardShim.get_exg_channels(board_id)[0]

    try:
        while True:
            data = board.get_board_data()
            if data.shape[1] == 0:
                time.sleep(1/fs)
                continue
            new = data[ch]
            raw_buf.extend(float(v) for v in new)
            filtered_buf = apply_filter(raw_buf,fs)
            rms = temp_rms(filtered_buf,fs)

            for i, v in enumerate(new):
                print(f"RAWDATA:{float(v)}")
                print(f"FILTER_DATA:{filtered_buf[-len(new)+i]}")
                print(f"RMS:{rms[-len(new)+i]}")

    except KeyboardInterrupt:
        print("stop")
    finally:
        board.stop_stream()
        board.release_session()


if __name__ == "__main__":
    main()
