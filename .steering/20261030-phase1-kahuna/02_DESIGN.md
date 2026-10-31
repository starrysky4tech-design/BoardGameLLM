# 設計書

## アーキテクチャ概要

`docs/03` のレイヤー構成（CLI / Application / Plugin・Infrastructure・Toolkit / Core）に従う。ファイルの配置は `docs/04` の「実装ファイル一覧」が正本で、本書は作る順序と実装の要点だけを書く。

```
cli ─▶ application ─▶ core ◀─ infrastructure
                         ▲        ▲
        plugins/kahuna/vision ─▶ toolkit
        plugins/kahuna/logic  ─▶ core
```

## 実装の方針

### 1. 縦に薄く通してから厚くする
最初に「画面を取得 → 画面の種類を判別 → 何もせずログを残す」の一巡を通す。次に対戦中の認識、ルール、思考、操作の順で足す。実機に触る前に、録画済みの画像で動く状態を保つ。

### 2. 録画画像を最大限使う
`datasets/phase0/kahuna/` の画像を、認識の開発とテストの出発点にする。自動プレイのログ（F6）が溜まったら、評価セットを増やす。

### 3. 実機での検証は小さく始める
`step` モードで数手だけ → 1ラウンド → 1ゲーム → `auto` の順に進める。各段階で止まったら、原因の画像とログを残して直す。

## コンポーネント設計

### 1. core（データモデルと Protocol）

**責務**: `docs/02` の共通モデルと `Protocol`。

**実装の要点**:
- `Recognition` の `confidence` は要素の最小値とし、閾値判定は `application` で行う
- `GameIo`、`MoveExecutor`、`ElementReader` の `Protocol` もここに置く
- 標準ライブラリ、NumPy、pydantic のみに依存する

### 2. infrastructure/adb_device.py

**責務**: Android用の `ScreenSource` と `InputDriver`。

**実装の要点**:
- 取得は `adb exec-out screencap -p`、入力は `adb shell input tap`。シリアルは設定で必須
- 座標は取得画像の座標をそのまま渡す（Phase 0 で実測。座標系は設定で持つ）
- 実行のたびにシリアルが接続中か確認する。取得は1秒前後なので、取得の失敗は `SOURCE_LOST` にする
- Phase 0 の `scripts/phase0/adb_capture.py` を移して整える

### 3. infrastructure/change_detector.py

**責務**: 操作の前後で画面が変わったかを判定する。

**実装の要点**:
- 背景の波と鳥で平均0.035〜0.07の差分が常にある（Phase 0 実測）。閾値は、環境アニメを除外する領域を指定したうえで決める
- 判定の領域はプラグインが指定する

### 4. application（runner、safety、game_io、replay、evaluation、registry）

**責務**: `docs/02` の実行ループ、安全装置、リプレイ、評価。

**実装の要点**:
- `GameIo` は実行用とリプレイ用の2実装。実行用は入力の直前に緊急停止を確認する
- `AgentRunner` は `GamePlugin` の `Protocol` にだけ依存し、`registry.py` が設定のゲーム名から動的に読み込む
- 待機（`WAITING`）は上限を設けて取り直す。上限超過は `NO_SCREEN_CHANGE`
- `step` モードは選んだ手を表示して、人の承認を待つ

### 5. toolkit（認識の共通部品）

**責務**: テンプレートマッチング、段階的な読み取り（`reader_chain`）。

**実装の要点**:
- 信頼度が閾値以上になった時点で打ち切る。VLM は最後の手段で、Phase 1 では使わない見込み
- 数字（得点、山札の枚数）はテンプレートマッチング、またはOCRを試す

### 6. plugins/kahuna/logic

**責務**: ルール（`rules.py`）と思考（`strategy.py`）。

**実装の要点**:
- 島の支配は「自分の杖コマ数 × 2 > その島の点線数」（`docs/02`）
- 決算は3回で、1回目は優位1点、2回目は2点、3回目はカフナコマ数の差。山札と場札が尽きたとき
- 手札の上限5、場札3は実測で確認し、`board.json` かルール定数に出典を添える
- 評価関数は `docs/02` の式を初期値とし、対戦結果で重みを調整する。重みは設定ファイルに持つ

