# 開発ガイドライン (Development Guidelines)

> **本書が単一情報源とする範囲**: コーディング規約、Git運用、テスト戦略、カバレッジ目標、検証コマンド、パラメータ境界値の方針、レビュー基準、セットアップ手順。
> ファイル配置と命名規則の詳細は `04_REPOSITORY-STRUCTURE.md`、技術スタックは `03_ARCHITECTURE-DESIGN.md` を参照すること。

## 検証コマンド

```powershell
uv sync                         # 依存の導入
uv run ruff check .             # lint
uv run ruff format --check .    # フォーマット確認
uv run mypy                     # 型検査
uv run lint-imports             # レイヤーの依存方向の検証
uv run pytest                   # テスト(実機テストを除く)
uv run pytest --cov=bglm        # カバレッジ付きテスト
uv run pytest -m device         # 実機テスト
.\scripts\check.ps1             # 実機テストを除く上記の一括実行
```

ビルド成果物は配布しないので、ビルドコマンドは無い。

CIは使わない。コミット前に `.\scripts\check.ps1` をローカルで実行する。実機テストは手元でしか実行できず、ゲームの画像を外部サービスへ送らないため。

## コーディング規約

### 型とフォーマット

- Python 3.12。すべての公開関数に型ヒントを付け、`mypy --strict` を通す
- フォーマットは `ruff format`、インデントは4スペース、行長は100
- インターフェースは `abc` ではなく `Protocol` で定義する
- ゲームの状態とモデルは `frozen=True` のデータクラスにする

### 命名規則

ファイル名の規則は `docs/04` に従う。

```python
# 良い例
def legal_moves(state: KahunaState) -> list[KahunaMove]: ...
is_terminal = settlement == MAX_SETTLEMENTS

# 悪い例
def get(s): ...
flag = settlement == 3
```

- 関数は動詞か、値を表す名詞句にする
- Booleanは `is_`、`has_`、`can_` で始める
- ゲームの用語は `docs/06` に合わせる。Kahunaは `stick`(杖コマ)、`kahuna`(カフナコマ)、`line`(点線)とし、`bridge` は使わない

### コメント

- コメントとdocstringは日本語で書く
- 「なぜそうするか」を書く。コードを見れば分かることは書かない
- ルールを実装した箇所には出典を書く。ルールブックのページはマニュアルの印刷ページとする(PDFは見開きなのでPDFのページ番号とは異なる)

```python
# ルールブック p.23: 攻撃手段を持たない相手には支配エリアが発生しない
if not has_arm_against(enemy, unit):
    continue
```

### エラーハンドリング

- 方針の正本は `docs/02` の「エラーハンドリング」
- 予期されるエラーは `core/errors.py` の例外クラスで表す
- 例外を握りつぶさない。自動プレイ中に判断できなければ止める
- **推測で操作を続けない**。読み取りの失敗を既定値で埋めない

```python
# 良い例
if reading.confidence < threshold:
    return Recognition(ui=ui, state=None, confidence=reading.confidence, low_confidence=[name])

# 悪い例
owner = reading.value if reading.confidence >= threshold else "me"
```

### 乱数と時刻

- グローバル乱数を使わない。`random.Random` を引数で受け取る
- 現在時刻と待機は差し替えられる形にする。テストを実時間に依存させないため

### 外部操作

- `adb` は必ずシリアルを指定して呼ぶ(`adb -s <serial>`)。別の端末を操作する事故を防ぐ
- 画面取得とタップ以外の端末操作(アプリの削除、データの消去など)はコードに入れない
- 入力の送信は `InputDriver` に集約し、他の場所から送らない

## パラメータ境界値の設計

数値パラメータの上限と下限を追加、変更するときの原則:

1. **根拠を書く**。根拠が計測前の見込みなら「(仮)」と明記し、計測後に置き換える
2. **設定の読み込み時に検証する**。範囲外は `pydantic` の検証エラーとして起動前に止める
3. **類似のパラメータと単位を揃える**。時間は設定でも内部でも `_ms` か `_sec` を名前に含める
4. **ゲームのルール値は静的データに持つ**。コードに直接書かず、出典を添える

**本プロジェクトでの適用例**:

| パラメータ | 許容範囲 | 根拠 |
|---|---|---|
| 認識の信頼度の閾値 | 0.0〜1.0 | 信頼度の定義域 |
| ステップ上限 | 1以上 | 既定値は `docs/02` |
| 思考時間の上限 | 1秒以上 | `docs/01` の基準以下に設定する |
| 手札の上限 | 5 | Kahunaのルール |
| マップの座標 | 0〜63 | ルールブック p.31 |
| 部隊数の上限 | 50 | ルールブック p.15 |

既定値の一覧は `docs/02` の「既定値」が正本である。

## テスト戦略

### テストの種類

| 種別 | 対象 | 実行タイミング | 目標 |
|---|---|---|---|
| ユニット | `core`、`toolkit`、各プラグインの `logic` | コミット前 | 下記のカバレッジ |
| 統合 | 録画画像を使った実行ループ、リプレイ、評価 | コミット前 | 正常終了と全 `StopReason` の経路 |
| 実機 | `tests/plugins/<game>/device/`。画面取得、入力、キャリブレーション | 実機に関わる変更時 | 接続手段ごとの疎通 |
| 認識の評価 | `bglm eval` | 認識の変更時 | `docs/01` のKPI |
| 実プレイ | `bglm run` | フェーズの完了時 | `docs/01` のKPI |

