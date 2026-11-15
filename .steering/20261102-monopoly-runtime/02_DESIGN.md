# 設計書

## アーキテクチャ概要

Kahuna のプラグインと同じ構成にする。`logic` は画面に依存せず、`vision` が画面を読んで操作する。共通基盤の `GamePlugin` に合わせるため、Monopoly 固有の接続層を置く。

```
plugins/monopoly/
├── __init__.py            (新規) MonopolyPlugin / create_plugin()
├── logic/
│   ├── events.py          (計画 2) 出来事の型
│   ├── moves.py           (新規) 手の型
│   ├── tracker.py         (新規) 出来事 + 所持金 → 状態。整合検査
│   ├── adapter.py         (新規) MonopolyRules / MonopolyStrategy(Policy と手の対応)
│   └── (既存: engine, rules, policies, ...)
├── vision/
│   ├── screens.py         (既存)
│   ├── cash.py            (計画 1)
│   ├── dice.py, log_reader.py (計画 2)
│   ├── recognizer.py      (新規) 画面 + 読み取り → Recognition
│   ├── executor.py        (新規) 手 → タップ列、成否の確認
│   └── describe.py        (新規) 認識結果の分解(評価用)
config/monopoly.toml        (新規)
src/bglm/core/models.py     (変更) HoldDrag を追加
src/bglm/infrastructure/adb_device.py (変更) HoldDrag の実行
```

## コンポーネント設計

### 1. `HoldDrag`(共通基盤)
- `HoldDrag(start, end, hold_ms, steps, step_ms)`。実機で確かめた手順: 押下 → 0.6 秒保持 → 6 段階で上へ移動 → 離す(`RESULT.md`「ロールは『タッチ → 保持 → 上へ移動』」)
- `AdbDevice.perform` は、`input motionevent DOWN/MOVE/UP` を、1 回の `adb shell` 呼び出しにまとめて送る。保持の時間を adb の呼び出し間の遅れに左右させないため
- 端末のスクリプト `/data/local/tmp/flick_hold.sh` には依存しない
- 既存の `Tap` / `Drag` は変えない

### 2. 状態と整合検査(`logic/tracker.py`)
- 状態: 位置、所持金(自分・AI)、所有(土地ごとの所有者、家数、抵当)、刑務所の状態、手番、未確定の理由
- 更新の入力: 出来事(計画 2)、所持金の読み取り(計画 1)、自分の操作の結果(購入を確定した、など)
- **所有は、観測した購入・落札・取引の出来事からだけ更新する。** 推測や画面の見た目での上書きはしない(第 77〜95 手番の取り違えの再発防止)
- 所持金の予測: 前の所持金 + 出来事の影響(購入の額、賃料、税、カード、GO 通過 +200)。読み取った所持金が予測と違えば:
  1. 間隔を置いて再読み取り(表示の遅れの可能性)
  2. それでも違えば `Unresolved(reason)` にし、判断(購入・入札・建設)を止める。次の出来事で整合したら解消する
- 賃料の額は、`logic.rules` の計算(同色セットの 2 倍、家数、鉄道、会社)で予測する。実機の記録と一致することをテストで確かめる(オレンジ 28 / 28 / 32、Mediterranean 4 など。RULES.md の 2026-11-02 の記載)
- 会社の支払いは実機で未確認。予測と合わなければ未確定にして停止し、画像と値を記録する(これが確認の機会になる)

### 3. 手と画面(`moves.py`、`adapter.py`)
- 画面ごとの合法な手:

| 画面(`screens.py`) | 手 |
|---|---|
| board_my_turn_roll | Roll(収監中は PostBail / UseCard も) |
| board_my_turn_end | EndTurn、Build / Sell / Mortgage(Manage 経由)、AcceptTrade 系 |
| buy_dialog | Buy(Yes)/ No |
| (FOR SALE 表示。未対応) | Buy / Pass |
| auction / bid_keypad | Bid(額)/ Forfeit |
| trade(AI の提案) | AcceptTrade / DeclineTrade |
| jail_dialog | Yes / No |
| board_ai_turn | なし(待つ) |

- `MonopolyStrategy.choose` は、`ExpectedValuePolicy` の判断を手に変える。Policy は `Game` を引数にとるため、`tracker` の状態から `Game` 相当の読み取り専用ビューを作って渡す(または Policy の入力を `MonopolyState` + 補助情報に絞る。実装時に既存テストへの影響が小さい方を選ぶ)
- 戦略の変更はしない(スコープ外)

