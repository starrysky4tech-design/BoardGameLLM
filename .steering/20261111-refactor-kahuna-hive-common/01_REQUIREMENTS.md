# 要求内容

## 概要

Kahuna と Hive の自動実行ロジック(`plugins/kahuna/`、`plugins/hive/`)をリファクタリングする。
あわせて、Kahuna・Hive・Monopoly の 3 つで同じことをしているコードを共通部品(`toolkit/`、`scripts/common/`)へ移し、重複を無くす。
外から見た動作(認識の結果、選ぶ手、送る入力の並び、止める条件)は変えない。

## 背景

Monopoly は 2026-11-11 に 2 回のリファクタリング(`.steering/20261111-monopoly-refactor`、`-refactor-logic`)を終えたが、
対象は Monopoly の中だけだった。Kahuna と Hive は作ったときのままで、次の重複がある(2026-11-11 の調査)。

### A. ゲームをまたぐ重複(共通化の対象)

| # | 内容 | 現在の場所 |
|---|---|---|
| A1 | テンプレートとの正規化相関の最大値を取る(`cv2.matchTemplate(...).max()`) | kahuna: `screens._dialog_button`、`recognizer._game_over`、`cards.read_market`、`alignment.find_alignment`、`stones` / monopoly: `screens._score` / toolkit: `TemplateReader` |
| A2 | 相関の山を、周囲を消しながら順に拾う | kahuna: `stones._peaks`、`cards.read_hand` の内側のループ |
| A3 | テンプレート画像の読み込み(読めなければエラー) | kahuna: `templates._read`(`imdecode`) / monopoly: `screens._template`、`cash._load`(`imread`。日本語のパスで読めない) |
| A4 | 条件が成り立つまで、待って取り直す | kahuna: `executor._wait_until`、`recognizer.observe` / hive: `executor._verified` / monopoly: `navigation.wait_for`、`executor._jail_confirm` |
| A5 | 取得画像の大きさ(2432x1080)の定数と確認 | kahuna: `screens.IMAGE_SIZE` / monopoly: `screens.IMAGE_SIZE`(確認が 5 箇所) |
| A6 | 連結成分を、外接する箱の一覧にする(面積や大きさで絞る) | kahuna: `glyphs`、`sticks` / hive: `grid`(3 箇所)、`recognizer` / monopoly: `cash`、`bars`(3 箇所)、`dice`、`board_scan` |
| A7 | 実機で 1 手だけ「認識 → 思考 → 操作」を行うスクリプト | `scripts/kahuna/step_once.py`、`scripts/hive/step_once.py` |

### B. Kahuna の中の重複・整理

- `executor.py`: 6 つの操作の冒頭が同じ(取得 → 位置合わせ → 自分の手番かの確認)。`_has_own_stick` と `_has_opponent_stick` は持ち主だけが違う。手札のカードを選ぶ処理が 2 通りある
- ダイアログの文字の照合が `screens.py` と `recognizer.py` に別々にある
- 領域の座標の並びが、ファイルごとに `(y0, y1, x0, x1)` と `(x0, y0, x1, y1)` で混ざっている

### C. Hive の中の重複・整理

- `wide.py` が `recognizer.py` の非公開関数 `_empty_wood_start` を import している。`board_clipped` と合わせて、置き場所が役割と合っていない
- `wide.pan_content` が `time.sleep` を直接呼ぶ(`docs/05`「待機は差し替えられる形にする」に反する。テストが実時間を待つ)
- `grid.py`: `_white_centres` と `_fallback_tiles` が同じ連結成分の処理を持つ。`_fit_spacing` と `to_axial` が同じ最小二乗を持つ
- 「盤の一番上の駒の辞書を作り、最小の q・r で平行移動して比べる」が `recognizer.py` と `executor.py` にある
- `HiveDebugRecognizer`(盤が広いときの読み分け)が `plugins/hive/__init__.py` にある。`docs/04` では `__init__.py` は `GamePlugin` の公開だけ

## 実装対象の機能

### 1. 共通部品の新設(`toolkit/`)

- A1・A2: `toolkit/matching.py`(相関の最大値と位置、山の列挙)
- A3: `toolkit/images.py`(画像の読み込み。日本語のパスでも読める `imdecode` に揃える)
- A4: `toolkit/waiting.py`(条件が成り立つまで取り直す。回数・間隔・`sleep` を引数で受ける)
- A5: `toolkit/screen.py`(端末 SHG11 の取得画像の大きさと、その確認)
- A6: `toolkit/components.py`(連結成分 → 箱・面積・重心の一覧)
- それぞれにユニットテストを足す(`tests/common/unit/toolkit/`。合成画像を使う)

### 2. Kahuna のリファクタリング

- 共通部品(A1〜A6)へ置き換える
- B の重複をまとめる(操作の冒頭、杖コマの確認、カードの選択、ダイアログの照合)

### 3. Hive のリファクタリング

- 共通部品(A4、A6)へ置き換える
- C の重複と置き場所を直す(寄せる操作の補助を `wide.py` へ、広い盤の読み分けを `vision/` へ、`sleep` の注入、`grid.py` の重複)

### 4. Monopoly の置き換え

- 共通部品(A1、A3、A4、A5、A6)と同じ処理をしている箇所だけ、呼び出しに置き換える。判断・座標・待ち秒・手順は変えない

### 5. スクリプトの共通化

- A7: `scripts/common/step_once.py --game <kahuna|hive>` に 1 本化する。Kahuna 固有の「引く操作が残っている印」は、ゲームごとの小さな差し込みとして残す

