from brainflow.board_shim import BoardIds,BoardShim,BrainFlowInputParams
import time
from filter_module import StreamingFilter
from mirrorhand import MirrorHand

settings = {"port":"/dev/ttyUSB0", "verbose":False}

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

    filt = StreamingFilter(fs=float(fs))   # 50/100 Hz ノッチ → 5–110 Hz BP(4次) → RMS(200 ms)
    hand = MirrorHand(port="/dev/ttyUSB1") # グローブは ttyUSB1 と推定して選択
    hand.connect()                         # ビーコン待ちでブロック（本体で MIRROR GUIDE → START）

    board.start_stream(45000)
    ch = BoardShim.get_exg_channels(board_id)[0]

    try:
        while True:
            data = board.get_board_data()
            if data.shape[1] == 0:
                time.sleep(1/fs)
                continue
            new = data[ch]
            for v in new:
                fval, rms = filt.process(float(v))
                if settings["verbose"]:
                    print(f"RAWDATA:{float(v)}")
                    print(f"FILTER_DATA:{fval}")
                    print(f"RMS:{rms}")
                hand.update(rms)

    except KeyboardInterrupt:
        print("stop")
    finally:
        hand.close()
        board.stop_stream()
        board.release_session()

if __name__ == "__main__":
    main()
