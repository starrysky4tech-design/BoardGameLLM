# 要求内容

## 概要

Monopoly の `logic/`・`runtime.py` に残った重複を共通化し(調査の B、C)、本番経路で使われていない旧系統を削除する(調査の D)。
外から見た動作(判断の結果、送る入力、状態の更新)は変えない。

## 背景

2026-11-11 の重複調査(`.steering/20261111-monopoly-refactor/` の続き)で見つかった。
画面遷移の共通化(手順 1・2)は完了済み。

- B: 同色の自分・相手の枚数の集計が 6 箇所、色グループ → 街の一覧が 6 箇所、名前 → 位置の辞書が 7 箇所、盤・ルールの定数の重複(`BOARD_SIZE` ×4、`40` の直書き、`GO_SALARY` ×2、保釈金 ×2、刑務所の 3 回 ×3)、方針内の式の重複(残す現金、鉄道・会社の係数、資産差の増分)
- C: `runtime.py` の抵当の旗の修正 ×2、現金の末尾一致補正 ×2、`LiveState` の手での再構築、関数内 import、`LogOcr` と `BoxOcr` の RapidOCR の別々の読み込み
- D: `tracker.py`、`turn.py`、`replay.py`、`hypothesis.py`、`position.py`、`trade_policy_cash.py`、`ownership.read_owner`・`plan` は、本番の経路(`runtime`、`sync`、`log_replay`、`ledger`、`state_update`)から使われず、テストだけが参照している

## 実装対象の機能

### B. logic の重複
- B1 同色の集計: `rules.group_counts`
- B2 色グループ → 街: `catalogue.street_groups` / `STREET_GROUPS`
- B3 名前 → 位置: `board.POSITION_OF`
- B4 定数: `board.BOARD_SIZE`、`board.JAIL_MAX_FAILS`、`GO_SALARY`・`BAIL_FEE` の 1 箇所化
- B5 方針内の式: 残す現金、鉄道・会社の価値の係数、資産差の増分

### C. runtime の重複
- 抵当の旗の修正、現金の末尾一致補正、`LiveState` の再構築、関数内 import の先頭への移動
- RapidOCR のエンジンの共有(`LogOcr`・`BoxOcr`)

### D. 旧系統の削除
- 上記 6 モジュールと `ownership.read_owner`・`plan`、それぞれのテスト、`docs/` の記述

## 受け入れ条件

- [ ] B1〜B5 の各重複が 1 箇所の定義になる
- [ ] C の各重複が 1 箇所の実装になり、`runtime.py` の関数内 import が、循環のあるものを除いて無くなる
- [ ] D の削除対象の `src/` 内の参照が 0(`grep` で確認)
- [ ] 模擬対戦(`scripts/monopoly/evaluate_strategy.py`)の結果が、変更前と変わらない(乱数の種が同じなら同一)
- [ ] `ruff`、`mypy`、`lint-imports`、`pytest` が、`src tests` で通る

## 成功指標

- 既存のテストが、期待値を変えずに通る(削除するモジュールのテストを除く)
- `src/bglm/plugins/monopoly/` の行数が減る

## 前提・仮定

- 乱数の種を固定した模擬対戦が、変更前後で同一の結果になれば、`logic` の判断が変わっていないとみなす — 根拠: `simulation.play_match` は種を取る
- `ownership.owner_from_image` と `synthetic_frame` は、本番の `holdings` が使う・テストが使うので残す
- 実機の確認は、状態を変えない読み取り(`read_group_houses`)に限る。`runtime.py` の変更は偽の入出力のテストで確認する

## スコープ外

- 判断の基準の変更(建設・競り・取引)
- 出目の確率表(`policies._DICE_WAYS`、`landing_odds._DICE`、`hypothesis.DICE_RANGE`)の統一 — 範囲が小さく、効果が薄い
- `sync.py` の構造の変更

## 参照ドキュメント

- `docs/02_FUNCTIONAL-DESIGN.md`、`docs/04_REPOSITORY-STRUCTURE.md`(削除するモジュールの記述を直す)
- `docs/05_DEVELOPMENT-GUIDELINES.md`