### 4. 認識(`vision/recognizer.py`)
- `observe(io, previous)`: 画面を取り、`classify_screen` → 画面名。`UiKind` への対応:
  - 自分の手番の盤・ダイアログ: PLAYABLE
  - board_ai_turn: WAITING
  - game_statistics: GAME_OVER
  - main_menu、pause、unknown: UNKNOWN(停止候補)
  - FORBIDDEN: 対象なし(オンライン対戦の画面が見つかったら追加)
- PLAYABLE のときだけ、所持金と出来事を読み、`tracker` を更新して状態を返す。信頼度は、読み取った要素の最小値

### 5. 操作(`vision/executor.py`)
- 手ごとのタップ列と、確認する画面の変化:
  - Roll: `HoldDrag`(Roll ボタン位置から上へ)→ Roll 表示が消える
  - EndTurn: ボタンをタップ → 画面が AI の手番に変わる
  - Buy: Buy → Yes。見送り: Pass → Yes
  - Bid: キーパッドで数字 → ACCEPT。Forfeit
  - Build: Manage → IMPROVEMENTS → 該当の土地の + → Make Changes → Yes。Manage が拡大盤を開いたら、Return で戻って再試行(上限回数つき)
  - 刑務所: ダイアログの Yes / No
- 各手の前に、画面が想定の画面であることを確かめる。後に、想定の画面変化を確かめる。違えば `ExecutionResult(success=False)` で止める
- 入力は、ゲームの画面が前面にある(Android: 対象アプリがフォアグラウンド)ときだけ送る

### 6. 停止と回復
- 停止の理由と画像を、実行ログ(`runs/`)に残す(既存の `RunSink`)
- アプリの強制終了: 画面が main_menu または端末のホームに変わったことと、`adb shell pidof com.eamobile.monopoly_na_wf` で検知する。メインメニューなら、PLAY NOW → Resume で戻る。Resume が出ない(保存が無い)場合は停止する
- 復帰後は、保存時の状態に戻るため、`tracker` を保存時点の記録まで巻き戻す(強制終了の間の出来事は破棄)。巻き戻せない場合は未確定にして停止する

## 実装の順序

1. `HoldDrag`(共通基盤)と実機確認。依存なしで先に進められる
2. `config/monopoly.toml`、プラグインの骨組み、手の型
3. 操作の座標を、実機で操作して確かめる(1 手ずつ。購入の確定のような戦績に関わる操作は、ユーザーが対局中であることを確認して行う)
4. executor(座標が確かめられた手から)
5. tracker と整合検査(計画 1・2 の完成後に、実際の読み取りをつなぐ。型とテストは先に進められる)
6. adapter(Policy → 手)、recognizer
7. 段階 A → B → C の順に実機で検証
8. 強制終了からの復帰

## エラーハンドリング戦略
- 認識・読み取りの失敗は例外にせず、不明として返す
- 操作の失敗は `ExecutionResult(success=False, reason)` で返す。同じ手の再試行は、設定の回数(既定 2)まで。それを超えたら停止
- adb の失敗は `SourceLostError`(既存)

## テスト戦略
- ユニット: tracker(出来事の列から状態。賃料の予測は RULES.md の実機の値)、adapter(画面と状態から手)、`HoldDrag` の adb コマンド生成(偽の runner)
- 統合: 録画画像の列(`datasets/`)と偽の `GameIo` で、認識 → 戦略 → 操作の流れ。想定外の画面で停止すること
- 実機(`-m device`): HoldDrag の Roll、1 手ずつの操作、段階 A〜C

## セキュリティ考慮事項
- `adb` は必ず `-s 355092380222016`。端末のデータ消去などの操作はコードに入れない(CLAUDE.md)
- アプリを離れるときは HOME キー。`am force-stop` は使わない(保存を壊す)
- 新しい対局の開始、Abandon、Save & Exit の操作は、executor に入れない(戦績・保存に影響する)

## パフォーマンス考慮事項
- 手番の待ち(AI の手番)は、画面の変化を一定間隔で見る。間隔と上限は `config/monopoly.toml`
- 認識は、画面の種類に応じて必要な読み取りだけを行う(盤では所持金と出目、ダイアログでは画面名のみ)
