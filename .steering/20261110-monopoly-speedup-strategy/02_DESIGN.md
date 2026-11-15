# 設計書

## アーキテクチャ概要

既存のレイヤー(`logic` は画面に依存しない、`vision` が実機の入出力、`runtime.py` が実行ループ)は変えない。変えるのは次の 3 点。

1. **観測を「全体盤 1 枚」に集約する。** 通常の盤の画面の取得画像 1 枚から、所持金・所有・抵当・家の有無・出目をまとめて読む(`BoardObservation`)。画面を開く操作(拡大盤、Log)は、1 枚で分からないことがあるときだけ行う。
2. **台帳(Log と操作の結果で更新した状態)を主、画面を照合に使う。** 食い違いは、食い違った土地・色グループだけを直す。全体の読み直しは、照合で直せないときの最後の手段にする。
3. **同期の処理を、作業用スクリプトから `src` に移す。** `scripts/run_agent.py` の `process_log` と `resync` は、テストが無く、ここを変えるため、`plugins/monopoly/sync.py` に移してテストを付ける。

```
                         ┌──────────── runtime.step ────────────┐
 取得画像 1 枚 ──► vision/board_scan.observe ──► BoardObservation│
                    (cash / 所有の棒 4 辺 / 抵当の印 / 家の有無 / 出目)
                                   │
                                   ▼
 Log(周回に 1 回、つながるまで) ─► sync.Synchronizer ──► MonopolyState・位置(台帳)
                                   │  logic/reconcile: 台帳と観測の差 → 直す土地・開く色
                                   │  食い違いが残る → 独占の色だけ拡大盤(vision/holdings)
                                   ▼
                         logic/decisions.Decider
                 (policies: 建設の期待値 / opponent_model: 入札の上限 / auction_bid)
```

## コンポーネント設計

### 1. `vision/board_scan.py`(新規): 全体盤 1 枚の読み取り

**責務**:
- 全体盤の 4 辺の所有の棒から、28 か所の所有者を読む(`Owner.ME` / `AI` / `NONE`、読めなければ `None`)
- マスの上の抵当の印(赤い「M」)の有無を読む
- マスの上の家・ホテルの絵の有無(できれば軒数)を読む
- 所持金(`cash.read_cash`)、出目(`dice.read_with_pips`)と合わせて `BoardObservation` を返す

**実装の要点**:
- `bars.View` は横の帯(下辺)専用。左右の辺は縦に並ぶので、`View` に軸(`axis: "x" | "y"`)を足し、`find_bars` を軸に沿って切り出す形に一般化する。既存の `global_bottom`、拡大盤の `View` は `axis="x"` のまま動く
- 4 辺の `View`(`global_bottom`、`global_left`、`global_top`、`global_right`)の帯と土地の中心は、実機の画像で測って登録する(下辺は登録済み。上辺 y≈215、左辺 x≈850〜880、右辺 x≈1620〜1690 が目安。実測で確定する)。盤は遠近で台形なので、左右の辺は土地ごとに帯の x が違う。土地ごとの矩形(x0,y0,x1,y1)で持つ
- 抵当の印: 土地ごとの矩形(マスの内側)の中の、赤の画素の割合で判定する。赤の色グループ(Kentucky、Indiana、Illinois)は色帯が赤なので、色帯を除いた矩形にする。鉄道・会社にも印が出る(`after_auto_sell.png` で確認)
- 家の有無: 土地ごとの矩形(色帯の上)の中の、家の緑・ホテルの赤の塊で判定する。軒数まで読めるかは、フェーズ 0 の実機の画像で決める。読めなければ `has_buildings: bool | None` だけを返す
- 駒・ダイスが棒や印に重なると読めない。その土地は `None` を返す(推測しない)。呼び出し側は、次の取得で読み直す
- 色補正(`color_is_normal` が False)のときは、全て `None`

```python
@dataclass(frozen=True)
class DeedScan:
    owner: Owner | None          # 読めなければ None
    mortgaged: bool | None
    has_buildings: bool | None
    houses: int | None = None    # 全体盤から軒数まで読めた場合だけ

@dataclass(frozen=True)
class BoardObservation:
    cash: CashPair
    deeds: Mapping[str, DeedScan]
    dice: DiceSnapshot | None
```

