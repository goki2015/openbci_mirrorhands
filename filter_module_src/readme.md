
`cargo build --release` の出力名は OS で変わります。

| ビルドしたOS | cargo の出力 | 置き換え先（名前は固定） |
|---|---|---|
| Linux | `target/release/libfilter_module.so` | `filter_module/_filter_module.abi3.so` |
| macOS | `target/release/libfilter_module.dylib` | `filter_module/_filter_module.abi3.so` |
| Windows | `target\release\filter_module.dll` | `filter_module\_filter_module.pyd` |

### Windows の場合（重要）

Windows の Python 拡張は `.so` ではなく **`.pyd`** です。しかもファイル名は **`_filter_module.pyd`** にしてください。

```text
× _filter_module.abi3.pyd   ← Windowsでは .abi3 付きは認識されない
○ _filter_module.pyd
```

`.pyd` は実体が DLL なので、`filter_module.dll` をリネームするだけで動きます。

```powershell
cd C:\path\to\filter_module
cargo build --release

copy target\release\filter_module.dll ^
     C:\path\to\openbci_mirrorhands\filter_module\_filter_module.pyd

cd C:\path\to\openbci_mirrorhands
uv sync
uv run main.py
```

## ビルド環境の前提

受け取った側に必要なもの：

| 項目 | 内容 |
|---|---|
| Rust | `rustup` でインストール |
| Windows | Visual Studio Build Tools（C++ によるデスクトップ開発） |
| Python | CPython 3.10 以上、かつ Rust と同じビット数（通常64bit） |
| Python 3.12+ | `openbci_mirrorhands` の `requires-python = ">=3.12"` のため |
