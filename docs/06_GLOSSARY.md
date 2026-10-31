# プロジェクト用語集 (Glossary)

> **本書が単一情報源とする範囲**: 用語の1行定義と略語の正式名称。
> データモデルの型定義は `02_FUNCTIONAL-DESIGN.md`、技術スタックの詳細は `03_ARCHITECTURE-DESIGN.md`、ファイル一覧は `04_REPOSITORY-STRUCTURE.md` を参照すること。

## プロダクト共通の用語

| 用語 | 英語 | 定義 |
|---|---|---|
| 共通基盤 | core platform | 全ゲームで共有する画面取得、操作、実行ループ、ログ、VLM連携の総称 |
| プラグイン | plugin | ゲームごとの認識、ルール、思考、操作をまとめた単位 |
| 盤面認識 | recognition | 画面から盤面の状態を構造化データにする処理 |
| 思考ロジック | strategy | 合法手から1手を選ぶ自作の処理。画面とVLMに依存しない |
| 合法手 | legal move | ルール上、現在の状態で実行できる手 |
| 1手 | move | 1回の判断で実行する操作のまとまり。大戦略SSB2では1部隊の行動 |
| 完走 | completion | 人手の介入なしで1ゲームを終えること。勝敗は問わない |
| 誤操作 | misoperation | 実行した操作の結果が、画面変化の確認で意図と異なると判定された状態 |
| 緊急停止 | emergency stop | 専用キーの操作で入力を止めること |
| 評価セット | evaluation set | 正解ラベル付きの画面の集まり。認識の正答率の計測に使う |
| キャリブレーション | calibration | 画面座標と盤面座標の対応を求める作業 |
| 想定外画面 | unknown screen | プラグインが判別できない画面。操作せずに停止する |
| 禁止画面 | forbidden screen | オンライン対戦など、操作してはいけない画面 |
| 実機 | device | 実際のAndroid端末、またはPCで動くゲーム本体 |

## Kahunaの用語

ルールの正本は、アプリ内のルール説明(`docs/ideas/Kahuna_アプリ内ルール.md` に要約)とする。アプリ内では杖コマを「bridge」と呼ぶ。

| 用語 | コード上の名前 | 定義 |
|---|---|---|
| 島 | island | 盤上の12の場所。カードの種類でもある |
| 点線 | line | 2つの島を結ぶ線。杖コマを置く場所 |
| 杖コマ | stick | 点線に置く細い棒。一般のルールの「橋」にあたる |
| カフナコマ | kahuna | 島の支配を示すコマ。島の点線の過半数を取ると置く |
| 手札 | hand | 自分のカード。上限は5枚 |
| 場札 | market | 表向きの最大3枚のカード |
| 決算 | settlement | 山札と場札が尽きたときの得点計算。全3回 |
| 捨て札 | discard | 使った・捨てたカードを置く場所。決算後の山札は、これを混ぜて作り直す |
| 引かずに終える | pass draw | 手番で引かずに終えること。相手が次の手番で必ず引く |
| 途中終了 | early end | 2・3ラウンド目に杖コマが0本になった者が負けること。アプリ内の説明にはあるが、ご指示により本プロジェクトでは適用しない |

## Hiveの用語

ルールの正本は、アプリ内のルール説明(`docs/ideas/Hive_アプリ内ルール.md` に要約)とする。アプリ内では、カブトムシを「Beetle」、バッタを「Grasshopper」、ダンゴムシを「Pillbug」と呼ぶ。

| 用語 | コード上の名前 | 定義 |
|---|---|---|
| ハイブ | hive | 盤上の駒がつながった集まり。盤は駒のハイブから作る |
| 女王 | queen | 相手に囲まれると負けになる駒。4手目までに置く |
| 囲む | surround | 女王の隣6マスすべてを駒で埋めること |
| ヘックス座標 | `HexCoord` | 軸座標(q, r)で表したマスの位置 |
| スタック | stack | 同じマスに積み重なった駒。下から上の順 |
| ワンハイブ規則 | one hive rule | 駒を動かして、ハイブを2つに割ってはならない規則 |
| 滑り込み | sliding | 駒が隣接する駒の隙間を通って目的地へ動けること。カブトムシとバッタ以外は、滑れる場所にしか動けない |
| ゲート | gate | 2つの駒が作る隙間。滑り込みを阻む |
| 手番の放棄 | pass | 動ける手が無いときの手番の終わらせ方。`Pass` で表す |
| 同時囲み | mutual surround | 両方の女王が同時に囲まれた状態。扱いは未確認 |
| 手持ち | hand | 盤に置いていない駒の数(種類と色ごと) |
| 拡張駒 | expansion piece | 基本の8種以外の駒(てんとう虫、モスキート、ダンゴムシ)。実装は後段 |

## 大戦略SSB2の用語

ルールの正本は `docs/ideas/大戦略SSB2_ルール.pdf` とする。

