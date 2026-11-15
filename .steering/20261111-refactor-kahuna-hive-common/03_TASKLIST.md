# タスクリスト

<!-- 以下「タスク完了の原則」「タスクをスキップ・変更してよい唯一のケース」は
     正本 `~/.claude/skills/steering/SKILL.md`（モード2）からの**意図的な転記**である。
     このタスクリスト単体でもルールが機能するようにするため。
     変更時は必ず正本（SKILL.md）を先に更新し、その後ここへ反映する。 -->


## タスク完了の原則

このファイルは作業の正式な進捗記録である。全タスクが `[x]` になるまで作業を続ける。

### 進捗記録の規則
- タスクは完了した直後に、1件ずつ `[x]` にする（まとめて更新すると、中断時に未実装のタスクが完了扱いで残るため）
- タスクを残してよいのは、下記「タスクスキップが許可される唯一のケース」に該当する場合だけ。「時間の都合」「複雑すぎる」「後回し」はスキップの理由にならない
- 未完了タスク（`[ ]`）が残っている状態で、作業を終了しない

### 実装可能なタスクのみを計画
- 計画段階で「実装可能なタスク」のみをリストアップ
- 「将来やるかもしれないタスク」は含めない
- 「検討中のタスク」は含めない

### タスクスキップが許可される唯一のケース
以下の技術的理由に該当する場合のみスキップ可能:
- 実装方針の変更により、機能自体が不要になった
- アーキテクチャ変更により、別の実装方法に置き換わった
- 依存関係の変更により、タスクが実行不可能になった

スキップ時は必ず理由を明記:
```markdown
- [x] ~~タスク名~~（実装方針変更により不要: 具体的な技術的理由）
```

### タスクが大きすぎる場合
- タスクを小さなサブタスクに分割
- 分割したサブタスクをこのファイルに追加
- サブタスクを1つずつ完了させる

---

## フェーズ0: 基準

- [x] テストの基準(通過数)を控える(2026-11-11: `uv run pytest` 1209 passed, 3 deselected)
- [x] 録画画像のテスト(Kahuna・Hive の `test_recorded_screens.py`)が、スキップされずに実行されていることを確かめる(`-rs` で 62 passed、スキップ 0)
- [x] 認識の出力を書き出す作業用スクリプトを `scratchpad` に作り、変更前の出力(JSON)を取る(変更前の `src` を scratchpad に複製し、`PYTHONPATH` でそれを読ませて取った。編集と並行するため)
  - [x] Kahuna: `KahunaRecognizer.recognize` の画面名・状態・信頼度・`low_confidence`(と、手札・場札・杖・石・数字・位置合わせを個別に。365 枚)
  - [x] Hive: `read_board` の `tops`・`problems`・信頼度、`find_tiles` の中心、`board_clipped`(161 枚)
  - [x] Monopoly: `classify`、`read_cash`、`scan_board`、`find_pips`(と `read_dice`、`has_use_card` など。671 枚)
- [x] 自己対戦の基準を取る(`scratchpad/selfplay_before.txt`、`monopoly_before.txt`)
  - [x] Kahuna `play_game`(種 0〜19。評価関数 対 乱数、全 20 局で先手勝ち、手番数 63〜73)
  - [x] Hive `play_game`(種 0〜4、深さ 2。lose/None/lose/lose/lose、手番 160/200/29/67/54)
  - [x] Monopoly `evaluate_strategy --games 150 --seed 7`(78/150、61/150、66/150。前回の記録と同じ)
- [x] 行数の基準を控える(`Measure-Object -Line`: `src/bglm/` 11,852、`kahuna` 1,839、`hive` 1,211、`monopoly` 7,130、`toolkit` 45)

## フェーズ1: 共通部品(`toolkit/`)

- [x] `toolkit/images.py`(`Box`、`load_image`、`gray`、`crop`)と `test_images.py`
- [x] `toolkit/matching.py`(`Match`、`correlation`、`best_match`、`match_score`、`find_peaks`)と `test_matching.py`
- [x] `toolkit/template_reader.py` を `match_score` に置き換える(既存の `test_template_reader.py` が通る)
- [x] `toolkit/waiting.py`(`poll`)と `test_waiting.py`
- [x] `toolkit/screen.py`(`LANDSCAPE_SIZE`、`has_size`)と `test_screen.py`
- [x] `toolkit/components.py`(`Component`、`connected_components`、`component_mask`)と `test_components.py`
- [x] `tests/common` を実行し、ruff・mypy・lint-imports を `src/bglm/toolkit` に対して通す

## フェーズ2: Kahuna

