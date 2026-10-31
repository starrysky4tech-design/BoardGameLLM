# CLAUDE.md — BoardGameLLM

ローカルPCで複数のターン制ボードゲーム(Kahuna、大戦略SSB2)を自動プレイする、プラグイン式ゲームエージェント。
開発プロセスの共通指針は上位の `e:\Workspace\repository\CLAUDE.md` に従う。本書はこのプロジェクト固有の事項だけを書く。

## ファイル管理

- 編集・削除してよいのは **`e:\Workspace\repository\LLMProject\BoardGameLLM\` 配下のみ**。
  隣の `BoardGameAI`、`MathSolver` は参照のみで、変更しない
- `datasets/`、`runs/`、`assets/`、`models/`、`cache/`、`apk/` の中身はGit管理外。ゲーム画面やAPKをコミットしない
- `docs/ideas/*.pdf`(大戦略SSB2のルールブック)は複製禁止の記載があるためコミットしない

## 永続ドキュメント

| 知りたいこと | 読む場所 |
|---|---|
| 要件、KPI、優先度、前提と未確定事項 | `docs/01_PRODUCT-REQUIREMENTS.md` |
| データモデル、コンポーネントの責務、アルゴリズム | `docs/02_FUNCTIONAL-DESIGN.md` |
| 技術スタック、レイヤー、資源の配分 | `docs/03_ARCHITECTURE-DESIGN.md` |
| ファイル配置、依存ルール、実装ファイル一覧 | `docs/04_REPOSITORY-STRUCTURE.md` |
| 規約、検証コマンド、テスト戦略 | `docs/05_DEVELOPMENT-GUIDELINES.md` |
| 用語 | `docs/06_GLOSSARY.md` |
| 実機で確かめた事実 | `.steering/20261030-phase0-feasibility/RESULT.md` |

検証コマンドは `docs/05` の先頭にある。コミット前に `.\scripts\check.ps1` を実行する。

## 守ること

- **推測で操作しない**: 認識の信頼度が足りない、想定外の画面、禁止画面のときは入力を送らず止める。読み取りの失敗を既定値で埋めない
- **`logic` は画面に依存しない**: `plugins/<game>/logic/` から `vision`、`toolkit`、OpenCV、VLM、`infrastructure` を import しない。`application` から `plugins` を import しない(動的読み込みのみ)。`import-linter` で検証する
- **ルールの期待値は実装から作らない**: Kahuna はルールページ、大戦略SSB2はルールブックの記述から手で作り、出典(ページ)を書く
- **画面の配置は操作して確かめてから書く**: 1枚の画像から推測して `docs/` に書かない
- **ユーザーのアカウントに影響する操作は事前に確認する**: 対戦を始める、戦績が変わる操作など

## 実機の操作

### Android(Kahuna)

- 端末は SHG11(シリアル `355092380222016`)。**`adb` は必ず `-s <シリアル>` を付けて呼ぶ**。端末の削除・データ消去などの操作はコードに入れない
- 座標は取得画像の座標(回転後)をそのまま `input tap` に渡す。端末を変えたら最初の1タップで座標系を確かめる
- アプリを離れるときは HOME キーを使う。`am force-stop` は保存を壊す

### PC(大戦略SSB2)

- ウィンドウは題名が「大戦略SSB2」と**完全一致**するもので特定する(VS Codeなど、題名に含むだけのウィンドウを除く)
- 画面取得は PrintWindow を使う。mss はゲームが前面のときだけ
- クリックは「移動 → 待機 → 押す → 待機 → 離す」の順に送る。即時のクリックは無視される
- 入力は、ゲームを前面に出せたときだけ送る(別のアプリへの誤クリックを防ぐ)
- 評価に使うマップは通常マップの「ハロー・大戦略」。先頭約20個の「シナリオマップ」は別ルール(生産不可・全滅でクリア)

### GPU

- ゲームを起動していなくても約1.17GBが使われ、使えるのは実質約2.9GB。VLM(2B)とゲームは同時に載るが余裕は約570 MiB
- VLM は密な数字の表や重なったカードの数え上げを誤る。数字はテンプレートマッチングかOCRで読み、VLM は切り出した1要素の分類に限る

## 作業の進め方

- 作業計画は `.steering/[YYYYMMDD]-[タスク名]/` に作る(steering スキル)。現在の作業は `.steering/20261030-phase1-kahuna/`
- 数値パラメータの上限・下限を足すときは `docs/05` の「パラメータ境界値の設計」に従う
- 新しいゲームを足すときは `docs/04` の「スケーリング戦略」に従う
