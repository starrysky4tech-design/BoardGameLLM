"""Hive の step_once(scripts/common/step_once.py)への差し込み。

認識は直前の状態を必要とする。対局の最初の1手は、初期状態(空の盤)から始めるので --from-start を付ける。
"""

from typing import Any

from bglm.core.models import Recognition
from bglm.core.protocols import GameIo
from bglm.plugins.hive.logic.models import HiveState, initial_state
from scripts.common.step_once import StepHooks


def observe(plugin: Any, io: GameIo, from_start: bool) -> Recognition[HiveState]:
    previous = initial_state() if from_start else None
    recognition: Recognition[HiveState] = plugin.recognizer().observe(io, previous)
    return recognition


HOOKS = StepHooks(observe=observe)
