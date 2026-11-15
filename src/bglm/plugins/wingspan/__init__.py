"""Wingspan のプラグイン。`create_plugin()` を registry が動的に読み込む。

対局は、カスタムゲーム(人間 1 + AI 1。基本 + スウィフトスタート)。設定の既定は config/wingspan.toml。
**再開のとき、画面から読めない 3 つを環境変数で渡す**(最初の観測で、追跡の初期状態を作るため):
- WINGSPAN_HAND_SIZE: 手札の全部の枚数(ボーナスを含む。必須)
- WINGSPAN_ROUND: ラウンド 1〜4(手番開始のダイアログが出ていれば、画面から読むので不要)
- WINGSPAN_BONUS: ボーナスカードの枚数(既定 1)
"""

import os
import random
from collections.abc import Sequence

from bglm.core.models import TimeBudget, VlmProfile
from bglm.plugins.wingspan.logic.cards import default_table
from bglm.plugins.wingspan.logic.rules import WingspanRules
from bglm.plugins.wingspan.logic.state import Move, WingspanState
from bglm.plugins.wingspan.logic.strategy import WingspanStrategy
from bglm.plugins.wingspan.vision.executor import WingspanExecutor
from bglm.plugins.wingspan.vision.recognizer import Resume, WingspanRecognizer
from bglm.plugins.wingspan.vision.tracker import Tracker


class SupportedStrategy:
    """思考(`WingspanStrategy`)を、実機で実行できる手だけに絞って使う。

    位置を測っていない手(札を払う変換、差し込み、複数の生息地の札など)を選ばないため。
    実行できる手が無ければ、合法手のままの先頭を返す(executor が unsupported で止める)。
    """

    def __init__(self, inner: WingspanStrategy, executor: WingspanExecutor) -> None:
        self._inner = inner
        self._executor = executor

    def choose(self, state: WingspanState, legal: Sequence[Move], budget: TimeBudget) -> Move:
        usable = [m for m in legal if self._executor.supports(state, m)]
        return self._inner.choose(state, usable or list(legal), budget)


def resume_from_env(environ: dict[str, str] | None = None) -> Resume:
    env = os.environ if environ is None else environ

    def number(name: str) -> int | None:
        value = env.get(name)
        return int(value) if value and value.isdigit() else None

    return Resume(
        hand_size=number("WINGSPAN_HAND_SIZE"),
        round_no=number("WINGSPAN_ROUND"),
        bonus_count=number("WINGSPAN_BONUS") or 1,
    )


class WingspanPlugin:
    name = "wingspan"

    def __init__(self, resume: Resume | None = None, seed: int = 0) -> None:
        table = default_table()
        self._rules = WingspanRules(table)
        tracker = Tracker()
        self._recognizer = WingspanRecognizer(
            me=0, table=table, tracker=tracker, resume=resume or resume_from_env()
        )
        self._executor = WingspanExecutor(self._recognizer, table, tracker)
        self._strategy = SupportedStrategy(
            WingspanStrategy(random.Random(seed), self._rules), self._executor
        )

    def recognizer(self) -> WingspanRecognizer:
        return self._recognizer

    def rules(self) -> WingspanRules:
        return self._rules

    def strategy(self) -> SupportedStrategy:
        return self._strategy

    def executor(self) -> WingspanExecutor:
        return self._executor

    def vlm_profile(self) -> VlmProfile | None:
        return None  # VLM は使わない(札名は日本語の OCR、盤は色とテンプレートで読む)


def create_plugin() -> WingspanPlugin:
    return WingspanPlugin()


__all__ = ["WingspanPlugin", "create_plugin", "resume_from_env"]