| 用語 | コード上の名前 | 定義 |
|---|---|---|
| ヘックス | hex | マップを構成する六角形のマス |
| 勢力 | faction | BLUE、RED、GREEN、YELLOWの4つの陣営 |
| 部隊 | unit | ゲームの駒。兵器の集団で、1勢力の上限は50 |
| 兵器 | weapon | 部隊の種類。性能はゲーム内の画面から収集する |
| 武装 | arm | 兵器が攻撃に使う装備 |
| 機数 | count | 部隊の編成数、耐久。0で全滅する |
| 拠点 | base | 首都、都市など占領できる8種類の地形 |
| 首都 | capital | 敵のものをすべて占領すると勝利する拠点 |
| 占領 | capture | 歩兵が拠点の上で待機して自勢力のものにする行動 |
| 収納 | store | 部隊を拠点へ入れる行動 |
| 索敵範囲 | search range | 敵部隊を確認できる範囲。範囲外の敵は見えない |
| 支配エリア | zone of control | 部隊の周囲で、敵の通過を阻む範囲 |
| 遭遇戦 | ambush | 移動中に見えていない敵と接触し、一方的に攻撃を受けること |
| 戦果予測 | battle forecast | 攻撃の決定前に表示される互いの被害の予想 |
| 軍資金 | funds | 生産と補充に使う資源 |
| 保有燃料 | fuel stock | 燃料の補給に使う資源。ターンをまたいで持ち越せない |
| 工業力 | industry | 生産拠点を稼働できる、首都からの距離を決める値 |

## データモデル・アーキテクチャ用語

型定義の詳細は `docs/02`、レイヤー構成は `docs/03` を参照。

| 用語 | 定義 | 実装箇所 |
|---|---|---|
| `Frame` | 取得した1枚の画面 | `src/bglm/core/models.py` |
| `InputAction` | タップ、ドラッグ、キー入力の共通表現 | `src/bglm/core/models.py` |
| `Recognition` | 認識の結果。画面の種類、盤面、信頼度を持つ | `src/bglm/core/models.py` |
| `StepRecord` | 1手の入出力の記録 | `src/bglm/core/models.py` |
| `GamePlugin` | プラグインが実装するインターフェース | `src/bglm/core/protocols.py` |
| `GameIo` | プラグインに渡す入出力の窓口。実行とリプレイで実装を切り替える | `src/bglm/application/game_io.py` |
| `Recognizer` | 画面を読んで `Recognition` を作る | `docs/04` 参照 |
| `Rules` | 合法手の列挙と盤面の予測を行う | `docs/04` 参照 |
| `Strategy` | 合法手から1手を選ぶ | `docs/04` 参照 |
| `MoveExecutor` | 選んだ手を実際の操作として実行する | `docs/04` 参照 |
| `ElementReader` | 1つの要素を読み取る手段の共通インターフェース | `src/bglm/core/protocols.py` |
| `AgentRunner` | ゲームに依存しない実行ループ | `src/bglm/application/runner.py` |
| `SafetyGuard` | 緊急停止と停止条件の判定 | `src/bglm/application/safety.py` |
| `logic` | プラグインのうち、画面に依存しないルールと思考の部分 | `docs/04` 参照 |
| `vision` | プラグインのうち、認識と操作の部分 | `docs/04` 参照 |

## ステータス・状態

| 状態 | 意味 | 遷移 |
|---|---|---|
| `PLAYABLE` | 自分が操作できる | 思考して手を実行する |
| `WAITING` | 相手の手番や演出の待ち | 待機後に取り直す |
| `GAME_OVER` | ゲームが終了した | 結果を記録して終了する |
| `FORBIDDEN` | 操作してはいけない画面 | 直ちに停止する |
| `UNKNOWN` | 想定外の画面 | 操作せず停止する |

実行状態の遷移図は `docs/02` を参照。

## 実行モード

| モード | 意味 |
|---|---|
| `step` | 1手ごとに人の確認を待つ |
| `auto` | 確認なしで連続実行する |

## 略語・技術用語

| 用語 | 正式名称 / 定義 |
|---|---|
| LLM | Large Language Model(大規模言語モデル) |
| VLM | Vision-Language Model(画像を入力できるLLM) |
| LoRA | Low-Rank Adaptation(少ない差分でモデルを追加学習する手法) |
| QLoRA | Quantized LoRA(量子化したモデルで行うLoRA学習) |
| GGUF | llama.cpp系で使う量子化モデルのファイル形式 |
| CNN | Convolutional Neural Network(畳み込みニューラルネットワーク。本書では小型の画像分類器) |
| OCR | Optical Character Recognition(画像から文字を読み取る技術) |
| VRAM | Video RAM(GPUのメモリ) |
| OpenAI互換API | OpenAIの形式に合わせたHTTP API。推論サーバの差し替えに使う |
| テンプレートマッチング | 見本の画像と照合して位置や種類を判定する手法 |
| 射影変換 | 斜めから見た平面を正面から見た形へ補正する座標変換 |
| ADB | Android Debug Bridge(PCからAndroid端末を操作するツール) |
| KPI | Key Performance Indicator(成功指標) |
| MVP | Minimum Viable Product(最初に必要な最小の範囲) |
| SSB2 | 本書では「大戦略SSB2」の略。設定とコード上の識別子は `ssb2` |
