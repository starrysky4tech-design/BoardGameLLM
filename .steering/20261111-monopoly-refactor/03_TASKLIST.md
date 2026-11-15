# タスクリスト

<!-- 以下「タスク完了の原則」「タスクをスキップ・変更してよい唯一のケース」は
     正本 `~/.claude/skills/steering/SKILL.md`(モード2)からの**意図的な転記**である。
     このタスクリスト単体でもルールが機能するようにするため。
     変更時は必ず正本(SKILL.md)を先に更新し、その後ここへ反映する。 -->

## タスク完了の原則

このファイルは作業の正式な進捗記録である。全タスクが `[x]` になるまで作業を続ける。

### 進捗記録の規則
- タスクは完了した直後に、1件ずつ `[x]` にする(まとめて更新すると、中断時に未実装のタスクが完了扱いで残るため)
- タスクを残してよいのは、下記「タスクスキップが許可される唯一のケース」に該当する場合だけ。「時間の都合」「複雑すぎる」「後回し」はスキップの理由にならない
- 未完了タスク(`[ ]`)が残っている状態で、作業を終了しない

### タスクスキップが許可される唯一のケース
以下の技術的理由に該当する場合のみスキップ可能:
- 実装方針の変更により、機能自体が不要になった
- アーキテクチャ変更により、別の実装方法に置き換わった
- 依存関係の変更により、タスクが実行不可能になった

スキップ時は必ず理由を明記:
```markdown
- [x] ~~タスク名~~(実装方針変更により不要: 具体的な技術的理由)
```

### タスクが大きすぎる場合
- タスクを小さなサブタスクに分割し、このファイルに追加して、1つずつ完了させる

---

## フェーズ0: 変更前の基準

- [x] Monopoly のテストを実行し、変更前の結果(通過・スキップの数)を控える(656 passed、スキップ 0、61 秒)

## フェーズ1: 画面遷移の共通部品(手順 1)

- [x] 定数と小さな関数の置き場所
  - [x] `screens.BOARD_SCREENS` を足し、holdings・ownership・property_manager・builder・runtime の定義と直書きを置き換える
  - [x] `executor.fail`、`executor.confirm` を公開の名前にし、builder・property_manager の `_fail` と `ex._confirm` を置き換える
  - [x] `navigation.py` を作り、`NOTICE_OK`、`IMPROVEMENT_TILE_Y`、`OPEN_SEC`、`HELP_SEC`、`RETURN_SEC` を置く。5 箇所の `Point(1254, 811)` と、重複した待ち秒・y を置き換える
  - [x] 詳細画面の Return の座標を `ownership.py` の 1 組にする(自分の土地の Return は 2 値 (1006,929) と (1022,933) があり、抵当の実機操作で使っている (1022,933) に揃えた)(holdings の `DETAIL_RETURN`、property_manager の `DETAIL_RETURN_MINE`)。`holdings.py` の `1.22` の直書きを `bars.DISPLAY_TO_FRAME` にする
- [x] 盤へ戻る
  - [x] `navigation.capture`、`wait_for`、`return_to_board` を実装する
  - [x] `test_navigation.py` に `return_to_board` のテストを書く
  - [x] builder `_return_to_board`、holdings `_return_to_board` と `_return_board`、property_manager `_to_board` を置き換えて削除する
  - [x] `runtime._return_from_zoom` を `return_to_board` の呼び出しにする(`_return_from_improvements` は、確認ダイアログで止める役割なので残し、定数だけ揃える)
- [x] 色グループを開く
  - [x] `navigation.open_group` を実装する
  - [x] `test_navigation.py` に `open_group` のテストを書く
  - [x] builder `build_group`、property_manager `_open_detail` と `sell_houses`、holdings `read_all_holdings` と `read_group_houses` を置き換える
- [x] Monopoly のテストを実行し、フェーズ0 と比べる(656 passed。`test_navigation.py` の 10 件は別)