- [x] `templates.py`: `_read` → `images.load_image`
- [x] `alignment.py`、`cards.py`、`stones.py`: 照合 → `matching`(`stones._peaks` と `read_hand` の内側のループ → `find_peaks`)
- [x] `glyphs.py`、`sticks.py`: 連結成分 → `components`。`glyphs.red_mask` を作り、`screens._banner_present` と `numbers.read_deck` から使う
- [x] `numbers.py`: `_crop` → `images.crop`
- [x] `screens.py` / `recognizer.py`: 領域を `(x0, y0, x1, y1)` に揃える。`HAND_ROI` を `cards` の 1 つに。`dialog_scores` で照合を 1 つに。`IMAGE_SIZE` → `screen.LANDSCAPE_SIZE`
- [x] `recognizer.observe` の取り直し → `waiting.poll`
- [x] `executor.py`: `_my_turn_view`、`_has_stick`、`_best_card`、`_wait_until` → `waiting.poll`
- [x] Kahuna のテストを実行する(期待値を変えずに通る。`tests/plugins/kahuna` + `tests/common` で 557 passed)
- [x] 認識の出力を、フェーズ0 と比べる(365 枚、差 0)

## フェーズ3: Hive

- [x] `wide.py`: `board_clipped`・`empty_wood_start` を `recognizer.py` から移す。`pan_content`・`wide_read` に `sleep` を足す。`measured_offset` の参照が無いことを確かめて削除する
- [x] `wide.py`: `WideBoardRecognizer`(`__init__.py` の `HiveDebugRecognizer` を移す)。`plugins/hive/__init__.py` を組み立てと公開だけにする
- [x] `grid.py`: `_seed_centres`、`_lattice_spacing`。連結成分 → `components`(重心は最初から従来の「画素の座標の平均」を保った)
- [x] `recognizer.py`: `tops_of` を公開。`_hidden_ground` の連結成分 → `components`
- [x] `executor.py`: `_geometry` で `tops_of` を使う。`_verified` → `waiting.poll`。`wide_read`・`pan_content` に `sleep` を渡す
- [x] テスト・スクリプトの import を直す(`test_pan.py` の `board_clipped` の場所だけ。期待値は変えない)
- [x] Hive のテストを実行する(期待値を変えずに 47 passed)
- [x] 認識の出力を、フェーズ0 と比べる(161 枚、差 0)

## フェーズ4: Monopoly(置き換えだけ)

- [x] `screens.py`: `_template` → `images.load_image`、`_score` → `matching.match_score`、大きさの確認 → `screen.has_size`
- [x] `cash.py`: `_load` → `images.load_image`、`_components` → `components`
- [x] `bars.py`(3 箇所)、`dice.py`、`board_scan.py`: 連結成分 → `components`
- [x] `navigation.wait_for`、`executor._jail_confirm` → `waiting.poll`(確認を待つ回数 4 を `JAIL_CONFIRM_TRIES` に名前付け)
- [x] Monopoly のテストを実行する(期待値を変えずに 633 passed)
- [x] 認識の出力を、フェーズ0 と比べる(671 枚、差 0)

## フェーズ5: スクリプト

- [x] `scripts/common/step_once.py`(`StepHooks`、`--game`、`--execute`、`--from-start`)
- [x] `scripts/kahuna/step_hooks.py`、`scripts/hive/step_hooks.py`
- [x] `scripts/kahuna/step_once.py`、`scripts/hive/step_once.py`、`scripts/kahuna/record_session.py` を削除する(参照は過去の `.steering` の記録だけ)
- [x] `uv run python -m scripts.common.step_once --help` が動く(実機には接続しない。`load_hooks` は kahuna・hive の差し込みを読み、monopoly は既定)

## フェーズ6: 品質チェックと修正

- [x] 受け入れ条件の `grep` を確かめる
  - [x] `src/bglm/plugins/` に `cv2.matchTemplate`・`cv2.imread`・`cv2.imdecode`・`connectedComponentsWithStats` の直接の呼び出しが無い(残りは `toolkit` と `infrastructure` だけ)
  - [x] `IMAGE_SIZE = (2432, 1080)` の定義が無い(`LANDSCAPE_SIZE` の 1 つ)
  - [x] `plugins/hive/` に `time.sleep(` の直接の呼び出しと、他モジュールの `_` 始まりの import が無い
- [x] すべてのテストが通ることを確認
  - [x] `uv run pytest`(1237 passed = 変更前 1209 + 新設 28。3 deselected は実機テスト)
  - [x] `uv run pytest tests/common --cov=bglm.toolkit --cov-branch`(toolkit 全体で分岐 99%。新設 5 モジュールは 100%)
- [x] リントエラーがないことを確認
  - [x] `uv run ruff check src tests scripts`
  - [x] `uv run ruff format --check src tests scripts`
- [x] 型エラーがないことを確認
  - [x] `uv run mypy`(137 ファイル、問題なし)
- [x] 依存方向を確認
  - [x] `uv run lint-imports`(6 kept)
- [x] 自己対戦の結果が、フェーズ0 と一致する(Kahuna 20 局、Hive 5 局、Monopoly 150 局×3。出力が一字一句一致)
- [x] 行数を、フェーズ0 と比べる(`src/bglm/` 11,852 → 12,004(+152)。`toolkit` +153、`kahuna` −10、`hive` ±0、`monopoly` +9。振り返りに記録)

