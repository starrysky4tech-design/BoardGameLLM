# 設計書

## アーキテクチャ概要

レイヤーと依存の向きは変えない(`import-linter` の契約はそのまま)。3 つのプラグインの `vision/` が個別に持っていた
画像処理と待ちの定型を、既存の共通レイヤー `toolkit/` に 5 モジュール足して集める。

```
plugins/kahuna/vision ──┐
plugins/hive/vision ────┼──> toolkit/{matching, images, waiting, screen, components} ──> core
plugins/monopoly/vision ┘          └─ template_reader も matching を使う

scripts/common/step_once.py ──> application.registry(プラグインの動的読み込み)
        └──(あれば)──> scripts/<game>/step_hooks.py(ゲーム固有の差し込み)
```

- `toolkit` は `core`・NumPy・OpenCV だけに依存する(今と同じ)。ゲームの知識(座標、閾値、画面名)は入れない
- `logic/` は触らない(Kahuna・Hive の `strategy.py`、`rules.py`、`simulation.py`、Monopoly の `logic/` 全部)
- 閾値・座標・待ち秒・試行回数の**値**は変えない。共通部品は値を引数で受ける

## コンポーネント設計

### 1. `toolkit/images.py`(新設。A3 と、画像の小さな定型)

**責務**:
- 画像ファイルを読む(日本語を含むパスでも読める `np.fromfile` + `cv2.imdecode`)
- グレースケールへの変換、領域の切り出し

**インターフェース**:

```python
Box = tuple[int, int, int, int]  # (x0, y0, x1, y1)。toolkit とプラグインで、この並びに揃える

def load_image(path: Path, flags: int = cv2.IMREAD_COLOR) -> NDArray[np.uint8] | None: ...  # 読めなければ None
def gray(image: NDArray[np.uint8]) -> NDArray[np.uint8]: ...                                  # BGR → グレースケール(uint8)
def crop(image: NDArray[np.uint8], box: Box) -> NDArray[np.uint8]: ...                        # image[y0:y1, x0:x1]
```

**実装の要点**:
- 読めないときに何を投げるかは、呼び出し側が決める(Kahuna は `ConfigError`、Monopoly の画面テンプレートは `FileNotFoundError`、
  Monopoly の数字テンプレートは読めないものを飛ばす。今の挙動を保つ)
- `infrastructure/run_logger.py` にも同じ `imdecode` があるが、`infrastructure` は `toolkit` を import できない(`docs/04`)ので、そのまま残す

### 2. `toolkit/matching.py`(新設。A1・A2)

**責務**:
- テンプレートとの正規化相関(`cv2.TM_CCOEFF_NORMED`)の最大値と位置
- 相関の山を、周囲を消しながら高い順に拾う

**インターフェース**:

```python
@dataclass(frozen=True)
class Match:
    score: float
    x: int  # 最大の位置(テンプレートの左上)
    y: int

def correlation(image, template) -> NDArray[np.float32]: ...        # matchTemplate の結果そのもの
def best_match(image, template) -> Match: ...                       # 最大値と位置。テンプレートが画像より大きければ Match(0.0, 0, 0)
def match_score(image, template) -> float: ...                      # best_match(...).score
def find_peaks(result, threshold: float, half_width: int, half_height: int) -> list[Match]: ...
```

**実装の要点**:
- `find_peaks` は、渡された `result` を書き換えない(中でコピーする)。消す範囲は
  `[y - half_height, y + half_height) × [x - half_width, x + half_width)`(Kahuna の `stones._peaks` は 30×30、`cards.read_hand` は 40×20。今の値を渡す)
- `toolkit/template_reader.py` の `TemplateReader.read` も `match_score` を使う
- テンプレートが画像より大きいとき: Monopoly の `screens._score` は 0.0 を返し、Kahuna は OpenCV の例外になっていた。0.0 に揃える
  (例外になっていた経路は、今のテストと録画では通らない)

### 3. `toolkit/waiting.py`(新設。A4)

**責務**:
- 「取得して確かめる。だめなら待って取り直す」を、回数の上限つきで行う

**インターフェース**:

```python
def poll[T](
    probe: Callable[[], T],            # 1 回の取得(画面の取得 + 読み取り)
    accept: Callable[[T], bool],       # 成り立ったか
    *,
    tries: int,                        # probe を呼ぶ回数の上限(1 以上)
    wait_sec: float,
    sleep: Callable[[float], None],
    wait_first: bool = False,          # 各回の probe の前に待つ(押した直後の確認)
    wait_last: bool = False,           # 最後の回が不成立でも、その後に待つ
) -> tuple[T, bool]: ...               # (最後に取った値, 成り立ったか)
```

**実装の要点**:
- 既存のループは、待つ位置が少しずつ違う。`sleep` の回数と順序を変えないよう、2 つの旗で今の並びを再現する

