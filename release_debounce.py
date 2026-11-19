"""release 側のデバウンス（時間方向の安定化）。

EMG の RMS は 1 サンプルだけ release_th を下回ることがある（安静のように見える
一瞬）。その瞬間に OPEN を送ると手袋がパタパタ開閉してしまうため、
「release_th を frames 回 連続で下回ったときだけ OPEN を許可する」。

使い方（MirrorHand.update 内）:

    if self.release_debounce.push(rms_uv <= release_th):
        ...  # OPEN してよい

- 下回っている（True）を渡せばカウンタが 1 増える
- 上回っている（False）を渡せばカウンタは 0 に戻る
- frames 連続で True が続いたときだけ True を返す
"""

DEFAULT_RELEASE_FRAMES = 30  # 250 Hz サンプリングなら 0.12 秒相当


class ReleaseDebounce:
    """release_th を連続で下回ったサンプル数を数えるクラス。"""

    def __init__(self, frames=DEFAULT_RELEASE_FRAMES):
        # 1 未満は意味がないので 1 に丸める
        self.frames = max(1, int(frames))
        self.count = 0

    def reset(self):
        """カウントを最初から数え直す（CLOSE した直後などに呼ぶ）。"""
        self.count = 0

    def push(self, is_below_release):
        """1 サンプル分を投入し、OPEN してよければ True を返す。

        Args:
            is_below_release: 今回の RMS が release_th 以下なら True。

        Returns:
            frames 連続で is_below_release が True のときだけ True。
        """
        if is_below_release:
            self.count += 1
        else:
            self.count = 0
        return self.count >= self.frames
