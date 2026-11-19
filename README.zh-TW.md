# openbci_mirrorhands

[English](README.md) | [日本語](README.ja.md) | 繁體中文（台灣）

以 OpenBCI Cyton 的肌電訊號（EMG）驅動的鏡像手（手套）範例程式。
EMG 在 PC 上進行線上處理，啟動時會為每位使用者校準閾值模型，
再透過 USB 串列埠即時開合手套。

```
OpenBCI Cyton (EXG Ch0)
    │  250 Hz
    ▼
因果濾波器鏈（以 scipy 設計）: 50Hz 帶阻 → 100Hz 帶阻 → 5–110Hz 帶通（4次）→ RMS（200ms）
    ▼
AdaptiveThreshold: 靜息階段 → 用力階段 → grip / release / artifact 閾值
    ▼  rms ≥ grip_th                    ▼  rms ≤ release_th（連續30個樣本）
MirrorHand: CLOSE                    MirrorHand: OPEN
    ▼
RMTC_GLOVE 協定（USB 串列埠 57600 8N1，每 0.2 秒 keepalive 重送）
```

## 需求環境

- Linux PC（以 `/dev/ttyUSB*` 裝置路徑為前提）
- Python ≥ 3.12 與 [uv](https://docs.astral.sh/uv/)
- 硬體：OpenBCI Cyton、RMTC_GLOVE 相容的鏡像手手套
- 相依套件（以 `uv sync` 安裝）：brainflow, numpy, pyserial, scipy

## 安裝

```bash
git clone <this repo>
cd openbci_mirrorhands
uv sync
```

## 使用方式

```bash
uv run main.py
```

1. 將 Cyton 接上 `/dev/ttyUSB0`，手套接上 `/dev/ttyUSB1`
   （若裝置路徑不同，請修改 `main.py`：開發板是 `settings["port"]`，手套是 `MirrorHand(port=...)`）。
2. 在手套本體按 **MIRROR GUIDE → START**。程式會等待 `device` 信標，
   以 `RMTC_GLOVE` 握手後，初始狀態保持開啟。
3. 校準開始：保持放鬆約 6 秒 → 按 **Enter** → 用力握緊並持續約 6 秒。
   完成後會印出閾值（`grip=… release=… artifact=… gap=… dB`）。
4. 執行模式：`rms ≥ grip_th` 時手會閉合；**唯有 rms 連續 30 個樣本
   都維持在 release_th 以下才會張開**（去抖動，見 `release_debounce.py`）。
   若出現巨大雜訊（`rms ≥ artifact_th`），會以安全側為原則強制張開手。
5. **Ctrl+C** 結束：手套會張開，開發板的 session 會被釋放。

## 驗證用程式（本機開發用）

- `test_emg_pipeline.py` — 僅以 Cyton（不接手套）執行相同流程，
  印出閾值與判定結果，並比較 scipy 與 Rust 版濾波器的一致性（送信目標為假的 FakeLink）。
  本 repo 未追蹤此檔案（已列入 gitignore）。
- `test_glove_buttons.py` — 手套單獨的冒煙測試（握手 → CLOSE → OPEN）。

## 檔案構成

| 檔案 | 角色 |
|---|---|
| `main.py` | 進入點：Cyton 收集 → 濾波 → 手套 |
| `mirrorhand.py` | 開合判定邏輯、校準流程的協調 |
| `mirrorhand_link.py` | 手套的串列通訊層（等待信標、握手、keepalive） |
| `release_debounce.py` | release 側去抖動（連續 N 個樣本低於閾值才 OPEN） |
| `calibrate.py` | `AdaptiveThreshold`：靜息→用力的校準、以百分位數計算閾值 |
| `filter_module_scipy.py` | 以 scipy 設計係數的因果即時 EMG 濾波器 |
| `filter_module_py.py` | 僅用標準函式庫的等價實作（可替換使用） |
| `filter_module/`, `filter_module_src/` | Rust 擴充模組與其原始碼（僅本機使用，不追蹤於 repo） |
| `docs/` | 詳細文件（日文、HTML） |
| `test_emg_pipeline.py` | 僅 OpenBCI 的驗證程式（本機專用） |
| `test_glove_buttons.py` | 手套單獨測試 |

## 實作說明

- **即時濾波器**：因果串接（50/100 Hz 帶阻 → 5–110 Hz 4 次帶通 →
  200 ms 移動 RMS）。`passes=2` 可在不預看未來樣本的前提下，
  重現 filtfilt 的 |H|² 振幅響應。狀態以第一個樣本的穩態值初始化，
  異常樣本（0／非有限值／|x|>1e5）以因果的線性外推（最多 0.1 秒）取代。
- **閾值校準**（`calibrate.py`）：以 p50 中位數為基礎取 anchor（幾何平均），
  最差情況的分離度 `gap_db = 20·log10(grip_p10 / rest_p90)`，
  以 p10/p90 保守估計；最終 grip 閾值不會低於 `rest_p90 × 1.5`。
- **Release 去抖動**（`release_debounce.py`）：rms 連續 `release_frames` 個樣本
  （預設 30 = 250Hz 下 0.12 秒）維持在 `release_th` 以下才會張開。
  只要有一個樣本高於 release_th，計數器就歸零。CLOSE 時會重新計數。
- **手套通訊協定**：`device` 信標 → 立即送出 `RMTC_GLOVE\r` →
  每個封包含 5 個 `DATA:0:v` 欄位（`v=100` 閉合、`v=10` 張開），
  每 0.2 秒重送一次（keepalive）。
- **Rust 版濾波器**：最初以 Rust 擴充模組實作，目前預設改用數值等價
  （已驗證絕對誤差 ≤ 5e-13）的 scipy 版 Python 濾波器。
  Rust 版仍可在本機使用，但不追蹤於此 repo 中。

## 授權

MIT（見 `LICENSE`）。