| 置き換える箇所 | tries | wait_first | wait_last |
|---|---|---|---|
| kahuna `executor._wait_until`(確かめる → 待つ、を 4 回) | 4 | False | True |
| kahuna `recognizer.observe`(読む。だめなら待って読む、を 2 回まで) | retries + 1 | False | False |
| hive `executor._verified`(読む → 待つ、を 3 回) | 3 | False | True |
| monopoly `navigation.wait_for`(取る。だめなら待って取る) | WAIT_CAPTURES | False | False |
| monopoly `executor._jail_confirm`(待つ → 確かめる、を 4 回) | 4 | True | False |

- Monopoly の他のループ(`_tap_until`、`confirm`、`roll`、`close_card`、`return_to_board`、`read_cash_stable`)は、
  回ごとに入力を送る・ログを足す・投票するなど中身が違うので、置き換えない

### 4. `toolkit/screen.py`(新設。A5)

**責務**:
- 端末 SHG11 の横向きの取得画像の大きさ(幅 2432、高さ 1080)と、その確認

**インターフェース**:

```python
LANDSCAPE_SIZE = (2432, 1080)  # 幅, 高さ。SHG11 の横向き(Kahuna、Monopoly)
def has_size(image: NDArray[np.uint8], size: tuple[int, int] = LANDSCAPE_SIZE) -> bool: ...
```

**実装の要点**:
- Kahuna と Monopoly の `screens.IMAGE_SIZE` は、`LANDSCAPE_SIZE` の別名として残す(テストとスクリプトが名前を使う)。定義は 1 つ
- Hive(縦向き 1080x2432)は、今は大きさを確かめていない。確認を足すと動作が変わるので、足さない

### 5. `toolkit/components.py`(新設。A6)

**責務**:
- 2 値画像の連結成分を、箱・面積・重心の一覧にする

**インターフェース**:

```python
@dataclass(frozen=True)
class Component:
    label: int
    x: int; y: int; width: int; height: int; area: int
    cx: float; cy: float                                  # 重心

def connected_components(mask: NDArray[np.uint8]) -> tuple[list[Component], NDArray[np.int32]]: ...  # (背景を除く成分, ラベル画像)
def component_mask(labels, component) -> NDArray[np.uint8]: ...  # 成分の箱の中の、その成分の画素(0/1)
```

**実装の要点**:
- 連結は 8 近傍(今の全箇所が 8 近傍。OpenCV の既定も 8)
- 大きさ・面積での絞り込みは、呼び出し側に残す(閾値はゲームの知識)
- Hive の `grid.py` は、重心を `labels` からの平均で求めている。`Component.cx / cy`(OpenCV の重心)と数学的に同じ値だが、
  丸めの差が出ないことを、録画画像の読み取りの比較(下の「回帰の確認」)で確かめる。差が出たら `component_mask` からの平均に戻す

### 6. Kahuna(`plugins/kahuna/vision/`)

**`executor.py`**:
- `_my_turn_view(io, state=None) -> tuple[image, alignment] | ExecutionResult`: 取得 → 位置合わせ → 手番の確認。
  `state` を渡すと「手札 0 枚なら相手の手番の表示でも可」(引く操作・終える操作)。6 つの操作の冒頭を置き換える
- `_has_stick(image, at, owner)`: `_has_own_stick` と `_has_opponent_stick` を 1 つに
- `_best_card(hand, island) -> CardReading | None`: `_select_hand_card` と `_place_stick` の中の選び方を 1 つに
- `_wait_until` は `toolkit.waiting.poll` を呼ぶ 1 行にする
- 操作ごとの取得の回数と順序(押した直後の `_capture` を含む)は変えない

**`screens.py` / `recognizer.py`**:
- `screens.best_dialog(image, roi, names, templates) -> dict[str, float]` を作り、`_dialog_button`(CONTINUE / NEXT)と
  `recognizer._game_over`(勝者の表示)の照合を 1 つにする
- 領域の定数を `(x0, y0, x1, y1)` に揃える(`SIDE_STRIP`、`TIP_STRIP`、`BUTTON_ROI`、`WINNER_ROI`)。
  `screens.HAND_ROI` は `cards.HAND_ROI` と同じ領域の並び違いなので、`cards` の定義を使う(定義は 1 つ)
- 「赤い画素」の判定(`r > 150 & g < 110 & b < 110`)が `screens._banner_present` と `numbers.read_deck` にある。`glyphs.red_mask` に 1 つにする

**その他**:
- `templates._read` → `toolkit.images.load_image`。`cards`、`alignment`、`stones` の照合 → `toolkit.matching`。
  `glyphs.extract_glyphs`、`sticks.find_blobs` の連結成分 → `toolkit.components`。`numbers._crop` → `toolkit.images.crop`