## フェーズ7: ドキュメント更新

- [x] `docs/04_REPOSITORY-STRUCTURE.md` の実装ファイル一覧を更新する(toolkit の 5 行、Hive の行の「未作成」の修正と `wide.py`・`stitch.py`、`scripts/` の `step_once`・`step_hooks`、配置規則に共通部品の行)
- [x] `docs/02`・`docs/03`・`README.md` に、移した名前(`step_once`、`HiveDebugRecognizer`、`board_clipped` など)への参照があれば直す(参照なし)
- [x] 実装後の振り返り(このファイルの下部に記録)

---

## 実装後の振り返り

### 実装完了日
2026-11-11

### 計画と実績の差分

**計画と異なった点**:
- **成功指標「`src/bglm/` の合計が増えない」は満たせなかった**(11,852 → 12,004、+152 行)。増えたのは新設の `toolkit` 5 モジュール(+153。docstring と `Component`・`Match` のデータクラス)で、プラグイン側は `kahuna` −10、`hive` ±0、`monopoly` +9(`poll` の呼び出しがキーワード引数で複数行になるため)。重複は「同じ処理を書いた箇所の数」では減った(`cv2.matchTemplate` の呼び出し 8 → 1、連結成分 12 → 1、画像の読み込み 3 → 1、取り直しのループ 5 → 1、画面の大きさ 2 → 1、step_once 2 → 1)が、行数では減っていない
- Hive の重心は、設計では OpenCV の重心(`Component.cx`)に寄せて差が出たら戻す予定だったが、最初から従来の「画素の座標の平均」を保った(比べる前に丸めの差の危険を避けた)。Monopoly の `dice` は元から OpenCV の重心なので `Component.cx` を使った
- `screens.best_dialog` は `dialog_scores`(名前 → 相関の辞書)という名前にした。勝者の表示の照合は「最良」を選ばず閾値で判定するため
- Kahuna の `recognizer.observe` は、`retries` が負のとき従来は 1 回だけ読んでいた。`poll` は `tries < 1` を拒むので、`max(0, retries) + 1` で従来の動作を保った
- Monopoly の `_jail_confirm` の回数 4 は、直書きだったものを `JAIL_CONFIRM_TRIES` に名前付けした(値は同じ)
- 変更前の認識の出力は、作業の途中で 1 回失敗した(`datasets/raw/hive` に空のファイルがあり、OpenCV が例外を出した)。取り直しでは、変更前の `src` を scratchpad に複製し、`PYTHONPATH` でそれを読ませて取った。これで、基準を取っている間も本体を編集できた
- テストの件数: 新設は 28 件(作業中に「34 件」と書いた数は、既存の `test_template_reader.py` の 6 件を含んでいた)。全体は 1209 + 28 = 1237

**新たに必要になったタスク**:
- なし

**技術的理由でスキップしたタスク**:
- なし

### 学んだこと

**技術的な学び**:
- 認識のリファクタリングの回帰は、手元の全画像(1,197 枚)に対する出力の `repr` を前後で比べると、テストより広く確かめられる(テストは数十枚、比較は手札・場札・杖・石・数字・マスの中心の小数まで)
- 待ちのループは、待つ位置(各回の前・回の間・最後の後)がそれぞれ違っていた。2 つの旗(`wait_first`、`wait_last`)で全部を再現でき、`sleep` の回数と順序をテストで固定できた
- Hive の `pan_content` に `sleep` を注入したことで、操作のテストが実時間(1 回 1.5 秒 × 寄せる回数)を待たなくなった

**プロセス上の改善点**:
- 基準(テスト件数・認識の出力・自己対戦・行数)を最初に全部取ったので、ゲームごとに「差 0」を確かめてから次へ進めた
- 自己対戦は `logic` だけを読み込むので、`vision` の編集と並行して走らせても影響しない

### 次回への改善提案
- **実機での確認が未了**。次に各ゲームを動かすときの最初に、表示のみで 1 回ずつ確かめる: `uv run python -m scripts.common.step_once --game kahuna`、`--game hive --from-start`(`--execute` を付けない)。Monopoly は `runtime` の通常の再開の最初の数手で、画面の判別・所持金・ダイスの読み取りを見る
- 行数を減らすのが目的なら、次の候補は Monopoly の `_tap_until`・`confirm`・`roll`・`close_card` の「押す → 待つ → 確かめる」の型(回ごとにログを足すので、今回の `poll` では置き換えなかった)
- `datasets/raw/hive/` に 0 バイトの PNG がある。素材の整理のときに消すか、作った手順を確かめる
- `scripts/check.ps1` は、既知の `scratchpad_*.py` の ruff の指摘で止まる(前回の申し送り)。今回の検証は `src tests scripts` を指定して個別に実行した
