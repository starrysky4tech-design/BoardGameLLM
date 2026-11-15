"""「取得して確かめる。だめなら待って取り直す」の定型。

画面の表示は少し遅れて変わる(アニメーション、Android の描画の遅れ)。取得の回数と待ちの秒は、
ゲームごとに実機で決めた値を呼び出し側が渡す。`sleep` は差し替えられる(テストを実時間に依存させないため)。
"""

from collections.abc import Callable


def poll[T](
    probe: Callable[[], T],
    accept: Callable[[T], bool],
    *,
    tries: int,
    wait_sec: float,
    sleep: Callable[[float], None],
    wait_first: bool = False,
    wait_last: bool = False,
) -> tuple[T, bool]:
    """probe を最大 tries 回呼び、accept が成り立った時点で返す。返り値は (最後に取った値, 成り立ったか)。

    - 回と回の間に wait_sec 待つ
    - wait_first: 各回の probe の前に待つ(押した直後に確かめる場合。1 回目の前も待つ)
    - wait_last: 最後の回が成り立たなくても、その後に待つ(呼び出し側が続けて取得する場合の、今までの待ち方)
    """
    if tries < 1:
        raise ValueError(f"tries は1以上: {tries}")
    for attempt in range(tries):
        if wait_first:
            sleep(wait_sec)
        value = probe()
        if accept(value):
            return value, True
        is_last = attempt == tries - 1
        if not wait_first and (not is_last or wait_last):
            sleep(wait_sec)
    return value, False