### 2. `logic/reconcile.py`(新規): 台帳と観測の照合

**責務**:
- 台帳(`MonopolyState`)と観測(所有・抵当・家の有無。`logic` の型に変換済みのもの)を比べ、(a) その場で直せる差、(b) 画面を開いて確かめる色グループ、(c) 直せない差、に分ける

**実装の要点**:
- 入力は `logic` の型だけ(`vision.Owner` を import しない)。変換は `sync.py` が行う
- 所有の差: 観測が読めていて(`None` でない)、2 回続けて同じ読みなら、観測を採る(1 回の読みで台帳を書き換えない。駒の重なり・演出中の誤読を避ける)。新しい所有者に移すとき、価格が分からない取得(AI の競りの落札)は、所有だけ直し、現金は画面の値を採る
- 抵当の差: 同じく 2 回続けて同じ読みなら、観測を採る(これで、保存から引き継いでいた抵当の旗が、画面から直る)
- 家の差: 台帳が 0 軒で観測が「家あり」、または台帳が 1 軒以上で観測が「家なし」なら、その色グループを「開いて確かめる」に入れる。全体盤から軒数まで読める場合は、軒数の差も同じ扱い
- 独占でない色グループに家がある、という観測は誤読として捨て、記録に残す

### 3. `vision/holdings.py`(変更): 独占の色だけを開く

**責務**:
- `read_groups(driver, groups)`: 渡された色グループだけ、拡大盤または建設画面を開いて、軒数を読む
- 既存の `read_all_holdings`(8 グループの巡回)は、`board_scan` で読めない土地が残ったときの予備として残す(呼び出しは `sync` の最後の手段だけ)

**実装の要点**:
- 軒数は、その色グループ自身の画面の読みだけを採る(`merge_view` の「own」の読み)。隣の色の端の読みは、軒数に使わない
- AI の独占は拡大盤(`bars.read_view_full`)、自分の独占は建設画面(`bars.read_buildings`)。既存の読み取りをそのまま使う
- 待ち時間(`OPEN_SEC` 3.0、`HELP_SEC` 2.0、`RETURN_SEC` 2.5)は、固定の待ちをやめ、「画面の種類が期待どおりになるまで 0.5 秒間隔で確かめる(上限は現在の値)」に変える

### 4. `plugins/monopoly/sync.py`(新規): 同期

**責務**:
- `scripts/run_agent.py` の `process_log`、`resync`、保存(`session.pkl`)を移す。`run_agent.py` は引数の解釈と組み立てだけにする
- Log を読む時機を決める。読む量を決める。台帳・位置・現金を更新する
- 照合(`reconcile`)の結果に従い、直す・開く・止める

**実装の要点**:
- **Log を読む時機**: (a) 自分の Roll の画面に戻ったとき(AI の手番の後。周回に 1 回)、(b) End Turn の直前で、建設の判断に相手の位置が要るのに、位置が未確定のとき、(c) 現金の照合が合わないとき。操作(Roll、カードを閉じる、購入…)のたびには読まない
- **自分の手番の間の状態**: 所持金は画面の値をそのまま採る(タップなし)。自分の位置は、出目、または購入画面・競りの土地名(盤で一意)で進める。所有は、購入の成功・競りの結果の画面(次の全体盤の棒)で更新する。Log の行は、次の周回の読みでまとめて照合する(同じ出来事を二重に数えないよう、既存の `own_action_events` と同じ考え方で、反映済みの出来事に印を付ける)
- **読む量**: `log_reader.read_until_joined(driver, ocr, cursor, max_pages=10)`。1 ページ読むごとに、前回の読みの末尾とつながったかを調べ、つながれば打ち切る。上限まで読んでもつながらなければ `gap`
- **gap・現金の食い違いのとき**: 全体盤の観測で所有・抵当を直し、現金は画面の値、位置は Log の最後の「landed on」。家は、独占の色だけ開く。これが新しい「再同期」(目標: 10 秒 + 独占の色の数 × 10 秒)
- 既存の、現金の食い違いの許容(数 ₼、片側の少額、対称な移動)は、そのまま移す
- AI の所持金が読めないときは、0.7 秒あけて 2 回まで取り直す(手番の側の切り替えの演出中に読めないことがある、という見立て。フェーズ 0 で、読めない画面を保存して原因を確かめる)

