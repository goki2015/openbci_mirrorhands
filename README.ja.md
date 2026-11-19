# openbci_mirrorhands

[English](README.md) | 日本語

OpenBCI Cyton の EMG 信号でミラーハンド（グローブ）を動かすサンプルです。
EMG は PC 上でオンライン処理され、起動時にユーザーごとの閾値モデルを校正し、
USB シリアル経由でグローブをリアルタイムに開閉します。

```
OpenBCI Cyton (EXG Ch0)
    │  250 Hz
    ▼
因果フィルタチェーン（scipy 設計）: 50Hz ノッチ → 100Hz ノッチ → 5–110Hz バンドパス（4次）→ RMS（200ms）
    ▼
AdaptiveThreshold: 安静フェーズ → 活動フェーズ → grip / release / artifact 閾値
    ▼  rms ≥ grip_th                    ▼  rms ≤ release_th（連続30サンプル）
MirrorHand: CLOSE                    MirrorHand: OPEN
    ▼
RMTC_GLOVE プロトコル（USB シリアル 57600 8N1、0.2秒周期で keepalive 再送）
```

## 必要なもの

- Linux PC（`/dev/ttyUSB*` のパスを前提）
- Python ≥ 3.12 と [uv](https://docs.astral.sh/uv/)
- ハードウェア: OpenBCI Cyton、RMTC_GLOVE 互換ミラーハンドグローブ
- 依存ライブラリ（`uv sync` で導入）: brainflow, numpy, pyserial, scipy, matplotlib

## セットアップ

```bash
git clone <this repo>
cd openbci_mirrorhands
uv sync
```

## 使い方

```bash
uv run main.py         # GUIなしで実行（実時間性重視）
uv run main.py --gui   # Raw / Filtered / RMS の波形をライブ表示（実時間性が下がる可能性あり）
```

1. Cyton を `/dev/ttyUSB0`、グローブを `/dev/ttyUSB1` に接続します
   （異なる場合は `main.py` を編集: ボードは `settings["port"]`、グローブは `MirrorHand(port=...)`）。
2. グローブ本体で **MIRROR GUIDE → START** を押します。`device` ビーコン待ちの後、
   `RMTC_GLOVE` で握手し、初期状態は開いたままになります。
3. 校正が走ります: 安静にしたまま約6秒 → **Enter** → 強く握ったまま約6秒。
   完了すると閾値（`grip=… release=… artifact=… gap=… dB`）が表示されます。
4. 実行モード: `rms ≥ grip_th` で閉じ、**rms が release_th 以下に30サンプル連続で
   とどまって初めて開きます**（デバウンス。`release_debounce.py` 参照）。
   巨大なアーティファクト（`rms ≥ artifact_th`）では安全側に倒して強制的に開きます。
5. **Ctrl+C** で終了: グローブは開き、ボードのセッションが解放されます。

## 動作確認

- `uv run test/test_wave_gui.py` — Cyton から生データを取得し、波形を GUI 表示します
  （グローブ不要）。校正・判定ロジックは `main.py` と同じですが、`MirrorHand` を
  仮リンクに差し替えるため、手袋には何も送信されません。波形と判定状況を見ながら
  動作確認できます。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `main.py` | エントリポイント: Cyton 取得 → フィルタ → グローブ |
| `mirrorhand.py` | 開閉判定ロジック、校正のオーケストレーション |
| `mirrorhand_link.py` | グローブのシリアル通信層（ビーコン待ち、握手、keepalive） |
| `release_debounce.py` | release 側デバウンス（N連続で下回るまで OPEN しない） |
| `calibrate.py` | `AdaptiveThreshold`: 安静→活動の校正、パーセンタイルベースの閾値計算 |
| `filter_module_scipy.py` | scipy で係数設計した因果リアルタイム EMG フィルタ |
| `filter_module_py.py` | 標準ライブラリのみの同等実装（差し替え可能） |
| `wave_gui.py` | `main.py --gui` によるライブ波形ビューア（matplotlib） |
| `test/test_wave_gui.py` | OpenBCI 動作確認: 生データを GUI 表示（グローブ不要） |
| `LICENSE` | MIT |

ローカル専用のファイル・ディレクトリ（`docs/`、`filter_module/`、`filter_module_src/`、
`test_emg_pipeline.py`、`test_glove_buttons.py`）は意図的に gitignore でリポジトリに含めていません。

## 実装メモ

- **リアルタイムフィルタ**: 因果カスケード（50/100 Hz ノッチ → 5–110 Hz 4次バンドパス →
  200 ms 移動 RMS）。`passes=2` により filtfilt の |H|² と同じマグニチュード特性を、
  先読みなしで実現します。状態は最初のサンプルの定常値で初期化し、
  異常サンプル（0 / 非有限 / |x|>1e5）は因果的な線形補外（最大0.1秒）で置き換えます。
- **閾値校正**（`calibrate.py`）: p50 中央値ベースの anchor（幾何平均）、
  最悪ケース分離 `gap_db = 20·log10(grip_p10 / rest_p90)` を p10/p90 で保守的に見積もり、
  最終的な grip 閾値は `rest_p90 × 1.5` を下回らないようにクランプします。
- **Release デバウンス**（`release_debounce.py`）: rms が `release_th` 以下に
  `release_frames` 連続（デフォルト30 = 250Hzで0.12秒）とどまるまでは開きません。
  1サンプルでも release_th を上回るとカウンタは0に戻ります。CLOSE 時にはカウンタを再アームします。
- **グローブのプロトコル**: `device` ビーコン → 即座に `RMTC_GLOVE\r` →
  5個の `DATA:0:v` フィールドを1パケットとするコマンド（`v=100` 閉、`v=10` 開）を
  0.2秒周期で再送（keepalive）します。
- **Rust フィルタ**: 元々は Rust 拡張でしたが、現在は数値的に同一
  （絶対誤差 ≤5e-13 で検証済み）な scipy ベースの Python フィルタを既定にしています。
  Rust 版はローカルで使えますが、リポジトリには追跡していません。

## 免責事項

- 本プロジェクトは OpenBCI 社およびグローブのメーカーとは **一切関係ありません**。その公認・認証を受けたものでもありません。
- 本コードは非公式の教育・研究目的の実装です。使用は自己責任で行ってください。
- 本プロジェクトはホビー／研究目的であり、**医療機器ではありません**。

## ライセンス

MIT（`LICENSE` 参照）。
