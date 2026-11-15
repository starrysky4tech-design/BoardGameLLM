# タスクリスト

## タスク完了の原則

このファイルは作業の正式な進捗記録である。全タスクが `[x]` になるまで作業を続ける。タスクは完了した直後に 1 件ずつ `[x]` にする。
スキップしてよいのは技術的理由(方針変更で不要・別の方法に置き換わった・実行不可能)だけで、`~~取り消し線~~(理由)` を付ける。

---

## フェーズ0: 基準

- [x] Monopoly のテストの基準(通過数)を控える(666 passed)
- [x] 模擬対戦(種を固定)の基準値を取る(`--games 150 --seed 7`: 期待値 対 強欲 78/150、強欲 対 強欲 61/150、期待値 対 期待値 66/150)

## フェーズ1: B(logic の重複)

- [x] B3 `board.POSITION_OF` を作り、policies×3、funding、builder、runtime、board_scan を置き換える
- [x] B4 定数: `BOARD_SIZE`、`GO_SALARY`、`BAIL_FEE`、`JAIL_MAX_FAILS`、`40` の直書き
- [x] B2 `catalogue.street_groups` / `STREET_GROUPS` を作り、6 箇所を置き換える
- [x] B1 `rules.group_counts` を作り(テストも)、6 箇所を置き換える
- [x] B5 `_keep`、`transport_value`、`margin_gain`
- [x] Monopoly のテストと模擬対戦を、フェーズ0 と比べる

## フェーズ2: C(runtime の重複)

- [x] `_fix_mortgaged_flag`、`_ledger_cash`、`_with_cash`(`replace`)
- [x] 関数内 import を先頭へ
- [x] `vision/ocr_engine.py` を作り、`LogOcr`・`BoxOcr` から使う(テストも)
- [x] Monopoly のテストを実行する

## フェーズ3: D(旧系統の削除)

- [x] 削除対象の `src/` 内の参照が 0 であることを `grep` で確認する
- [x] 6 モジュールと `ownership.read_owner`・`plan`(と未使用の定数)、対応するテストを削除する
- [x] `docs/` の記述を直す(`docs/04` の位置・追跡の行、`docs/02` の該当箇所)
- [x] Monopoly のテストを実行する

## フェーズ4: 品質チェックと修正

- [x] ruff check、ruff format --check、mypy、lint-imports、pytest(`src tests` で。1209 passed)
- [x] 模擬対戦の結果が変更前と同一であることを確認する(B の後・全完了後の 2 回とも、勝数・平均手番数・上限決着数が一致)
- [x] 実機(SHG11)で `read_group_houses` を確かめる(状態を変えない。pink 6.4 秒、light_blue + brown 11.5 秒、問題なし)
- [x] 実装後の振り返り

---

## 実装後の振り返り

### 実装完了日
2026-11-11

### 計画と実績の差分

**計画と異なった点**:
- B3 は `POSITION_OF`(全マス)に加えて `DEED_POSITION_OF`(土地のみ)も作った。`policies` の 2 箇所と `board_scan` が土地だけの辞書を前提にしていたため(全マスの辞書にすると、`board_scan` の反復が非土地を含む)
- B2 の `reconcile` と `rules.group_members` のうち、`group_members`(街以外の同じ `group` も含む)と `reconcile` の 130 行目(同)は、意味が違うので置き換えなかった
- 刑務所の「3 回目の失敗」は、3 つの定数を別名として残した(`engine.MAX_JAIL_REST`、`jail.MAX_FAILED_ROLLS`、`landing_odds.MAX_JAIL_FAILS`)。名前を使うテストがあるため。定義は `board.JAIL_MAX_FAILS` の 1 つ
- `trade_advisor._margin` は削除し、`ExpectedValuePolicy.margin_gain` の呼び出しにした(設計どおり)
- D の `ownership.py` は、`read_owner`・`plan`・`OwnershipReading` と使われなくなった待ち秒 4 つを削除した。`ownership` が `executor`(`Driver`)に依存しなくなった

**新たに必要になったタスク**:
- なし

**技術的理由でスキップしたタスク**:
- なし

### 学んだこと

**技術的な学び**:
- 種を固定した模擬対戦は、`logic` のリファクタリングの回帰検出に使える。勝数・平均手番数・上限決着数まで一致すれば、判断が変わっていないと言える
- `runtime.py` の関数内 import は、循環のためではなく慣習だった。先頭へ移しても循環は起きなかった(`mypy`、`lint-imports`、テストが通る)
- 行数は、`src/bglm/plugins/monopoly/` の合計で、9,126 行 → 8,443 行(新設の `navigation.py`・`ocr_engine.py` を含めて、683 行減)

**プロセス上の改善点**:
- 削除前に `grep` で `src/`・`scripts/`・`scratchpad_*.py` の参照が 0 であることを確かめ、テストだけが参照していることを確認してから消せた
- 模擬対戦は、`src` を編集している間に別プロセスで走らせても、起動時に読み込まれるので影響しない(`runtime.py`・`vision` は対戦が読み込まない)

### 次回への改善提案
- 出目の確率表(`policies._DICE_WAYS`、`landing_odds._DICE`)の統一は、スコープ外にした。必要なら別作業にする
- `scripts/check.ps1` が、既存の `scratchpad_*.py`(ruff 39 件)と `build_digit_templates.py`(format)で失敗する。整えるか、対象から外す
- 実機の確認は、状態を変えない読み取りだけ。`runtime.py` の変更(抵当の旗の修正、現金の補正)は、次の自動実行で実機確認する
