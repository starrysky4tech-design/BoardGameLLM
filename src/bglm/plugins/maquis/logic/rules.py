"""Maquis のルール(確認済みの範囲)。画面にも VLM にも依存しない(docs/04 の logic の規則)。

扱う範囲: 配置(地点と任務の枠)、巡回の出現、行動(確認済みの地点と任務Bの★2つ)、帰還と捕縛(監獄)、
全団員の捕縛による敗北。
**扱わない範囲**(実機で確かめるまで推測で埋めない。`.steering/20261111-phase-maquis/RESULT.md` の「未確認」):
任務の達成と勝敗、士気の下がる条件(ターントラックのオレンジのターンなど)、3地点が埋まったカードの捕縛、
確認していない地点の行動、監獄の団員が戻る条件。このため `outcome` は敗北(全団員の捕縛)しか返さない。

`apply` は決まる部分だけを反映する。配置のたびに出る巡回は、引かれるカードが分からないので反映しない
(`place_patrol` で、観測したカードまたは標本のカードを足す)。
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from bglm.plugins.maquis.logic.board import Board, default_board
from bglm.plugins.maquis.logic.models import (
    EndPhase,
    MaquisMove,
    MaquisState,
    Phase,
    Place,
    Resolve,
    Resources,
)
from bglm.plugins.maquis.logic.patrol import PatrolCard, full_deck, landing

ACTIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "actions.json"
MAX_AGENTS = 5  # 実機で5/5まで確認(アプリ内ルールの「5人目の駒」)


@dataclass(frozen=True)
class Action:
    cost: Mapping[str, int]
    gain: Mapping[str, int]
    recruit: int = 0
    star: int = 0  # 点灯する★の数(任務の枠の行動)
    until: int = 0  # 点灯済みの★がこの数未満の間だけ実行できる(star > 0 のとき)


def load_actions(path: Path = ACTIONS_PATH) -> dict[str, tuple[Action, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        loc: tuple(
            Action(
                dict(a["cost"]),
                dict(a["gain"]),
                int(a.get("recruit", 0)),
                int(a.get("star", 0)),
                int(a.get("until", 0)),
            )
            for a in entries
        )
        for loc, entries in data["actions"].items()
    }


MISSION_INDEX = {"mission_a": 0, "mission_b": 1}


def initial_state() -> MaquisState:
    """新規ゲーム(普通)の開始直後。山札は10枚。"""
    return MaquisState(deck=full_deck())


class MaquisRules:
    def __init__(
        self, board: Board | None = None, actions: dict[str, tuple[Action, ...]] | None = None
    ) -> None:
        self._board = board or default_board()
        self._actions = actions if actions is not None else load_actions()

    # --- 合法手 ---

    def legal_moves(self, state: MaquisState) -> list[MaquisMove]:
        if state.defeated:
            return []
        if state.phase is Phase.PLACEMENT:
            if state.unplaced > 0:
                taken = set(state.agents) | state.patrols  # 巡回のいる地点には置けない(実機で確認)
                # 任務の枠と同じ地点の通常の枠は、同時には使わない。観測(2026-11-15): ポン・デュ・ノールに団員がいる状態で
                # 工場破壊に置くと、ポン・デュ・ノールに巡回が出て、そこの団員が捕縛された。仕組みは未確認なので、
                # 手を減らす側の仮定として、両方に置く手を外す
                shared = {self._board.node_of(a) for a in state.agents if a in self._board.missions}
                shared |= {
                    slot for slot, node in self._board.missions.items() if node in state.agents
                }
                moves: list[MaquisMove] = [
                    Place(loc)
                    for loc in self._board.locations()
                    if loc not in taken and loc not in shared
                ]
                # 任務の枠。巡回のいる地点の枠に置けるかは未確認なので、置けないものとして外す(手を減らす側の仮定)
                moves += [
                    Place(slot)
                    for slot, node in self._board.missions.items()
                    if slot not in taken and node not in state.patrols and node not in state.agents
                ]
                return moves
            return [EndPhase()]
        moves = []
        for loc in state.agents:
            if loc in state.acted:
                continue
            for slot, action in enumerate(self._actions.get(loc, ())):
                if self._affordable(state, loc, action):
                    moves.append(Resolve(loc, slot))
        moves.append(EndPhase())
        return moves

    def _affordable(self, state: MaquisState, loc: str, action: Action) -> bool:
        if not state.resources.can_pay(dict(action.cost)):
            return False
        if action.recruit and state.agents_total + action.recruit > MAX_AGENTS:
            return False
        if action.recruit > state.recruits_left:
            return False
        if state.resources.morale + action.gain.get("morale", 0) < 1:
            return False  # 士気が尽きると壊滅するので、士気を下げる行動は士気1では出さない(保守的な仮定)
        if action.star and state.stars[MISSION_INDEX[loc]] >= action.until:
            return False
        return True

    def _returns(self, state: MaquisState, slot: str) -> bool:
        """団員のいる枠から隠れ家へ戻れるか。任務の枠は、その地点に巡回がいても戻れない(実機で確認)。"""
        node = self._board.node_of(slot)
        return node not in state.patrols and node not in self._board.stranded(state.patrols)

    # --- 状態の遷移 ---

    def apply(self, state: MaquisState, move: MaquisMove) -> MaquisState:
        """手を打った後の予測。配置で出る巡回は含めない(`place_patrol` で足す)。"""
        if isinstance(move, Place):
            return replace(
                state,
                unplaced=state.unplaced - 1,
                agents=tuple(sorted((*state.agents, move.location))),
            )
        if isinstance(move, Resolve):
            return self._resolve(state, move)
        if state.phase is Phase.PLACEMENT:
            return replace(state, phase=Phase.ACTION)
        return self._end_turn(state)

    def place_patrol(self, state: MaquisState, card: PatrolCard) -> MaquisState:
        """配置の後に引かれたカードの巡回を出す。置き先が決まらないカード(3地点とも埋まり)は未確認のため例外にする。"""
        # 任務の枠にいる団員は、その地点への巡回の出現を塞がない(実機で確認: 4局目)
        occupied = (
            frozenset(a for a in state.agents if a not in self._board.missions) | state.patrols
        )
        at = landing(card, occupied)
        if at is None:
            raise ValueError(f"3地点とも埋まったカードの扱いは未確認: {card}")
        deck = state.deck.drawn_from(card, full_deck())
        return replace(state, patrols=state.patrols | {at}, deck=deck)

    def _resolve(self, state: MaquisState, move: Resolve) -> MaquisState:
        action = self._actions[move.location][move.slot]
        resources = state.resources.with_delta(
            {**action.gain} | {k: -v for k, v in action.cost.items()}
        )
        total = state.agents_total + action.recruit
        acted = state.acted | {move.location}
        agents = state.agents
        if self._returns(state, move.location):
            # 経路があれば、行動した団員はただちに帰還する。無ければ地図に残り、ターン終了時に捕縛される
            agents = tuple(a for a in agents if a != move.location)
        stars = state.stars
        if action.star:
            i = MISSION_INDEX[move.location]
            stars = (*stars[:i], stars[i] + action.star, *stars[i + 1 :])  # type: ignore[assignment]
        return replace(
            state,
            resources=resources,
            agents_total=total,
            acted=acted,
            agents=agents,
            stars=stars,
            recruits_left=state.recruits_left - action.recruit,
        )

    def _end_turn(self, state: MaquisState) -> MaquisState:
        """ターンの終了。隠れ家へ戻れない団員は捕縛される。全団員が捕縛されたら敗北(実機で確認)。

        捕縛された団員は監獄に入り、使える団員(`agents_total`)から引かれる(実機で確認: 4人のうち1人が捕縛されると、
        次のターンは `3/3`)。監獄の団員は次のターンも戻らない。巡回は消える。士気の変化は含めない(未確認)。
        """
        captured = sum(1 for loc in state.agents if not self._returns(state, loc))
        defeated = captured >= state.agents_total
        if captured == 1 and state.prisoners >= 1:
            # 監獄は定員1人: 新しい捕縛者が入ると、前の囚人が戻り、使える団員の数は変わらない
            # (実機で2回確認、2026-11-15: ターン6・9。捕縛の無いターンは、囚人は戻らない)。
            # 2人以上が同時に捕縛されたときの扱いは未確認なので、従来どおり(全員が引かれる)にする
            total = state.agents_total
            prisoners = 1
        else:
            total = state.agents_total - captured
            prisoners = state.prisoners + captured
        return replace(
            state,
            turn=state.turn + 1,
            phase=Phase.PLACEMENT,
            agents_total=total,
            unplaced=total,
            prisoners=prisoners,
            agents=(),
            acted=frozenset(),
            patrols=frozenset(),
            defeated=defeated,
        )

    # --- 終局 ---

    def is_terminal(self, state: MaquisState) -> bool:
        return self.outcome(state) is not None

    def outcome(self, state: MaquisState) -> str | None:
        return "lose" if state.defeated else None

    def diff(self, predicted: MaquisState, actual: MaquisState) -> dict[str, Any]:
        """予測と実際の差。巡回と山札は予測に含まれない(配置のたびに出る)ので比べない。"""
        out: dict[str, Any] = {}
        for name in (
            "turn",
            "phase",
            "agents_total",
            "unplaced",
            "prisoners",
            "agents",
            "resources",
        ):
            a, b = getattr(predicted, name), getattr(actual, name)
            if a != b:
                out[name] = {"predicted": _plain(a), "actual": _plain(b)}
        return out


def _plain(value: object) -> object:
    if isinstance(value, Resources):
        return {k: getattr(value, k) for k in value.__dataclass_fields__}
    if isinstance(value, Phase):
        return value.value
    return list(value) if isinstance(value, tuple) else value


__all__ = ["Action", "MaquisRules", "initial_state", "load_actions"]
