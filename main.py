from brainflow.board_shim import BoardIds,BoardShim,BrainFlowInputParams
from brainflow.data_filter import DataFilter, FilterTypes
import time
from collections import deque

settings = {
    "port":"/dev/ttyUSB0",
    "BAND":(5.0,110),
    "BAND_ORDER":4,
    "NOTCH_F":(50,100),
    "NOTCH_Q":30,
    "RMS_MS":200,
}


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

    raw_buf:deque[float] = deque(maxlen=int(fs*(settings["RMS_MS"]/1000)))
    ch = BoardShim.get_exg_channels(board_id)[0]

    try:
        while True:
            data = board.get_board_data()
            if data.shape[1] == 0:
                time.sleep(1/fs)
                continue
            new = data[ch]
            raw_buf.extend(float(v) for v in new)

            k = min(len(new), len(raw_buf))

            raws = new[-k:]
            for i in range(k):
                print(f"RAWDATA:{float(raws[i])}")


    except KeyboardInterrupt:
        print("stop")


if __name__ == "__main__":
    main()