### 7. plugins/kahuna/vision

**責務**: 認識（`recognizer.py`）と操作の実行（`executor.py`）。

**実装の要点**:
- 画面の種類は、固定位置のテンプレート（ボタンや見出し）で判別する
- 点線ごとの杖コマは、`board.json` の点線の位置（画像座標）の周辺を切り出して、白（自分）、茶（相手）、無しを分類する
- 手札は右の束、場札は下端の3枚。カード名は上部だけが見える場合があるので、切り出す領域は実測で決める
- 手札を選んでから照準マークをタップする手順は `executor.py` に閉じ込める。タップ後の画面で、杖コマが置かれたかを確認する
- 左の黒帯（約60px）と上部のチュートリアル案内はマスクする

## データフロー

### 1手の実行
```
1. AgentRunner が緊急停止を確認する
2. Recognizer.observe(io, previous) が画面を取得して Recognition を作る
3. PLAYABLE なら Rules.legal_moves、Strategy.choose で手を選ぶ
4. MoveExecutor.execute が手札のタップ → 照準マークのタップを送る
5. 画面変化と予測の差異を確認し、StepRecord を保存する
```

## エラーハンドリング戦略

`docs/02` の「エラーハンドリング」に従う。Phase 1 で追加するもの:
- 設定の検証エラー（シリアル未指定、閾値の範囲外）は起動前に止める
- 手札上限や場札の取り違えなど、ルールの前提が実測と違うと分かったら、テストを追加してから直す

## テスト戦略

`docs/05` の「テスト戦略」に従う。

### ユニットテスト
- `core`: データモデルの不変性、シリアライズ
- `kahuna/logic`: 合法手、支配判定、決算（期待値はルールページから手で作る）
- `toolkit`: テンプレートマッチングの合成画像
- `application`: 全 `StopReason` の経路（偽の `GameIo`）

### 統合テスト
- 録画画像を返す偽の `ScreenSource` で、認識 → 思考 → 実行の一巡
- 保存したログから `Replayer` で認識と思考を再現

### 実機テスト（`device` マーカー）
- 画面取得とtapの疎通、チュートリアルを除く対戦の開始

### 評価
- `bglm eval` で認識の正答率を計測する

## 依存ライブラリ

追加するものは `typer`、`pydantic`、`rich`、`pynput`（`docs/03` の常時利用）。VLM関連（`openai`）は Phase 1 では入れない。

## ディレクトリ構造

`docs/04` の「実装ファイル一覧」のうち、共通基盤と `plugins/kahuna/` 分を作る。`tests/` は `src/bglm/` と同じ構造で作る。

## 実装の順序

1. core（モデルと Protocol）
2. infrastructure（adb、change_detector、run_logger）と application の `GameIo`
3. 偽の `ScreenSource` で動く `AgentRunner` と `SafetyGuard`（停止条件のテスト）
4. kahuna/logic（モデル、`board.json`、ルール、思考）
5. kahuna/vision（画面の種類 → 対戦中の読み取り → 実行）
6. CLI、`Replayer`、`EvalHarness`
7. 実機の `step` → `auto`、KPIの計測

## セキュリティ考慮事項

- `adb` は常にシリアルを指定する
- ログと評価セットはGit管理外（`docs/04` の除外設定）
- ユーザーのアカウント名がスクリーンショットに写るため、学習データ化の前にマスクする（F9の範囲。Phase 1 ではGit管理しないことで足りる）

## パフォーマンス考慮事項

- 1手の所要時間は、画面取得（約1秒）+ 認識 + 思考 + 操作 + 確認の取得（約1秒）で、30秒以内に収める
- 認識は1枚の取得画像から全要素を読み、取得を繰り返さない

## 将来の拡張性

- `GameIo`、`MoveExecutor`、`Recognizer` の境界は、大戦略SSB2（Phase 2 以降）でそのまま使う。Kahuna の実装で `application` に Kahuna の知識が漏れていたら、境界を直す
