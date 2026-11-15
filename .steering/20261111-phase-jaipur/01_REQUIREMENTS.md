# 要求内容

## 概要

Android 版「Jaipur」(`com.meepletouch.jaipur` 1.4)の SOLO(対 CPU)を自動でプレイするプラグイン `jaipur` を追加する。Kahuna・Hive と同じ共通基盤(認識 → 思考 → 操作のループ、安全装置、ログ、リプレイ、評価)の上に、`plugins/jaipur/` を書き足す形で作る。

## 背景

- Android のボードゲームの自動対戦を増やす方針の 7 本目(Kahuna、Hive、Monopoly、Maquis、King & Assassins、Colt Express に続く)
- 実機(SHG11)に導入済みで、接続手段(adb)をそのまま使える。未ログインで、SOLO はローカルの対局(`RESULT.md` §1)
- 隣の `BoardGameAI` に、Jaipur のシミュレータ・公開情報の追跡・探索(ISMCTS)が、画面に依存しない形で実装済み(実機との接続は未着手)。ルールと思考をゼロから作らずに済む
- 2 人用で、隠れた情報(相手の手札、山札、ボーナストークンの値)がある。盤は固定で、手は「選択 → 確定」の 2 段階(`RESULT.md` §2)

## 実装対象の機能

### 1. ルールとシミュレータ(`plugins/jaipur/logic/`)
- 4 種の手(1 枚取る、ラクダを全部取る、交換、売る)の合法手、手の適用、ラウンドの終了と勝者、マッチ(先取数)。画面に依存しない
- 公開情報の追跡(相手の手札のうち分かる札、山札と相手の手札に残る札の内訳、トークンの山)
- 山札と相手の方針を乱数で動かして、1 マッチを完走できる自己対戦

### 2. 思考(`logic/strategy.py`)
- 相手の手札と山札を、見えている情報と矛盾しないように無作為に定めた探索(ISMCTS)で 1 手を選ぶ。持ち時間で打ち切る

### 3. 認識(`plugins/jaipur/vision/`)
- 画面種別(メニュー、設定、対局、吹き出し、ラウンド終了、マッチ終了、不明)
- 市場 5 枠、自分の手札、双方の群れ、相手の手札の枚数、商品トークンの山、ボーナストークンの残数、得点、手番、確定バーの文言
- 相手の手の推定(前後の画面の差。差で 1 つに決まらないときは、進行役の再生で確かめる)

### 4. 操作(`vision/executor.py`)
- 札を選ぶ(タップ)→ バーの文言が意図した手と一致することを確かめる → 確定(タップ)→ 結果を画面で確かめる
- 吹き出しを閉じる、ラウンド終了の表示を進める
- 禁止領域(ONLINE DUEL、ACCOUNT、GAMES、CAMPAIGN、対局中の左上の印)へのタップを拒否する

### 5. 組み込み
- `config/jaipur.toml`、プラグインの登録、`bglm run/eval/replay --game jaipur` が動く
- `tests/plugins/jaipur/`、`scripts/jaipur/`、`assets/jaipur/`、`datasets/{eval,raw}/jaipur/`

## 進める順序(難易度)

1. **難易度 1、2 本先取**(設定画面を開いた時点の選択)で通しの自動プレイ
2. 難易度 2 → 3 → 4。難易度 4 での勝率を最終の KPI とする

## 受け入れ条件

### Phase 0(実機で確かめる)
- [x] パッケージ名、バージョン、起動 Activity、画面の大きさ、ログインの状態が記録されている(`RESULT.md` §1)
- [x] メニューから対局までの画面と、1 枚取る・売るの選択と確定、相手の手の再生が記録されている(`RESULT.md` §2)
- [ ] `RESULT.md` §3 の未確認 1〜12 が埋まっている(SOLO を手で 1 マッチ以上終える)
- [ ] Go / No-Go の最終判断が `RESULT.md` にある

### ルールとシミュレータ
- [ ] 4 種の手の合法性、補充、売却のトークンとボーナス、ラウンドの終了(トークンの山 3 つ、山札切れ)、ラクダトークン、勝者と同点の扱い、マッチを、**ルールの記述から手で作った期待値**で検証している(出典つき。`BoardGameAI` の実装の出力を期待値にしない)
- [ ] 追跡が、全情報のシミュレータから作った視点と一致する(無作為の 1000 マッチ)
- [ ] 固定シードの自己対戦で 1 マッチを完走し、不正な手が出ない

### 認識・操作
- [ ] 手ラベル付けした 30 画面以上で、要素単位 95% 以上(KPI。仮)
- [ ] 想定外の画面、信頼度不足、禁止画面のときは、入力を送らず止まる
- [ ] バーの文言が意図した手と一致しないときは、確定せず、選択を外して止まる
- [ ] 相手の手を 1 つに決められないときは、既定値で埋めない。再生でも決まらなければ止まる