### 6. ドキュメントの更新

- `docs/04` の実装ファイル一覧(toolkit の新設、Hive の「未作成」の記述の修正、スクリプト)

## 受け入れ条件

### 共通部品
- [ ] `src/bglm/plugins/` の中に `cv2.matchTemplate` の直接の呼び出しが残らない(`toolkit/matching.py` 経由になる)
- [ ] `src/bglm/plugins/` の中に `cv2.imread`・`cv2.imdecode` の直接の呼び出しが残らない
- [ ] `IMAGE_SIZE = (2432, 1080)` の定義が 1 箇所になる
- [ ] 「条件が成り立つまで取り直す」ループが、Kahuna・Hive では `toolkit/waiting.py` の 1 つになる
- [ ] 新設した toolkit のモジュールごとにユニットテストがあり、`toolkit` の分岐カバレッジ 80% を満たす

### Kahuna
- [ ] `executor.py` の「取得 → 位置合わせ → 手番の確認」が 1 つの内部関数になる
- [ ] 録画画像のテスト(`tests/plugins/kahuna/unit/vision/test_recorded_screens.py`)と統合テストが、期待値を変えずに通る
- [ ] 自己対戦(種を固定)の結果が、変更前と一致する

### Hive
- [ ] `vision/` の中に、他のモジュールの非公開関数(`_` 始まり)の import が残らない
- [ ] `vision/` の中に `time.sleep` の直接の呼び出しが残らない(引数で受ける)
- [ ] `plugins/hive/__init__.py` が、プラグインの組み立てと公開だけになる
- [ ] 既存のテストが、期待値を変えずに通る。自己対戦(種を固定)の結果が、変更前と一致する

### Monopoly
- [ ] 既存のテスト(変更前 1209 passed のうち Monopoly 分)が、期待値を変えずに通る
- [ ] 模擬対戦(`--games 150 --seed 7`)の結果が、変更前と一致する(`logic` を触らないことの確認)

### 全体
- [ ] `ruff check`・`ruff format --check`・`mypy`・`lint-imports`・`pytest` が、`src tests scripts` に対して通る(テストは 1209 件以上)
- [ ] `scripts/kahuna/step_once.py` と `scripts/hive/step_once.py` が無くなり、`scripts/common/step_once.py` に置き換わる

## 成功指標

- `plugins/kahuna/` と `plugins/hive/` の行数が減る(共通部品へ移した分を含めても、`src/bglm/` の合計が増えない)
- 既存のテストの期待値を 1 つも緩めない

## 前提・仮定

- **Monopoly のコードも変更する**(共通部品への置き換えに限る) — 根拠: 依頼の「3 つで共通的に使えるロジックは共通化して、重複を無くす」。Monopoly 側に同じ処理を残すと重複が残る
- **実機の確認は行わない**。検証は、録画画像のテスト・偽の入出力のテスト・自己対戦で行う — 根拠: 実機の USB が切れて保留中(`07_HANDOFF_20261110.md`)、Monopoly の 3 局目は Save & Exit で中断中。実機での確認は、次に各ゲームを動かすときの最初の 1 手(`step_once` の表示のみ)で行う、と振り返りに申し送る
- **`logic/` の共通化はしない** — 根拠: 3 つの思考は方式が違う(Kahuna は 1 手の評価、Hive はアルファベータ、Monopoly は期待値の方針)。共通なのは重みの TOML を読む数行と `WIN_SCORE` の定数だけで、`logic` は `toolkit` を import できない(`docs/04`)。共通の置き場所(新しいレイヤー)を作るほどの量が無い
- **共通部品の置き場所は `toolkit/`** — 根拠: `docs/04`「複数のプラグインが使う認識の部品」。`toolkit` は `core` だけに依存するので、`GameIo` を受け取る待ちの部品も置ける
- **Monopoly の `Driver`(入出力 + `sleep` + ログ)は共通化しない** — 根拠: 画面名の判別(Monopoly の `classify`)と結び付いており、Kahuna・Hive の実行は `GamePlugin`(`MoveExecutor`)の形で、構造が違う。無理に揃えると Monopoly の手順を変えることになる
- ステアリングの月次アーカイブ(10 月分の連結)は、今回は行わない — 根拠: プロジェクトの `CLAUDE.md` が `.steering/20261030-phase0-feasibility/RESULT.md` と `.steering/20261030-phase1-kahuna/` を直接参照しており、連結すると参照が切れる

## スコープ外

以下はこのフェーズでは実装しません:

- 認識の精度・思考の強さ・待ち秒の変更(動作を変えるもの)
- Monopoly を `GamePlugin` の形にすること(`.steering/20261104-monopoly-autoplay-handoff` の課題)
- Hive の未確認の操作(Pass)の実装、`debug_overlay` の重ね描き
- `logic/` の共通レイヤーの新設
- `scripts/<game>/` のうち、ゲーム固有の素材作り(テンプレート作成、評価セット、キャリブレーション)

## 参照ドキュメント

- `docs/02_FUNCTIONAL-DESIGN.md` - 機能設計書(コンポーネントの責務)
- `docs/04_REPOSITORY-STRUCTURE.md` - リポジトリ構造定義書(依存ルール、実装ファイル一覧)
- `docs/05_DEVELOPMENT-GUIDELINES.md` - 開発ガイドライン(乱数と時刻、テスト戦略)
- `.steering/20261111-monopoly-refactor/`、`.steering/20261111-monopoly-refactor-logic/` - Monopoly の先行リファクタリング(進め方と検証の型)
