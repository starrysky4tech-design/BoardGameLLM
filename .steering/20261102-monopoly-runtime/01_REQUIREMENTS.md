# 要求内容

## 概要

Monopoly を `bglm run --game monopoly` で、Python だけで自律的に対局できるようにする。プラグイン登録、状態の追跡、方針と手の対応、実機の操作(executor)、停止と回復を作る。
自律対局の3計画の3番目(1: 所持金 `20261102-monopoly-cash-reader`、2: 出目と Log `20261102-monopoly-log-reader`)。

## 背景

- 現状の Monopoly は、`logic/`(ルール、方針、模擬エンジン)と `vision/screens.py`(画面の判別)だけ。プラグイン登録、操作、状態の追跡、設定は無い
- 共通基盤の `GamePlugin` は、`Recognizer / Rules / Strategy / MoveExecutor` の形を要求する。Monopoly の `logic` は、模擬エンジン `Game` と、`Policy`(`wants_to_buy`、`auction_limit`、`manage`、`propose_trades`、`respond_to_trade`)で作られており、形が違う。接続する層が要る
- 2026-11-01 の手動対局で起きた不具合は、そのまま設計の要求になる:
  - 所持金の表示の更新が遅れ、取り違えた(5 回)
  - GO 通過の +200 が Log に出ず、整合しなかった
  - 土地の所有者を、18 手番にわたって取り違えた(赤グループを未所有と思い込んだ)
  - アプリが強制終了した(第 21 手番、SIGSEGV)。Resume で保存済みの状態に戻った
  - Manage が建設画面ではなく拡大盤を開いた。戻るタップが 1 回では効かなかった
  - Roll が `input swipe` では反映されず、「タッチ → 保持 → 上へ移動」で反映された
- 本番では Claude は介入しない(memory `monopoly-operating-model`)。想定外の画面や認識の失敗は、停止して記録する設計にする

## 実装対象の機能

### 1. 入力の拡張(共通基盤)
- 「押下 → 保持 → 移動 → 離す」の入力 `HoldDrag` を `InputAction` に追加し、`AdbDevice` で実装する(Roll のフリックに必要)
- 共通基盤の変更は、インターフェースの不足として記録する(`docs/04`「ゲームの追加」)

### 2. プラグイン登録と設定
- `plugins/monopoly/__init__.py` に `create_plugin()`。`config/monopoly.toml`(端末、閾値、待ち時間)
- `bglm run --game monopoly` で読み込まれる

### 3. 状態の追跡(`logic/tracker.py`、画面に依存しない)
- 出来事(出目、購入、落札、支払い、カード、刑務所)と所持金の読み取りから、状態(位置、所有、家、抵当、所持金)を更新する
- 整合検査: 出来事から予測した所持金と、読み取った所持金を比べる。ずれたら「未確定」にして、次の判断を止める(既定値で埋めない)
- 所持金の表示の更新遅れは、再読み取りで確かめる。GO 通過(位置が 40 を超える)は +200 として予測に含める

### 4. 方針と手の対応(Strategy / Rules の接続層)
- 手(`Move`)の型: Roll、EndTurn、Buy、Pass、Bid(額)、Forfeit、Build(土地の組)、Sell、Mortgage、Unmortgage、AcceptTrade、DeclineTrade、PostBail、UseCard
- 画面の種類ごとに、合法な手を決める。方針(`ExpectedValuePolicy`)の判断を、手に変える
- 取引の提案(`propose_trades`)は、最初の版では送らない(受ける・断るだけ)

### 5. 実機の操作(executor)
- 手ごとに、タップ列を実行し、画面の変化で成否を確かめる(Kahuna の `executor.py` と同じ方式)
- 座標は、実機で操作して確かめてから書く(CLAUDE.md「画面の配置は操作して確かめてから」)

### 6. 停止と回復
- 判別できない画面、状態が未確定、操作の失敗が続く: 入力を送らず停止し、画像と状態を記録する
- アプリの強制終了を検知したら、メインメニューの Resume で保存済みの対局に戻る。新しい対局は始めない(戦績が変わるため。ユーザーが開始する)

## 受け入れ条件

### 入力
- [ ] `HoldDrag` で、実機の Roll が反映される(Roll 表示が消え、End Turn が出る)。10 回連続で成功する

### 縦通し(段階的)
- [ ] 段階 A(読み取りのみ): 実機の対局を、操作せずに 20 手番観察し、状態の追跡が実際の画面(所持金、位置、所有)と一致する
- [ ] 段階 B(基本の手): Roll → 購入または見送り → End Turn の手番を、step モードで 10 手番、停止なく進める
- [ ] 段階 C(全部の手): オークション、刑務所、建設、取引の受け答えを含めて、1 局を最後まで auto モードで進める(終局は勝敗または上限)

### 安全
- [ ] 想定外の画面で入力を送らず、停止して画像と状態を記録する(テスト: 画面を差し替えた模擬環境)
- [ ] 所持金が予測と合わないとき、次の判断を止める
- [ ] アプリの強制終了から Resume で復帰する(実機)。復帰後の状態が保存時と一致する
- [ ] 実機に誤入力が 0 回(別のアプリへのタップ、意図しない購入・入札)

### 構造
- [ ] `logic` が `vision`・`infrastructure` を import しない。`application` から `plugins` を import しない(`lint-imports`)

## 成功指標

- 段階 C の 1 局を、人の操作なしで終える(停止した場合は、停止の理由が記録に残り、理由が設計の想定内であること)
- 誤入力 0 回

## 前提・仮定

- 計画 1(所持金)と計画 2(出目と Log)が完了していること。段階 A 以降は、この 2 つに依存する。依存しない部分(入力の拡張、設定、型、操作の座標確認)は先に進める — 根拠: 読み取りの精度が、状態の追跡の前提(`monopoly-operating-model`)
- 新しい対局の開始は、ユーザーが行う。Python は、進行中または保存済みの対局を続ける — 根拠: CLAUDE.md「ユーザーのアカウントに影響する操作は事前に確認する」
- 相手は Very Easy の AI、2 人対局 — 根拠: `RESULT.md`
- 手の座標は、実機で操作して確かめた位置のみ使う。画面は 2432x1080 固定 — 根拠: CLAUDE.md、`RESULT.md`

## スコープ外

- 取引の提案(`propose_trades`)の送信。受け答えだけを実装する
- Very Easy 以外の難易度、3 人以上の対局
- 戦略の調整(`logic/policies.py` の変更)
- 新しい対局の開始、課金や戦績に関わる操作
- VLM の利用

## 参照ドキュメント

- `docs/02_FUNCTIONAL-DESIGN.md` - GamePlugin、実行状態の遷移、エラーハンドリング
- `docs/03_ARCHITECTURE-DESIGN.md` - レイヤー、資源の配分
- `docs/04_REPOSITORY-STRUCTURE.md` - ゲームの追加(スケーリング戦略)
- `docs/05_DEVELOPMENT-GUIDELINES.md` - テスト戦略、外部操作
- `.steering/20261101-phase-monopoly/RESULT.md`、`RULES.md` - 実機の事実
- `.steering/20261102-monopoly-cash-reader/`、`.steering/20261102-monopoly-log-reader/`
- `runs/monopoly-manual-20261101/journal.jsonl` - 手動対局の記録(不具合の事例)