### 7. Hive(`plugins/hive/`)

- **`vision/wide.py`**: `board_clipped` と `_empty_wood_start`(`empty_wood_start` に改名)を `recognizer.py` から移す(寄せる操作の補助なので)。
  `pan_content(io, dx, sleep=time.sleep)`、`wide_read(io, sleep=time.sleep)` にして、`HiveExecutor` は自分の `sleep` を渡す。
  使われていない `measured_offset` は削除する(参照が無いことを `grep` で確かめてから)
- **`vision/wide.py` の `WideBoardRecognizer`**: `__init__.py` の `HiveDebugRecognizer` を移して改名する(盤が画面より広ければ継ぎ合わせて読む)。
  `plugins/hive/__init__.py` は、組み立てと公開だけにする
- **`vision/grid.py`**: `_seed_centres(mask)`(侵食 → 連結成分 → 面積で絞る → 重心)を `_white_centres` と `_fallback_tiles` で共有する。
  `_lattice_spacing(dxs, dys, qs, halves)`(最小二乗の間隔)を `_fit_spacing` と `to_axial` で共有する
- **`vision/recognizer.py`**: `_tops_of` を `tops_of` として公開し、`executor._geometry` の同じ処理を置き換える。
  `_hidden_ground` の連結成分 → `toolkit.components`
- **`vision/executor.py`**: `_verified` → `toolkit.waiting.poll`
- import の向き: `recognizer` ← `stitch` ← `wide` ← `executor`、`__init__`。循環しない(`recognizer` は `wide` を import しない)

### 8. Monopoly(`plugins/monopoly/vision/`。置き換えだけ)

| ファイル | 置き換え |
|---|---|
| `screens.py` | `_template` → `images.load_image`(無ければ `FileNotFoundError` のまま)、`_score` → `matching.match_score`、大きさの確認 5 箇所 → `screen.has_size` |
| `cash.py` | `_load` → `images.load_image`、`_components` → `components.connected_components` |
| `bars.py`(3 箇所)、`dice.py`、`board_scan.py` | 連結成分 → `components.connected_components` |
| `navigation.py` | `wait_for` → `waiting.poll` |
| `executor.py` | `_jail_confirm` の待ち → `waiting.poll` |

`runtime.py`、`sync.py`、`logic/` は触らない。

### 9. スクリプト(A7)

- `scripts/common/step_once.py --game <名前> [--execute] [--from-start]`: 設定の読み込み → 端末 → プラグイン(`application.registry`)→
  認識 → 合法手 → 思考 → 表示 →(`--execute` のときだけ)実行
- ゲーム固有の差し込みは `scripts/<game>/step_hooks.py`(あれば読み込む)に置く

```python
# scripts/common/step_once.py
@dataclass(frozen=True)
class StepHooks:
    observe: Callable[[Any, GameIo, bool], Recognition[Any]] | None = None   # (plugin, io, from_start) → 認識。None なら plugin.recognizer().observe(io, None)
    after: Callable[[Any, Any], None] | None = None                          # (state, move)。実行が成功した後
```

- `scripts/kahuna/step_hooks.py`: 今の `_read`(入力を送らない `recognize`、引く操作が残っている印 `runs/kahuna/pending_draw`)と、印の更新
- `scripts/hive/step_hooks.py`: `--from-start` のとき、直前の状態を初期状態にして `observe` する
- `scripts/kahuna/step_once.py`、`scripts/hive/step_once.py` は削除する。
  `scripts/kahuna/record_session.py`(`scripts/common/record_session.py` を呼ぶだけ)も削除する

## データフロー

### Kahuna の 1 操作(例: 杖コマを置く)
```
1. _my_turn_view(io): 取得 → aligned_view → classify_screen。違えば ExecutionResult(False, 理由)
2. read_hand → _best_card。無ければ失敗
3. カードをタップ → 点線をタップ
4. poll(取得 + 位置合わせ, 自分の杖があるか, tries=4, wait_last=True)
```

### Hive の 1 操作
```
1. wide_read(io, sleep): 中央・左・右を取り、継ぎ合わせる
2. _geometry: recognizer.tops_of(state) と読み取りを、平行移動で合わせる
3. 見えない点があれば pan_content(io, dx, sleep) して 1 へ(上限 4 回)
4. タップ → poll(wide_read + recognize_reading, 予測と一致か, tries=3, wait_last=True)
```

## エラーハンドリング戦略

### カスタムエラークラス

追加しない。

### エラーハンドリングパターン

今と同じ。操作の失敗は `ExecutionResult(success=False, reason=...)`、読めない認識は `state=None` と `low_confidence`。
共通部品は推測で値を埋めない(`load_image` は `None`、`poll` は成否を返す)。

## テスト戦略