### カバレッジ目標

| 対象 | 目標(分岐) |
|---|---|
| プラグインの `logic` | 90% |
| `core`、`application`、`toolkit` | 80% |
| `infrastructure`、`vision` | 目標なし(実機テストと評価セットで確認する) |

`pyproject.toml` の設定で強制する。

### ルールのテスト

- 期待値は**実装からではなくルールの出典から**作る。Kahunaはルールページ、大戦略SSB2はルールブックを見て手で書く。実装の出力を貼り付けない
- テスト名か docstring に出典を書く
- 実機の挙動と違うと分かったら、先に再現するテストを追加してから直す
- シミュレータを実装と同じ前提でしか検証しないと、ずれを検出できない。**実プレイのログ**を固定データにして、`Rules.diff` が差異を出さないことも確認する

### 認識のテスト

- 認識の変更時は `bglm eval` の結果を変更前と比較し、下がった要素が無いことを確かめる
- 誤認識を見つけたら、その画面を評価セットへ追加してから直す
- 評価セットはゲーム画面を含むのでGit管理しない。Gitで管理するテストには自作の画像か、小さな合成画像を使う

### テストの書き方

- Given-When-Then の順に書き、1テスト1観点にする
- 正常系、境界値、異常系の順に洗い出す
- 外部(ウィンドウ、adb、VLM)だけを偽物に置き換え、ルールと思考は実物を使う
- 実機が要るテストに `@pytest.mark.device` を付ける

```python
def test_place_stick_taking_majority_removes_opponent_sticks() -> None:
    """ルールページ: 過半数を取ると、その島の相手の杖コマをすべて取り除く。"""
    # Given
    state = build_state(my_sticks=[1, 2], opponent_sticks=[3], hand=["A"])

    # When
    result = rules.apply(state, PlaceStick(card="A", line=4))

    # Then
    assert 3 not in result.sticks
```

命名は `test_<対象>_<条件>_<期待結果>` とする。

## Git運用ルール

### ブランチ戦略

- `main`: 常に `check.ps1` が通る状態
- `feat/<内容>`、`fix/<内容>`、`docs/<内容>`、`refactor/<内容>`: 作業ブランチ

個人開発のためレビュアーは立てず、セルフレビュー後に `main` へマージする。

### コミットメッセージ規約

```text
<type>(<scope>): <日本語の要約>

<本文(必要な場合)>
```

- type: `feat`、`fix`、`docs`、`refactor`、`test`、`chore`
- scope: `kahuna`、`ssb2`、`core`、`vlm`、`cli` など

```text
feat(kahuna): 杖コマの設置と島の支配判定を実装
```

### コミットしてはいけないもの

`docs/04` の「除外設定」に挙げたものはコミットしない。特に、ゲーム画面、APK、ルールブックPDFを含めない。

### マージ前のチェック

- [ ] `.\scripts\check.ps1` が通る
- [ ] 認識を変更したら `bglm eval` が下がっていない
- [ ] 実機に関わる変更なら `pytest -m device` が通る
- [ ] 実装に合わせて `docs/` を更新した

## コードレビュー基準

セルフレビューや `/review-and-report` で次を確認する。

- **要件**: `docs/01` の受け入れ条件を満たしているか
- **安全**: 低信頼度や想定外の状態で操作を送る経路が無いか
- **依存**: `logic` が画面やVLMに依存していないか。プラグインの知識が共通基盤に漏れていないか
- **出典**: ルールの実装に出典があるか。数値の根拠が書かれているか
- **再現性**: 乱数や時刻に依存していないか

指摘には `[必須]`、`[推奨]`、`[提案]`、`[質問]` のいずれかを付ける。

## 開発環境セットアップ

### 必要なツール

| ツール | 用途 | 導入 |
|---|---|---|
| uv | Pythonと依存の管理 | 導入済み |
| adb | Android操作 | Android SDK Platform-Tools(導入済み) |
| scrcpy | 人間の確認用の画面表示 | 導入済み |
| Ollama | VLMサーバ(F8のみ) | 導入済み |

### セットアップ手順

```powershell
# 1. 依存の導入(Python 3.12も uv が取得する)
uv sync

# 2. 端末のシリアルを確認して config/kahuna.toml へ設定する
adb devices -l

# 3. 疎通確認
uv run bglm capture --game kahuna

# 4. キャリブレーション
uv run bglm calibrate --game kahuna
```

### 大戦略SSB2のゲーム内設定

自動プレイの前にオプションで次を設定する。

| 項目 | 設定 | 理由 |
|---|---|---|
| 画面モード、画面サイズ | ウィンドウ、固定サイズ | 座標を安定させる |
| 戦闘シーンの表示 | オフ | 時間短縮 |
| 戦闘後の爆発アニメ表示 | オフ | 時間短縮 |
| 移動演出スキップ | オン | 時間短縮 |
| ヘックス枠表示 | Phase 0 で決める | 認識しやすい設定を選ぶ |

カメラの拡大率と角度は既定のまま変えない。

### ゲームを追加する手順

`docs/04` の「スケーリング戦略」に従う。ルールの出典を先に決め、`logic` のテストから書き始める。
