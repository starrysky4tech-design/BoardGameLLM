"""保存した実行ログから、認識と思考を再実行する(入力は送らない)。

保存した画像を `ReplayGameIo` で返し、プラグインの認識 → 合法手 → 思考をやり直して、
ログの記録と一致するかを調べる。不具合の再現と、認識・思考を直した後の回帰確認に使う。
"""

import json
from dataclasses import dataclass
from typing import Any

from bglm.application.game_io import ReplayGameIo
from bglm.application.serialization import jsonable, recognition_to_dict
from bglm.core.errors import BglmError
from bglm.core.models import Recognition, StepRecord, TimeBudget, UiKind
from bglm.core.protocols import GamePlugin, RunReader


class ReplayError(BglmError):
    """再実行できない(ログが無い、手の番号が無いなど)。"""


@dataclass(frozen=True)
class ReplayStepResult:
    step: int
    recognition: Recognition[Any]
    recognition_matches: bool  # ログの認識結果と一致したか
    chosen_move: Any | None  # 再実行で選んだ手(保存する形)
    recorded_move: Any | None  # ログの手
    move_matches: bool | None  # 手を選んだ手番だけ。選んでいなければ None

    @property
    def consistent(self) -> bool:
        return self.recognition_matches and self.move_matches is not False


def _normalized(value: Any) -> Any:
    """JSON に書いて読み戻した形にそろえる(タプルとリスト、キーの型の違いを除く)。"""
    return json.loads(json.dumps(jsonable(value), ensure_ascii=False))


class Replayer:
    def __init__(
        self,
        plugin: GamePlugin[Any, Any],
        reader: RunReader,
        think_budget_sec: float = 10.0,
    ) -> None:
        self._plugin = plugin
        self._reader = reader
        self._think_budget_sec = think_budget_sec

    def replay(self, run_id: str, step: int | None = None) -> list[ReplayStepResult]:
        """run_id の全手(step を指定したらその手だけ)を再実行する。"""
        if not self._reader.has_run(run_id):
            raise ReplayError(f"実行ログが無い: {run_id}")
        records = self._reader.steps(run_id)
        if step is not None:
            records = [r for r in records if r.step == step]
            if not records:
                raise ReplayError(f"{run_id} に手 {step} が無い")
        return [self._replay_step(run_id, record) for record in records]

    def _replay_step(self, run_id: str, record: StepRecord) -> ReplayStepResult:
        if not record.frame_paths:
            raise ReplayError(f"手 {record.step} に保存した画像が無い")
        frames = [self._reader.frame(run_id, path) for path in record.frame_paths]
        io = ReplayGameIo(frames)
        recognizer = self._plugin.recognizer()
        recognition = recognizer.observe(io, None)
        recognition_matches = _normalized(recognition_to_dict(recognition)) == record.recognition

        chosen: Any | None = None
        move_matches: bool | None = None
        if recognition.ui.kind is UiKind.PLAYABLE and recognition.state is not None:
            rules = self._plugin.rules()
            legal = rules.legal_moves(recognition.state)
            if legal:
                move = self._plugin.strategy().choose(
                    recognition.state, legal, TimeBudget(self._think_budget_sec)
                )
                chosen = _normalized(move)
                if record.chosen_move is not None:
                    move_matches = chosen == record.chosen_move
        return ReplayStepResult(
            step=record.step,
            recognition=recognition,
            recognition_matches=recognition_matches,
            chosen_move=chosen,
            recorded_move=record.chosen_move,
            move_matches=move_matches,
        )