### ユニットテスト(`tests/common/unit/toolkit/`。合成画像)
- `test_images.py`: 日本語を含むパスの読み込み / 無いファイルは `None` / `gray` の型と形 / `crop` の範囲
- `test_matching.py`: 埋め込んだテンプレートの位置と相関 / テンプレートが大きいときは 0.0 / `find_peaks` が離れた 2 つを拾い、近い重複を 1 つにする / 閾値未満は拾わない / 入力を書き換えない
- `test_waiting.py`: 1 回目で成立(待たない)/ 途中で成立 / 最後まで不成立 / `wait_first`・`wait_last` ごとの `sleep` の回数と順序 / `tries < 1` は `ValueError`
- `test_screen.py`: 一致 / 縦横が逆 / 別の大きさ
- `test_components.py`: 離れた 2 つの成分の箱・面積・重心 / 8 近傍(斜めはつながる)/ 空の画像 / `component_mask`
- 既存のテストは、期待値を変えない。変えてよいのは import の場所(`board_clipped` を `wide` から、など)だけ

### 回帰の確認(作業用。`scratchpad` に置き、コミットしない)
- **認識の出力の比較**: 手元の録画・記録画像(`datasets/`、`runs/`)の全部に対して、変更の前後で次を JSON に書き出し、差が無いことを確かめる
  - Kahuna: `KahunaRecognizer.recognize(image)` の画面名・状態・信頼度・`low_confidence`
  - Hive: `read_board(image)` の `tops`・`problems`・信頼度、`find_tiles` の中心(小数 6 桁)
  - Monopoly: `classify`、`read_cash`、`scan_board`、`find_pips`
- **自己対戦**: Kahuna `play_game`(種 0〜19)、Hive `play_game`(種 0〜4、深さ 2)、Monopoly `evaluate_strategy --games 150 --seed 7` の結果が、変更の前後で一致する
  (`logic/` を触らないことの確認)

### 統合テスト
- 追加しない(Kahuna の `test_kahuna_dry_run_and_replay.py`、Monopoly の `test_runtime.py`・`test_sync.py` が経路を通す)

### 実機
- 行わない(USB が切れて保留中)。次に動かすときの最初の確認として、振り返りに申し送る

## 依存ライブラリ

追加しない。

## ディレクトリ構造

```
src/bglm/toolkit/
├── images.py            # 新設
├── matching.py          # 新設
├── waiting.py           # 新設
├── screen.py            # 新設
├── components.py        # 新設
└── template_reader.py   # 変更: matching を使う
src/bglm/plugins/kahuna/vision/   # 変更: executor、recognizer、screens、cards、numbers、glyphs、alignment、sticks、stones、templates
src/bglm/plugins/hive/
├── __init__.py          # 変更: 組み立てと公開だけ
└── vision/              # 変更: wide(board_clipped、empty_wood_start、WideBoardRecognizer)、recognizer、executor、grid
src/bglm/plugins/monopoly/vision/ # 変更: screens、cash、bars、dice、board_scan、navigation、executor(置き換えだけ)
scripts/
├── common/step_once.py  # 新設
├── kahuna/step_hooks.py # 新設(step_once.py、record_session.py は削除)
└── hive/step_hooks.py   # 新設(step_once.py は削除)
tests/common/unit/toolkit/{test_images,test_matching,test_waiting,test_screen,test_components}.py  # 新設
docs/04_REPOSITORY-STRUCTURE.md   # 実装ファイル一覧(toolkit の 5 行、Hive の行、scripts)
```

## 実装の順序

1. 基準を取る(テストの通過数、認識の出力、自己対戦)
2. `toolkit` の 5 モジュールとテスト
3. Kahuna を置き換える → Kahuna のテストと、認識の出力の比較
4. Hive を置き換える → 同上
5. Monopoly を置き換える → 同上
6. スクリプト
7. 全体の検証(ruff、mypy、lint-imports、pytest、自己対戦)、`docs/04`、振り返り

各段階の後に、そのゲームのテストを実行する。1 つのゲームで差が出たら、次へ進まず原因を直す。

## セキュリティ考慮事項

- 該当なし(端末への操作の種類は増やさない。`adb` の呼び出しは変えない)

## パフォーマンス考慮事項

- 共通部品は、今の OpenCV の呼び出しを包むだけで、計算は増やさない。`find_peaks` のコピーは 1 回(盤の領域の大きさの `float32`)
- `sleep` の回数と秒は変えない(`poll` の旗で再現する)
- Hive の `pan_content` に `sleep` を注入すると、偽の入出力のテストが実時間(1 回 1.5 秒)を待たなくなる

## 将来の拡張性

大戦略SSB2 のプラグインを作るとき、テンプレート照合・連結成分・待ちは `toolkit` から使える。
PC の画面の大きさは、`toolkit/screen.py` に定数を足す。