### 自動完走
- [ ] 1 マッチを人手介入なしで終えられる割合が 8 割以上(KPI。仮)
- [ ] 難易度 4 に対するマッチ勝率 5 割以上(KPI。仮。`BoardGameAI` の PC 上の測定では、プレイアウトだけの探索は上位の移植 CPU に 0.26〜0.37、評価関数を混ぜた版は 0.65。葉の評価の改良が前提。`02_DESIGN.md` 論点 5)

## 成功指標

- `docs/01` の KPI を、Jaipur についても同じ基準で測る
- 共通基盤(`core/`、`application/`、`infrastructure/`、`toolkit/`)の変更行数を数えて記録する。不足を直した分は理由を書く

## 前提・仮定

- 対象は端末 SHG11(シリアル `355092380222016`)。アプリの事実は `RESULT.md` — 根拠: 2026-11-11 に adb と取得画像で確認
- **「PLAY A GAME → SOLO GAME」だけを使う**。未ログインで、SOLO はアカウントに影響しないと判断した — 根拠: `RESULT.md` §1。King & Assassins の Solo Practice、Colt Express のローカルと同じ扱い。端末内に戦績が残るかは未確認(`RESULT.md` §3-11)。ログインした状態になったら、対局を始める前にユーザーへ確認する
- ONLINE DUEL、ACCOUNT、GAMES は**禁止**とし、押さない。PASS & PLAY、CAMPAIGN、TUTORIAL は使わない — 根拠: `CLAUDE.md`「ユーザーのアカウントに影響する操作は事前に確認する」
- **`BoardGameAI` から流用するのは、ルール・追跡・探索のうち、デコンパイル結果に由来しない部分に限る**(下の「流用の範囲」)— 根拠: `BoardGameAI/docs/01`「権利上の制約」は移植コードの公開を禁じている。本リポジトリは `scripts/publish_remote.ps1` で GitHub に公開している
- ルールの正本は、公開されている Jaipur のルールとアプリ内の表示。アプリ独自の差(同点の扱いなど)は実機で観測して `RESULT.md` に書く — 根拠: `CLAUDE.md`「ルールの期待値は実装から作らない」
- 接続手段は adb、アプリを離れるときは HOME キー、`am force-stop` は使わない — 根拠: `CLAUDE.md`「実機の操作」
- `GamePlugin` の形で作る。1 回の `execute` は 1 つの手(選択のタップ列 + 確定)または 1 つの表示を閉じる操作とする — 根拠: 確定の前は取り消せるので、選択の途中で止まっても盤面は変わらない(`RESULT.md` §2)

### 流用の範囲(`BoardGameAI` は参照のみ。変更しない)

| `BoardGameAI` | 扱い | 理由 |
|---|---|---|
| `game/types.py`、`actions.py`、`state.py`、`view.py`、`tracker.py`、`search_state.py`、`engine.py` | 写して `plugins/jaipur/logic/` に合わせて直す | 標準ライブラリだけで、画面に依存しない。`cpu/` を import していない |
| `ai/determinize.py`、`ai/ismcts.py`、`game/rollout.py` のプレイアウト | 同上 | 同上 |
| `game/rollout.py` の `heuristic_round_win_probability`(葉の評価) | **出所を確かめてから決める** | 移植 CPU の評価関数に由来するなら流用しない(プレイアウトだけで始める) |
| `game/rules.py`(アプリの XML を読む)、`assets/jaipur/STANDARD.xml` | 流用しない。枚数とトークンの値は、ルールの記述から自前の JSON に書く | XML はアプリの資産 |
| `cpu/`(移植 CPU) | **流用しない** | デコンパイル結果からの移植。公開できない |
| 写したコードの中の、デコンパイル結果への参照(`c/af.java:…` など)と、それだけが根拠の仕様 | 参照を消し、実機の観測かルールの記述で根拠を付け直す。付け直せないものは「未確認」とする | 同上 |

## スコープ外

- ONLINE DUEL、PASS & PLAY、CAMPAIGN、TUTORIAL、標準以外のルール
- 移植 CPU、Jev 型の判断モデル、自己対戦による学習(`BoardGameAI` の Phase 3 以降)
- アプリの改造・再署名、保存データの書き換え
- `BoardGameAI` の変更、他のゲームの作業

## 参照ドキュメント

- `docs/01_PRODUCT-REQUIREMENTS.md`、`docs/02_FUNCTIONAL-DESIGN.md`、`docs/03_ARCHITECTURE-DESIGN.md`
- `docs/04_REPOSITORY-STRUCTURE.md` - 「スケーリング戦略/ゲームの追加」の手順
- `E:\Workspace\repository\LLMProject\BoardGameAI\docs\02_FUNCTIONAL-DESIGN.md` - ルール仕様、`KnowledgeTracker`、`Determinizer`、ISMCTS、実機接続の設計(未実装)
- `.steering/20261111-phase-coltexpress/`、`.steering/20261111-phase-maquis/` - 同じ進め方をした計画
