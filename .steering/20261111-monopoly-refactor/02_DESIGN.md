# 設計書

## アーキテクチャ概要

`vision/` の中に、画面遷移の共通部品のモジュールを 1 つ足す。レイヤーと依存の向きは変えない
(`logic` は `vision` を import しない。`import-linter` の契約はそのまま)。

```
runtime.py ──┐
builder.py ──┤
property_manager.py ──┼──> navigation.py ──> executor.py(Driver、fail、confirm)──> screens.py(BOARD_SCREENS)
holdings.py ──┘              └──> ownership.py(ZOOM_ENTRY、HELP_DISMISS、ZOOM_RETURN)
```

循環を避けるための置き場所:

- 盤の画面名の組 `BOARD_SCREENS` は `screens.py`(画面名の正本。`ownership.py` と `executor.py` からも使える)
- 失敗の結果 `fail` と、確認つきの操作 `confirm` は `executor.py`(`Driver` と同じ場所。`_fail`、`_confirm` を公開の名前にする)
- 座標 `ZOOM_ENTRY`、`HELP_DISMISS`、`ZOOM_RETURN`、詳細画面の Return は、今の `ownership.py` のまま

## コンポーネント設計

### 1. `vision/navigation.py`(新設)

**責務**:
- 盤の通常の画面へ戻る(`return_to_board`)
- 色グループを開き、案内を消し、開いた画面を返す(`open_group`)
- 画面の取得と判別を 1 回で行う(`capture`、`wait_for`)
- 共通の座標と待ち秒を持つ(`NOTICE_OK`、`IMPROVEMENT_TILE_Y`、`OPEN_SEC`、`HELP_SEC`、`RETURN_SEC`)

**インターフェース**:

```python
def capture(driver: Driver) -> tuple[NDArray[np.uint8], str]: ...
def wait_for(driver: Driver, wanted: tuple[str, ...], wait_sec: float = WAIT_SEC) -> tuple[NDArray[np.uint8], str]: ...

def return_to_board(
    driver: Driver,
    *,
    wait_sec: float = RETURN_SEC,
    check_color: bool = False,   # 戻った盤の色が通常でなければ False(色に頼る読み取りの後に使う)
    close_trade: bool = False,   # 取引画面を誤って開いたとき、Cancel → Yes で閉じる(土地の管理だけ)
) -> bool: ...

@dataclass(frozen=True)
class Opened:
    screen: str                  # 開いた画面("zoomed_board" か "improvements"。それ以外は problem が入る)
    image: NDArray[np.uint8]     # 案内を消した後の画像(読み取りに、取り直さず使う)
    problem: str = ""            # 空でなければ失敗の理由

def open_group(driver: Driver, group: str, *, open_sec: float = OPEN_SEC, help_sec: float = HELP_SEC) -> Opened: ...
```

**実装の要点**:
- `return_to_board` は、既存の 4 つの補助関数の上位互換にする。1 周ごとに画面を 1 回取得し、
  盤なら終わり、通知(`ok_dialog`)なら OK、それ以外は Return を押す。試行は 5 回(既存の最大)
- `open_group` は、開いた画面が拡大盤・建設画面のどちらでもなければ、案内のタップを送らない
  (既存の `_open_detail` と `read_all_holdings` は送っていた。想定外の画面には押さない方へ揃える)
- 案内のタップが通知を出したら、OK で閉じて取り直す(既存は `holdings.py` だけが対処していた)
- 速さを変えない: `read_group_houses` は `open_sec`、`help_sec`、`wait_sec` に今の値(0.5 秒)を渡す。
  建設・売却・抵当は今の値(3.0、2.0、2.5 秒)のまま
- 画面の取得は 1 回に約 2 秒かかるので、判別と読み取りに同じ画像を使う(`Opened.image`)

### 2. `builder.py` の `_change_houses`(手順 2)

**責務**:
- 色グループを開き、計画の軒数だけ + または − を押し、Make Changes → Yes で確定して、盤へ戻す

**実装の要点**:
- `build_group(driver, group, plan)` と `property_manager.sell_houses(driver, group, plan)` は、名前と引数を残し、中で呼ぶ
- 違いは引数 `sell` で切り替える: 押す位置(+ / + の左 `MINUS_OFFSET_X`)、順序(入口から遠い順 / 近い順)、
  盤へ戻るときの取引画面の扱い(売却だけ `close_trade=True`)、失敗の文言