### 5. `vision/roll_reader.py`(変更): 出目

**責務**:
- 出目の確定を 2 系統にする: 画面(点の数)と Log(`rolled N` と `Doubles`)

**実装の要点**:
- `RollWatcher.arm` は、直前の `BoardObservation.dice`(すでに取得済みの画像)を使う。Roll の前に、静止の確認のための取得(2 回 × 1 秒)をしない
- Roll の後の固定の待ち(`ROLL_WAIT_SEC` 9.0)は、「0.7 秒間隔で取得し、メニューが出て、点の位置が 2 回続けて同じになったら確定」に変える。上限は現在の値 + 余裕
- Roll の直前の待ち(`ROLL_SETTLE_SEC` 3.0)は、Roll の画面を最初に見た時刻から数える(画面を見てから 3 秒たっていれば、待たない)
- 割り込み(カード、購入画面、競り)で読めなかった出目は、`pending_roll` として持ち、次に全体盤が見えたときに画面から読む(点が Roll の前と違えば、今回の出目)。それも読めなければ、次の Log の読みの `rolled N` で確定する。位置は、購入画面・競りの土地名から先に決まる
- 画面と Log の出目が食い違ったら、Log を採り、記録に残す(Log は「landed on」とも照合できるため)
- ダブルの判定は、画面の 2 個の目が同じ、または Log の `Doubles`。どちらも無いまま Roll の画面が続けば、ダブル(振り直し)とみなして進める(現行と同じ)

### 6. `logic/landing_odds.py`(新規)と `policies.py`(変更): 建設の時機

**責務**:
- `next_turn_landing(position, in_jail) -> Mapping[int, float]`: 相手の次の 1 手番で、各マスに止まる確率(ダブルの振り直しを 3 回目の収監まで含める。Go To Jail のマスは刑務所へ。収監中は、ダブル(1/6)のときだけ出る。カードの移動は、`cards.py` の移動カードの割合で近似する)
- 建設の判断を、期待値の比較にする

**実装の要点**:
- 1 軒ごとに `gain = Σ P(相手がその土地に止まる) × (建てた後の賃料 − 建てる前の賃料)` を出す。均等建設の規則の中で、`gain / house_cost` が大きい順に 1 軒ずつ建てる
- 建てる条件: `gain / house_cost >= BUILD_MIN_RETURN`、かつ、建てた後の現金が `reserve`(自分の次の 1 手の最悪の支払い)以上
- `BUILD_MIN_RETURN` は、シミュレーション(`logic/simulation.py`、現行の方針との対戦)で決め、根拠を `docs/02` に書く。境界値は `docs/05`「パラメータ境界値の設計」に従う(0 < 値 ≤ 1 を検査する)
- ホテルも同じ式(4 軒 → ホテルの賃料の増分)。`_target_houses`(現金の閾値で 3・4・5 軒)は廃止する
- 現金に大きな余裕があるとき(建てた後も `reserve` + `BUILD_SURPLUS` を保てる)は、確率が低くても建てる(建てずに置く利点が無い)。`BUILD_SURPLUS` もシミュレーションで決める
- 相手の位置が未確定(`LiveState.positions` に無い、または同期が外れている)なら、建てない
- **建てる時点を End Turn の直前に移す**(`runtime._end_turn`)。`runtime._roll` の `_build_before_roll` は呼ばない。理由: 自分の Roll の後の支払い・購入を終えた現金で判断でき、建てた直後に相手が動く
- 既存の「入口から遠い土地を厚く」(2026-11-08 の指示)は、確率の式に含まれる(相手の位置から届く土地ほど `gain` が大きい)ので、並び順の規則としては外す。同じ `gain / cost` のときの順は、盤の番号が大きい方を先にする
- `opponent_near_distance`、`build_when_opponent_near` は削除する(呼び出し元は `policies.py` とテストだけ。Grep で確認してから消す)

### 7. `logic/opponent_model.py`(新規): 相手の入札の上限

