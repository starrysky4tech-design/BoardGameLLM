# 設計書

## アーキテクチャ概要

使い捨ての検証スクリプトを `scripts/phase0/` に置き、結果（画像・計測値・メモ）を `datasets/phase0/` に出力する。本実装の `src/bglm/` にはまだ書かない。ただし、検証の成果のうち再利用できる取得・入力のコードは、Phase 1 で `infrastructure/` へ移すことを前提に `docs/02` の `ScreenSource` / `InputDriver` の形で書く。

```
scripts/phase0/
├── adb_capture.py        # Android の画面取得と tap
├── win_capture.py        # PC ウィンドウの取得と入力
└── vram_log.py           # nvidia-smi の定期記録
datasets/phase0/          # 撮影画像と計測ログ（Git管理外）
```

## コンポーネント設計

### 1. adb_capture.py

**責務**:
- 指定シリアルの端末から画面を取得して保存する
- 指定座標に tap を送る

**実装の要点**:
- `adb -s <serial> exec-out screencap -p` を使い、シリアルを必ず指定する（`docs/05`）
- 入力は端末の物理座標系。縦向きの Kahuna で座標が一致するか確かめる
- 端末の画面を変える操作（アプリの削除など）は入れない

### 2. win_capture.py

**責務**:
- ゲームウィンドウのクライアント領域を取得する
- ウィンドウ相対座標をスクリーン座標に変換して入力を送る

**実装の要点**:
- 取得は `mss` を第一候補にし、黒画面になる場合は別方式（PrintWindow、Windows Graphics Capture）を試す
- 入力は `pydirectinput` を第一候補にし、届かない場合は `SendInput` を直接使う、管理者権限で実行する、の順に試す
- 検証の安全のため、クリック前にゲームウィンドウが前面にあることを確認する

### 3. vram_log.py

**責務**: 一定間隔で `nvidia-smi` を呼び、GPUメモリ使用量を CSV に記録する。

**実装の要点**: ゲーム単体、ゲームと VLM の同時、VLM 単体の3条件で記録を分ける。

## データフロー

### VRAM の測定
```
1. vram_log.py を起動する
2. ユーザーが大戦略SSB2 を起動してマップを開始する
3. 一定時間（スクロール、拡縮を含む）記録する
4. Ollama で Qwen3-VL-2B を実行して同時の使用量を記録する
5. 載らない場合は CPU 実行にして 1 回あたりの時間を測る
```

## エラーハンドリング戦略

検証スクリプトは失敗の内容を握りつぶさず、そのまま出力する。結果の「失敗」も検証結果として記録する。

## テスト戦略

検証スクリプトは使い捨てなのでユニットテストは書かない。再利用するコードを Phase 1 で移す際に、テストを付ける。

## 依存ライブラリ

`docs/03` の常時利用ライブラリのうち、検証に必要なものだけを入れる。

```toml
dependencies = ["numpy", "opencv-python", "mss", "pywin32", "pydirectinput", "pillow"]
```

開発用: `ruff`、`mypy`、`pytest`、`pytest-cov`、`import-linter`

## ディレクトリ構造

```
BoardGameLLM/
├── pyproject.toml
├── scripts/phase0/
├── scripts/check.ps1
├── src/bglm/__init__.py      # 空のパッケージ
├── tests/unit/               # 空
└── datasets/phase0/          # Git管理外
```

## 実装の順序

1. 土台（pyproject、check.ps1、空のパッケージ）
2. Kahuna（`adb` の取得と tap）— ユーザー操作が不要で、すぐ着手できる
3. VRAM のベースライン（ゲーム無しの状態と Ollama 単体）
4. 大戦略SSB2（ユーザーがゲームを起動したあとに実施）
5. 結果の反映

## セキュリティ考慮事項

- `adb` はシリアルを指定して呼ぶ。他の端末を操作しない
- ゲーム画面の画像はコミットしない

## パフォーマンス考慮事項

- 1枚の取得時間を記録し、`docs/03` の見積もり（認識前の取得時間）の根拠にする

## 将来の拡張性

検証で使ったコードのうち再利用するものは、Phase 1 で `src/bglm/infrastructure/` へ移し、`GameIo` の下に組み込む。
