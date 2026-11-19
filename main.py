from brainflow.board_shim import BoardIds,BoardShim,BrainFlowInputParams
import argparse
import time
from filter_module_scipy import StreamingFilter
from mirrorhand import MirrorHand

settings = {"port":"/dev/ttyUSB0", "verbose":False}

def main():
    parser = argparse.ArgumentParser(description="Drive the mirror hand with EMG")
    parser.add_argument("--gui", action="store_true",
                        help="Show the live raw / filtered / RMS waveforms (may reduce real-time performance)")
    args = parser.parse_args()

    board_id = BoardIds.CYTON_BOARD.value
    params = BrainFlowInputParams()
    params.serial_port = settings["port"]
    params.timeout = 15
    BoardShim.disable_board_logger()

    print(str(board_id)+"\n"+str(params))
    board = BoardShim(board_id,params)
    board.prepare_session()
    fs = BoardShim.get_sampling_rate(board_id)

    filt = StreamingFilter(fs=float(fs))   # 50/100 Hz notch -> 5-110 Hz BP (4th order) -> RMS (200 ms)

    wave = None
    if args.gui:
        from wave_gui import LiveWave     # import matplotlib only when --gui is used
        wave = LiveWave(fs=float(fs))
        print("[gui] showing the waveform window (may reduce real-time performance)")

    hand = MirrorHand(port="/dev/ttyUSB1") # the glove is assumed to be on ttyUSB1
    hand.connect()                         # blocks until the beacon arrives (press MIRROR GUIDE -> START on the glove)

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
                v = float(v)
                fval, rms = filt.process(v)
                if wave is not None:
                    wave.push(v, fval, rms)
                if settings["verbose"]:
                    print(f"RAWDATA:{v}")
                    print(f"FILTER_DATA:{fval}")
                    print(f"RMS:{rms}")
                hand.update(rms)
            if wave is not None:
                wave.maybe_redraw()

    except KeyboardInterrupt:
        print("stop")
    finally:
        if wave is not None:
            wave.close()
        hand.close()
        board.stop_stream()
        board.release_session()

if __name__ == "__main__":
    main()