**責務**:
- `BidModel.ceiling(deed, ai_cash, ai_holdings) -> int`: 相手がその土地に入札する上限の推定
- 対局中の観測で、推定を更新する

**実装の要点**:
- 推定は `min(ai_cash, ratio × 定価)`。`ratio` は難易度ごとの値で、これまでの記録から決める
  - 記録: `events_game2_easy_final.log`(Easy)、`events_game3_veryeasy.log`(Very Easy)の `AuctionWon(direct=False)` の価格と、その時点の AI の現金(同じ記録の現金の行から再生する)
  - 手元の値(落札額 / 定価): Easy は Virginia 168/160、St. Charles 141/140、Short Line 185/200、Electric Company 98/150。Very Easy は Virginia 145/160、Pacific 268/300、Atlantic 183/260、Pennsylvania Railroad 92/200、Oriental 55/100
  - ただし、AI の落札額は「AI の上限」ではなく「自分が降りた額 + 刻み」。上限の下限値にしかならない。自分が落札した競り(AI が降りた額)が上限の観測になる: Very Easy は Park Place 306/350、Marvin Gardens 181/280、Electric Company 85/150、St. James 90/180、Illinois 90/240、North Carolina 40/300、Mediterranean 40/60。このうち、AI の現金が尽きて降りたものを、記録の現金から除く。この整理はタスクとして行い、表を `RESULT.md` に残す
- 記録が足りない難易度、相手が同色を持つ土地(独占に近づく土地は、AI が高く入札しうる)は、保守的に `ceiling = ai_cash`(全額まで入札する)とする
- 対局中の更新: 競りで、AI が推定の上限を超えて入札したら、その競りの間は `ceiling = ai_cash` に切り替え、`ratio` を観測値まで上げて保存する(同じ対局の次の競りに使う)。AI が降りた額は、上限の観測として記録に残す
- 難易度は、起動時の引数(`--difficulty`)で渡す。未指定は「不明」= 保守的な値

### 8. `policies.py` / `auction_bid.py` / `decisions.py`(変更): 競り

**競りで安く買う(購入画面の見送り)**:
- `wants_to_buy` の見送りの条件を広げる。現行「相手が定価を払えない」→ 新「相手の上限の推定 + 1 が、定価 × (1 − `AUCTION_MIN_DISCOUNT`) 以下」
- 次のどれかなら、見送らずに定価で買う: 独占の完成・阻止(`deed_value` の strategic)、相手が同色を 1 枚以上持つ(妨害価値がある)、推定が保守的な値(`ceiling = ai_cash` かつ `ai_cash >= 定価`)
- 価値は、これまでどおり `deed_value`。購入画面の判断と競りの上限は、同じ値から出す

**競りの入札(落札したいとき)**:
- 現行は、最初から「相手の現金と同額」を入れる。相手の上限が現金より低いときは、払いすぎになる
- 新: 最初の入札は `min(相手の上限の推定, 自分の上限)`。相手が上回ったら、刻み(`raising_bid`)で上げる。入札の回数が `MAX_BID_ROUNDS`(1 回 約 15 秒なので 4 回)を超えたら、「相手の現金と同額」(自分の上限の範囲なら)で決める
- 相手の上限の推定が保守的な値のときは、現行と同じ(相手の現金と同額)

**相手に高く買わせる(落札したくない・できないとき)**:
- `drain_bid(highest_bid, ceiling, my_cash, keep, my_value, max_regret) -> int | None`
- 入札するのは、次を全て満たすときだけ: 入札額 ≤ `ceiling − DRAIN_MARGIN`(相手がまだ上回る見込み)、入札額 ≤ `my_cash − keep`(落札しても残す現金を割らない)、入札額 − `my_value` ≤ `max_regret`(誤って落札したときの損の上限)
- 刻みは、`ceiling` までを `RAISE_STEPS` 回で上がる幅(入札の回数を抑える)
- 相手の上限の推定が保守的な値(`ai_cash`)のときは、`DRAIN_MARGIN` を大きく取る(相手が全額まで来るとは限らないため)。`max_regret` の既定は定価の 10%(誤落札でも、抵当価値 = 定価の 50% は回収できるので、実損はさらに小さい)
- `Decider.auction_bid` の順: ① 落札の入札(上限の範囲)→ ② 無ければ `drain_bid` → ③ 無ければ降りる
- 既存の停止条件(入札額が画面の自分の現金を超えたら送らない)は、そのまま

