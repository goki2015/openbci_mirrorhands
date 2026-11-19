from brainflow.board_shim import BoardIds,BoardShim,BrainFlowInputParams
import argparse
import time
from filter_module_scipy import StreamingFilter
from mirrorhand import MirrorHand

settings = {"port":"/dev/ttyUSB0", "verbose":False}

def main():
    parser = argparse.ArgumentParser(description="EMG でミラーハンドを開閉する")
    parser.add_argument("--gui", action="store_true",
                        help="OpenBCI の生波形・フィルタ後・RMS をライブ表示する（実時間性が下がる可能性あり）")
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

    filt = StreamingFilter(fs=float(fs))   # 50/100 Hz ノッチ → 5–110 Hz BP(4次) → RMS(200 ms)

    wave = None
    if args.gui:
        from wave_gui import LiveWave     # --gui のときだけ matplotlib を読み込む
        wave = LiveWave(fs=float(fs))
        print("[gui] 波形ウィンドウを表示します（実時間性が下がる可能性があります）")

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