- 成功したときの `actions` は、押した + / − のタップの並びに揃える(売却は、今は Make Changes と Yes を返している。
  呼び出し側は `success` と `reason` しか見ていない)

### 3. `executor.py` の `_jail_confirm`(手順 2)

**責務**:
- 刑務所のメニューのボタンを押し、確認(`jail_dialog`)が出るのを待って、Yes を押す

**実装の要点**:
- 前提の画面の確かめ方(Use Card の表示、Post Bail の表示、画面名)は、3 つの関数それぞれに残す
- 確認を待つ回数(4 回)と間隔は、今のまま

## データフロー

### 家を建てる
```
1. build_group → _change_houses(sell=False)
2. 盤の画面を確かめる → navigation.open_group(色グループ)
3. 開いた画面が建設画面でなければ、return_to_board して失敗
4. 計画の軒数だけ + を押す(通知が出たら、OK → return_to_board → 失敗)
5. executor.confirm(Make Changes → Yes)→ return_to_board
```

## エラーハンドリング戦略

### カスタムエラークラス

追加しない。

### エラーハンドリングパターン

今と同じく、失敗は例外にせず `ExecutionResult(success=False, reason=...)` で返す。読み取りは `problems` に理由を足す。
想定外の画面には、入力を送らない。

## テスト戦略

### ユニットテスト
- `navigation.return_to_board`: 盤なら何も押さない / 通知は OK で閉じる / 拡大盤は Return / 色の確認 / 取引画面は指定したときだけ閉じる / 戻れなければ False
- `navigation.open_group`: 拡大盤・建設画面が開く / 想定外の画面では案内を押さない / 案内のタップが通知を出したら閉じる
- 既存のテスト(builder、property_manager、holdings、group_houses、executor、runtime)が通ること。
  挙動を揃えたことで期待値が変わるテストは、理由をテストの docstring に書いて直す

### 統合テスト
- 追加しない(実行ループのテスト `test_runtime.py`、`test_sync.py` が、偽の入出力で経路を通す)

### 実機
- 状態を変えない操作だけ: 画面の判別 → `read_group_houses`(色グループを開いて戻る)→ 盤に戻ったことを確かめる

## 依存ライブラリ

追加しない。

## ディレクトリ構造

```
src/bglm/plugins/monopoly/
├── runtime.py                 # 変更: 盤へ戻る・通知の OK を navigation から
└── vision/
    ├── navigation.py          # 新設
    ├── screens.py             # 変更: BOARD_SCREENS を足す
    ├── executor.py            # 変更: fail、confirm を公開。_jail_confirm
    ├── builder.py             # 変更: _change_houses
    ├── property_manager.py    # 変更: _to_board を削除、sell_houses は builder へ委譲
    ├── holdings.py            # 変更: 盤へ戻る 2 つと、開く処理を navigation へ
    └── ownership.py           # 変更: BOARD_SCREENS を screens から。詳細画面の Return の座標を 1 つに
tests/plugins/monopoly/unit/vision/test_navigation.py   # 新設
docs/04_REPOSITORY-STRUCTURE.md                         # 実装ファイルの一覧に 1 行
```

## 実装の順序

1. 定数と小さな関数の置き場所を決める(`screens.BOARD_SCREENS`、`executor.fail` / `confirm`、`navigation` の座標と待ち秒)
2. `navigation.return_to_board` を作り、6 箇所を置き換える
3. `navigation.open_group` を作り、5 箇所を置き換える
4. `_change_houses`、`_jail_confirm`
5. 検証(check.ps1、実機)、ドキュメント

各段階の後に、Monopoly のテストを実行する。

## セキュリティ考慮事項

- 該当なし(端末への操作の種類は増やさない。`adb` の呼び出しは変えない)

## パフォーマンス考慮事項

- 画面の取得は 1 回約 2 秒。`read_group_houses` の取得回数を増やさない(テストで上限を確かめている)
- 待ち秒は変えない

## 将来の拡張性

黄色など、+ の位置が未登録の色グループを足すときは、`builder.PLUS` に座標を足すだけで、建設と売却の両方に効く。