## データフロー

### 通常の 1 周回
```
1. Roll の画面: 取得 1 枚 → BoardObservation(現金・所有・抵当・家の有無・直前の出目)
2. Log を、前回の読みにつながるまで読む(通常 1〜2 ページ)→ 台帳・位置を更新、現金を照合
3. 台帳と観測を照合 → 差があれば直す / 独占の色だけ開く
4. Roll → 出目(画面)→ 自分の位置を進める
5. 割り込み(購入・競り・カード)を処理。所持金は画面、位置は土地名で確かめる
6. End Turn の画面: 取得 1 枚 → 現金を更新 → 建設の判断(相手の位置は 2 の値)→ 建設 → End Turn
7. AI の手番を待つ → 1 へ
```

### 食い違い(現金が合わない、Log がつながらない)
```
1. 全体盤の観測で、所有・抵当を直す(2 回続けて同じ読み)
2. 現金は画面の値、位置は Log の最後の「landed on」
3. 独占の色グループだけ開いて、軒数を読む
4. 28 か所のうち読めない土地が残れば、その土地の色グループだけ拡大盤で読む
5. それでも決まらなければ止める(推測で埋めない)
```

## エラーハンドリング戦略

### カスタムエラークラス

追加しない。読み取りの失敗は、既存と同じく「値を返さない(`None`)+ 理由」で表す。

### エラーハンドリングパターン

- 読めない値は `None`。台帳を、1 回の読みで書き換えない(2 回続けて同じ読み)
- 照合で直せない食い違い、位置の未確定は、`StepResult(STOPPED, reason=...)` で止める(既存の安全規則)
- 建設・入札は、判断の入力(相手の位置、現金、土地)が不明なら、行わない

## テスト戦略

### ユニットテスト
- `board_scan`: 評価画像(`my_turn_end_turn.png`、`after_auto_sell.png`、フェーズ 0 で取る画像)の、28 か所の所有・抵当・家の有無。正解は、画像を見て手で作る(実装の出力から作らない)。駒が重なった土地は `None`
- `bars`: `axis` の一般化の後も、既存の拡大盤・下辺のテストが通る(回帰)
- `reconcile`: 所有の差(1 回目は保留、2 回目で採用)、抵当の差、家の差 → 開く色グループ、独占でない色の家の観測は捨てる
- `holdings.read_groups`: 独占 0 色なら画面を開かない、k 色なら k 色だけ(偽の `Driver`)
- `log_reader.read_until_joined`: 1 ページでつながれば 1 ページ、つながらなければ上限まで読んで `gap`
- `sync`: `run_agent.py` から移した分岐(少額、片側、対称、gap)を、偽の入力で 1 つずつ
- `roll_reader`: 割り込みの後の `pending_roll`、画面と Log の食い違いで Log を採る、待ちの短縮(偽の時計で、取得の回数を数える)
- `landing_odds`: 確率の合計が 1、収監中はダブルだけ、3 回ダブルは刑務所。期待値は、ルール(`RULES.md`)から手で計算した値と比べる(例: 7 マス先 = 6/36 + 振り直しの分)
- `policies`: 確率が高い位置で建てる・低い位置・収監中・位置不明で建てない、ホテルまで建てる条件、`BUILD_MIN_RETURN` の境界
- `opponent_model`: 上限の推定、保守的な値への切り替え、対局中の更新
- `auction_bid.drain_bid`: 上限の手前で止まる、現金・損の上限を超えない
- `policies.wants_to_buy`: 推定が定価を下回れば見送る、独占に関わる土地・妨害価値のある土地は買う

### 統合テスト
- `runtime`: 偽の `Driver` で 1 周回を流し、Log を開く回数が 1 回であること、建設が End Turn の直前に行われること
- シミュレーション: 新しい建設の基準と、現行(入口の手前 7 マス)を対戦させ、勝率が下がらないこと(`logic/simulation.py`、乱数の種を固定)
- 実機(`-m device` ではなく、3 局目の続きを手元で実行): 受け入れ条件の実測(再同期の時間、Log を開く回数、出目の確定率、AI の現金が読めない回数)