## フェーズ2: 操作の共通化(手順 2)

- [x] `builder._change_houses` を作り、`build_group` と `property_manager.sell_houses` から呼ぶ
- [x] `executor._jail_confirm` を作り、`pay_bail`、`pay_bail_top`、`use_jail_card` から呼ぶ
- [x] Monopoly のテストを実行し、フェーズ0 と比べる(656 passed。`test_navigation.py` の 10 件は別)

## フェーズ3: 品質チェックと修正

- [x] `.\scripts\check.ps1` 相当(ruff check、ruff format --check、mypy、lint-imports、pytest)が通ることを確認(1242 passed。`check.ps1` そのものは、既存の `scratchpad_*.py` の ruff エラー 39 件と `scripts/monopoly/build_digit_templates.py` の format で失敗する。今回の変更とは無関係なので、`src tests` に絞って確認した)
- [x] 実機(SHG11)で、状態を変えない操作を確かめる(2026-11-11。対局は 3 局目を Resume して盤に戻した)
  - [x] 画面を取得して判別する(盤の自分の手番であること): `board_my_turn_end`。メインメニューのときは、入力を送らず止まることも確認
  - [x] `read_group_houses` で色グループを開いて戻り、盤に戻ったこと、読んだ家の数を確かめる(pink 6.3 秒、light_blue + brown 11.2 秒、問題なし、戻った後も `board_my_turn_end`)

## フェーズ4: ドキュメント更新

- [x] `docs/04_REPOSITORY-STRUCTURE.md` の実装ファイルの一覧に `navigation.py` を足す
- [x] 実装後の振り返り(このファイルの下部に記録)

---

## 実装後の振り返り

### 実装完了日
2026-11-11

### 計画と実績の差分

**計画と異なった点**:
- `property_manager._to_board` は削除せず、`navigation.return_to_board(wait_sec=STEP_SEC, close_trade=True)` を呼ぶ薄い包みとして残した(抵当・売却の方針を 1 箇所に持たせるため)
- 自分の土地の詳細画面の Return の座標が、ownership `(1006, 929)` と holdings・property_manager `(1022, 933)` で食い違っていた。抵当の実機操作で使っている `(1022, 933)` に統一した(同じボタン内の 16 px 差)
- `open_group` に `want` 引数を足した。建設は、拡大盤が開いたとき案内を消すタップを送らない(拡大盤の上の別の場所を押しかねない)ため

**新たに必要になったタスク**:
- なし

**技術的理由でスキップしたタスク**:
- なし

### 学んだこと

**技術的な学び**:
- 6 つの「盤へ戻る」は、試行回数・通知の扱い・取引画面の扱い・色の確認が、それぞれ違った。差を引数(`check_color`、`close_trade`)として明示すると、どの経路が何をするかが読める
- 画面の取得は 1 回約 2 秒かかる。`open_group` が案内を消した後の画像を返すので、読み取りで取り直さずに済む(`read_all_holdings` は取得が減った)
- `scripts/check.ps1` は、既存の `scratchpad_*.py`(ruff 39 件)と `scripts/monopoly/build_digit_templates.py`(format)で失敗する。今回の変更とは無関係

**プロセス上の改善点**:
- 実機が `unauthorized` / メインメニューのとき、実機検証を後回しにして、偽の入出力のテストとドキュメントを先に終えられた
- メインメニューの PLAY NOW は、ラベルではなくアイコン(原寸 337,183)を押す。ラベル(原寸 336,270)では反応しなかった

### 次回への改善提案
- 偽の入出力のテストは、実機の画面の見本が Git 管理外で、環境によっては飛ばされる。画像が無い環境でも走る、合成画像のテストを検討する
- `scratchpad_*.py` と `build_digit_templates.py` を、`check.ps1` が通るよう整える(別作業)
- 調査の B(logic の重複)、C(runtime の重複)、D(旧系統の削除)は未着手
