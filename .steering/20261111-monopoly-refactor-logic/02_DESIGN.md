# 設計書

## アーキテクチャ概要

レイヤーと依存の向きは変えない。共通化した定義は、依存の少ない側(`board`、`catalogue`、`rules`)へ置く。

```
board.py      : BOARD_SIZE、POSITION_OF、JAIL_MAX_FAILS、JAIL_FINE
catalogue.py  : street_groups(catalogue)、STREET_GROUPS
rules.py      : group_counts(state, catalogue, player, deed) -> (mine, theirs)
policies.py   : ExpectedValuePolicy.margin_gain、_keep、transport_value
vision/ocr_engine.py : 共有の RapidOCR(LogOcr・BoxOcr が使う)
```

## コンポーネント設計

### B1 `rules.group_counts`
同色の街のうち、`player` が持つ数と、相手が持つ数(`state.holdings` に所有者つきで載っているもの)を返す。
`deed_value`、`portfolio_value`、`_completes_group`、`_cheaper_by_auction`、`propose_trades`、`owns_full_group` が使う。

### B2 `catalogue.street_groups`
色グループ → 街(`Deed`)のリスト。`catalogue` 引数で作る関数と、既定の `STREET_GROUPS` を持つ。
`group_return_factor`、`_best_build`、`board_scan._street_groups`、`holdings._street_members`、`reconcile` が使う。

### B3 `board.POSITION_OF`
`{sq.name: sq.position for sq in BOARD}`。名前が複数ある(Chance など)ものは、最後の位置が入る(現状と同じ)。

### B4 定数
- `board.BOARD_SIZE = len(BOARD)` を、`landing_odds`、`log_replay`、`position`(削除予定)、`tracker`(削除予定)から参照する
- `GO_SALARY` は `models.py` の 1 つ。`ledger.py` は import する
- `ledger.BAIL_FEE = board.JAIL_FINE`(名前は残す。`jail`、`runtime` が使う)
- 刑務所の「3 回目の失敗で保釈金」は `board.JAIL_MAX_FAILS = 3`。`engine.MAX_JAIL_REST`、`jail.MAX_FAILED_ROLLS`、`landing_odds.MAX_JAIL_FAILS` は、この値の別名として残す(名前を使うテストがあるため)
- `engine.py`、`policies.py` の `40` の直書きは `BOARD_SIZE`

### B5 方針内の式
- 残す現金: `_keep(game, player, strategic)`。`wants_to_buy` と `auction_keep` が使う
- 鉄道・会社の価値: `transport_value(kind, price, owned_before)`。`deed_value` と `portfolio_value`
- 資産差の増分: `ExpectedValuePolicy.margin_gain(state, after, catalogue, player)`。`trade_advisor._margin` は、これを呼ぶ

### C runtime
- `_fix_mortgaged_flag(agent, name)`: 画面が「すでに抵当済み」を示したとき、記録の旗を直す
- `_ledger_cash(read, ledger)`: 読みの末尾が台帳の値と一致し、桁が 1 つ多いとき、台帳の値を返す(₼ が数字に化ける)
- `_with_cash` は `dataclasses.replace`
- 関数内 import は先頭へ(循環が無いことを確かめる)
- `vision/ocr_engine.py`: `get_engine()`(`functools.cache`)と `recognize(image, box, scale)`。`LogOcr`・`BoxOcr` が使う

### D 削除
`logic/tracker.py`、`turn.py`、`replay.py`、`hypothesis.py`、`position.py`、`trade_policy_cash.py`、
`vision/ownership.py` の `plan`・`read_owner`・`SETTLE_SEC`・`DETAIL_SEC`・`CLOSE_SEC`(使われなくなる定数)、対応するテスト、`docs/` の記述。

## エラーハンドリング戦略

変えない。

## テスト戦略

- 新しい関数(`group_counts`、`street_groups`、`transport_value`、`margin_gain`、`recognize` の共有)に単体テスト
- 既存のテストが、期待値を変えずに通る
- 模擬対戦(種を固定、300 局)の勝率が、変更前後で同一

## ディレクトリ構造

```
src/bglm/plugins/monopoly/
├── logic/{board,catalogue,rules,policies,funding,jail,engine,ledger,landing_odds,log_replay,reconcile,trade_advisor}.py  # 変更
├── logic/{tracker,turn,replay,hypothesis,position,trade_policy_cash}.py                                               # 削除
├── runtime.py                       # 変更
└── vision/{ocr_engine.py(新設),log_reader,dialog_reader,board_scan,holdings,builder,ownership}.py
```

## 実装の順序

0. 模擬対戦の基準値を取る(種を固定)
1. B: B3、B4 → B2 → B1 → B5(機械的なものから)。各段階でテスト
2. C: runtime の helper、OCR の共有
3. D: 参照の確認 → 削除 → docs
4. 検証(ruff、mypy、lint-imports、pytest、模擬対戦、実機)

## セキュリティ・パフォーマンス

- OCR のエンジンを 1 つにすると、起動時間とメモリが減る(推測。未計測)