## 依存ライブラリ

追加なし。

## ディレクトリ構造

```
src/bglm/plugins/monopoly/
  sync.py                    新規: Log・現金・所有の同期(run_agent.py から移す)
  runtime.py                 変更: 建設を End Turn の直前へ、観測の共有、Log の時機
  logic/
    reconcile.py             新規: 台帳と観測の照合
    landing_odds.py          新規: 次の 1 手番で止まる確率
    opponent_model.py        新規: 相手の入札の上限
    policies.py              変更: 建設の期待値、見送りの条件
    auction_bid.py           変更: 最初の入札、drain_bid
    decisions.py             変更: 入札の順、LiveState に難易度・入札の観測
  vision/
    board_scan.py            新規: 全体盤 1 枚の読み取り
    bars.py                  変更: View の軸、4 辺の View
    holdings.py              変更: read_groups、待ちの短縮
    log_reader.py            変更: read_until_joined
    roll_reader.py           変更: 待ちの短縮、pending_roll
tests/plugins/monopoly/unit/  上記のテスト
.steering/20261110-monopoly-speedup-strategy/
  RESULT.md                  実機の実測、全体盤の読み取りの確認結果、入札の記録の表
  scripts/                   実測・画像の取得の作業用スクリプト
.steering/20261104-monopoly-autoplay-handoff/scripts/run_agent.py   変更: 組み立てだけに
```

## 実装の順序

1. フェーズ 0: 現状の実測(d ログから、1 周回の時間、Log の回数)。実機で 3 局目を再開し、全体盤の画像を取る(家が建っている状態、抵当、駒が棒に重なる状態、AI の現金が読めない瞬間)。全体盤から軒数まで読めるかを決める
2. `bars.View` の軸の一般化 → `board_scan`(所有 → 抵当 → 家の有無)
3. `reconcile` → `holdings.read_groups` → `sync`(`run_agent.py` からの移動を先に、挙動を変えずに行い、テストを付けてから、新しい流れに変える)
4. `log_reader.read_until_joined` と、Log の時機の変更
5. `roll_reader` の変更
6. `landing_odds` → 建設の基準 → End Turn の直前へ移す → シミュレーションで定数を決める
7. 入札の記録の整理 → `opponent_model` → 見送りの条件 → 入札(最初の入札、`drain_bid`)
8. 実機の確認(3 局目の続き)→ 受け入れ条件の実測
9. 品質チェック、`docs/02`「Monopoly の判断」・`docs/04` の実装ファイル一覧・`docs/06` の用語の更新、振り返り

## セキュリティ考慮事項

- 実機の操作は、これまでどおり `adb -s 355092380222016`。端末の削除・データ消去は入れない
- 新しい対局の開始(戦績が変わる)は、今回の作業では行わない。保存してある 3 局目の続きだけを使う。3 局目が終局したら、次の対局の前にユーザーへ確認する
- 評価用に取る画像は `datasets/` に置き、コミットしない

## パフォーマンス考慮事項

- `board_scan` は 1 枚あたり 50 ms 以内を目安にする(色のマスクと連結成分だけ。OCR は使わない)。毎ステップ呼んでも、取得(adb の screencap 約 0.5〜1 秒)より小さい
- 固定の待ちを「条件が満たされるまでの短い間隔の確認」に変える箇所は、上限を現在の待ち時間以上にする(遅い端末で、これまで通っていた操作が失敗しないように)
- 入札は 1 回 約 15 秒。`drain_bid` と最初の入札の刻みは、回数が増えすぎないようにする(`RAISE_STEPS`、`MAX_BID_ROUNDS`)

## 将来の拡張性

- `BidModel` は、取引の応答の傾向(Very Easy は何でも承諾する)も同じ形で持てるようにしておく(今回は入札だけ)
- 3 人以上の対局では、`landing_odds` を相手ごとに足せばよい形にする(今回は 2 人)
- `BoardObservation` に駒の位置を足せば、位置の照合が 3 系統になる(今回はスコープ外)
