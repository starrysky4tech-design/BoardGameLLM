"""Log の出来事の列から、位置を追う(画面に依存しない)。

Log には、出目(rolled N)と、止まったマス(landed on X)が、毎回出る。ダブルの振り直しも、相手の複数回の
Roll も、すべて残る。出目から計算した位置が、Log の「landed on」と一致するかを検査して、食い違えば止める。

起点の位置は、呼び出し側が渡す(画面で確認した値)。カードで動いた位置(Advance to X、3 マス戻る)は、
出目では計算できない。「landed on」のマスで合わせ直し、合わせ直した事実を `corrections` に残す。
"""

from dataclasses import dataclass, field

from bglm.plugins.monopoly.logic.board import BOARD, BOARD_SIZE, JAIL_POSITION, SquareKind
from bglm.plugins.monopoly.logic.events import (
    AuctionWon,
    BailPosted,
    DiceRolled,
    LandedOn,
    LogEvent,
    SentToJail,
    UnknownLine,
)
from bglm.plugins.monopoly.logic.models import Player

_POSITIONS_BY_NAME: dict[str, list[int]] = {}
for _sq in BOARD:
    _POSITIONS_BY_NAME.setdefault(_sq.name, []).append(_sq.position)


@dataclass(frozen=True)
class Step:
    player: Player
    total: int  # 出目の合計
    doubles: bool
    expected: int  # 出目から計算した位置
    landed: str | None  # Log の「landed on」のマス(まだ出ていなければ None)
    position: int  # 採用した位置(Log の「landed on」と合わせた後)
    note: str = ""


@dataclass
class Replay:
    positions: dict[Player, int]
    in_jail: set[Player] = field(default_factory=set)
    jail_roll: dict[Player, int] = field(
        default_factory=dict
    )  # 刑務所の中で、動けなかった直近の出目
    jail_fails: dict[Player, int] = field(
        default_factory=dict
    )  # 刑務所の中で、ダブルが出なかった回数(3 回目に出られないと、保釈金を払う)
    go_passes: dict[Player, int] = field(
        default_factory=dict
    )  # GO を通過した(止まった)回数。給与の計算に使う
    before: dict[Player, int] = field(default_factory=dict)  # 直近の Roll の前の位置
    steps: list[Step] = field(default_factory=list)
    corrections: list[str] = field(
        default_factory=list
    )  # 出目の計算と Log が食い違い、Log に合わせた記録
    stopped: str | None = None  # 値があれば、続けられない理由
    unknown_lines: int = 0


def _candidates(name: str) -> list[int]:
    return _POSITIONS_BY_NAME.get(name, [])


def replay_log(
    positions: dict[Player, int],
    events: list[LogEvent],
    in_jail: frozenset[Player] = frozenset(),
    jail_roll: dict[Player, int] | None = None,
    jail_fails: dict[Player, int] | None = None,
) -> Replay:
    """起点の位置から、Log の出来事を順に適用する。

    DiceRolled → 計算した位置を出す。次の LandedOn が、その位置の名前と一致するなら、確定。
    一致しなければ、カード移動などの可能性がある。Log のマスを採用し、corrections に残す。
    Log のマスが盤に複数ある名前(Chance、Community Chest、Income Tax など)は、計算した位置を優先する。
    """
    result = Replay(
        positions=dict(positions),
        in_jail=set(in_jail),
        jail_roll=dict(jail_roll or {}),
        jail_fails=dict(jail_fails or {}),
    )
    pending: Step | None = None
    unreadable = False  # 直前に、読めない行があった(出目の行かもしれない)
    for event in events:
        if isinstance(event, UnknownLine):
            result.unknown_lines += 1
            unreadable = True
            continue
        if isinstance(event, DiceRolled):
            pending = _roll(result, event)
        elif isinstance(event, LandedOn):
            if pending is None:
                # 出目の行が無いまま、止まったマスが出た。カードで動いた(「<マス>へ進む」)ときに出る(実機 2026-11-07:
                # Community Chest で GO へ進んだ)。マスが盤で一意なら、そこへ動いたとして採る。位置が戻れば GO を通過
                # (給与)。取りこぼし(行が消えた)は、Log の重なりの検知(gap)と画面の現金の照合が見つける
                spots = _candidates(event.square)
                current = result.positions[event.player]
                if unreadable:
                    if event.square not in {sq.name for sq in BOARD if sq.position == current}:
                        result.stopped = (
                            f"出目の行が無いまま {event.player.value} が {event.square} に止まった"
                            f"(位置 {current} と合わない。読めない行があった)"
                        )
                    unreadable = False
                    continue
                if len(spots) == 1 and spots[0] != current:
                    if spots[0] < current:
                        result.go_passes[event.player] = result.go_passes.get(event.player, 0) + 1
                    result.positions[event.player] = spots[0]
                    result.corrections.append(
                        f"{event.player.value}: 出目の行が無いまま {event.square}({spots[0]})に止まった"
                        f"(カードの移動とみなした。計算上 {current})"
                    )
                elif event.square not in {sq.name for sq in BOARD if sq.position == current}:
                    result.stopped = (
                        f"出目の行が無いまま {event.player.value} が {event.square} に止まった"
                        f"(位置 {current} と合わない)"
                    )
                continue
            _land(result, pending, event)
            pending = None
            unreadable = False
        elif isinstance(event, AuctionWon) and event.direct:
            _bought(result, event)
            pending = None
        elif isinstance(event, BailPosted):
            _bail(result, event)
            pending = None
        elif isinstance(event, SentToJail):
            result.in_jail.add(event.player)
            result.jail_fails[event.player] = 0
            result.positions[event.player] = JAIL_POSITION
            result.steps.append(
                Step(event.player, 0, False, JAIL_POSITION, None, JAIL_POSITION, "刑務所へ")
            )
            pending = None
    return result


def _bought(result: Replay, event: AuctionWon) -> None:
    """通常の購入(`bought <土地>`)の購入者は、その土地に止まっている。出目の計算と違えば、Log に合わせる。

    カードで動いた(「<土地>へ進む」)とき、Log には移動の行が出ない。位置が戻っていれば、GO を通過している
    (給与 ₼200)。この前提が誤りなら、画面の現金との照合が食い違うので、呼び出し側が止まる。
    """
    spots = _candidates(event.square)
    if len(spots) != 1:
        return
    target, old = spots[0], result.positions[event.winner]
    if target == old:
        return
    if target < old:
        result.go_passes[event.winner] = result.go_passes.get(event.winner, 0) + 1
    result.positions[event.winner] = target
    result.corrections.append(
        f"{event.winner.value}: 購入した {event.square}({target})に合わせた(計算上 {old})"
    )


def _roll(result: Replay, event: DiceRolled) -> Step | None:
    """出目を適用する。刑務所の中の出目は、ダブルでなければ位置を動かさない(出られない)。

    ダブルなら出られて、その出目だけ進む。3 回目の失敗(罰金を払って出る)は、Log の別の行で分かる
    ので、ここでは扱わない(動かさないまま、後の「landed on」で合わせる)。
    """
    if event.player in result.in_jail:
        if not event.doubles:
            result.jail_roll[event.player] = event.total
            result.jail_fails[event.player] = result.jail_fails.get(event.player, 0) + 1
            result.steps.append(
                Step(
                    event.player,
                    event.total,
                    False,
                    JAIL_POSITION,
                    None,
                    JAIL_POSITION,
                    "刑務所の中(動かない)",
                )
            )
            return None
        result.in_jail.discard(event.player)
        result.jail_fails.pop(event.player, None)
        result.positions[event.player] = JAIL_POSITION
    before = result.positions[event.player]
    result.before[event.player] = before
    expected = (before + event.total) % BOARD_SIZE
    if expected < before:  # GO を通過した、または GO に止まった(給与 ₼200)
        result.go_passes[event.player] = result.go_passes.get(event.player, 0) + 1
    step = Step(event.player, event.total, event.doubles, expected, None, expected)
    result.positions[event.player] = expected
    return step


def _land(result: Replay, step: Step, event: LandedOn) -> None:
    """止まったマスを、出目の計算と照合する。続けられない理由は result.stopped に入れる。"""
    if event.player is not step.player:
        result.stopped = (
            f"出目の持ち主 {step.player.value} と、止まった {event.player.value} が違う"
        )
        return
    options = _candidates(event.square)
    if not options:
        result.stopped = f"盤にないマス: {event.square}"
        return
    if step.expected in options:
        done = Step(
            step.player, step.total, step.doubles, step.expected, event.square, step.expected
        )
        result.steps.append(done)
        return
    # 出目の計算と食い違う。カード移動や、出目の取りこぼしがあり得る。Log のマスに合わせる
    adopted = _closest_forward(step.expected, options)
    before = result.before.get(step.player, adopted)
    if (step.expected < before) and not (adopted < before):
        result.go_passes[step.player] -= (
            1  # 計算では GO を通過したが、Log のマスに合わせると通過していない
        )
    elif (adopted < before) and not (step.expected < before):
        result.go_passes[step.player] = result.go_passes.get(step.player, 0) + 1
    note = f"計算 {step.expected}({_name(step.expected)}) と Log の {event.square} が違う"
    result.corrections.append(f"{step.player.value}: {note}")
    result.positions[step.player] = adopted
    result.steps.append(
        Step(step.player, step.total, step.doubles, step.expected, event.square, adopted, note)
    )


def _closest_forward(position: int, options: list[int]) -> int:
    return min(options, key=lambda o: (o - position) % BOARD_SIZE)


def _name(position: int) -> str:
    return BOARD[position].name


def is_card_square(name: str) -> bool:
    return any(
        sq.name == name and sq.kind in (SquareKind.CHANCE, SquareKind.COMMUNITY_CHEST)
        for sq in BOARD
    )


def _bail(result: Replay, event: BailPosted) -> None:
    """保釈の行。直前の動けなかった出目があれば、その出目で刑務所から進む(3 回目に出られなかった手番)。

    実機の Log: 「Dog rolled 8」→「Dog has posted bail.」→ 家賃の行。止まったマスの「landed on」は出ない。
    先に保釈してから出目が出る順(出目の前に罰金を払う)なら、出目の行が後から来て、通常の Roll になる。
    """
    result.in_jail.discard(event.player)
    result.jail_fails.pop(event.player, None)
    total = result.jail_roll.pop(event.player, None)
    if total is None:
        return
    landed = (JAIL_POSITION + total) % BOARD_SIZE
    result.positions[event.player] = landed
    result.steps.append(
        Step(
            event.player,
            total,
            False,
            landed,
            None,
            landed,
            "保釈して、刑務所の中で出た出目だけ進んだ(Log に landed on は出ない)",
        )
    )


class PositionTracker:
    """手番ごとに、新しい Log の出来事だけを渡して、位置・刑務所の状態を引き継ぐ。

    Log は約 34 行しか残らない(実機で確認)ので、毎手番で読み、新しい行を `advance` に渡す。
    食い違い(corrections)、停止(stopped)、読めなかった行は、呼び出し側が確認する。
    """

    def __init__(
        self,
        positions: dict[Player, int],
        in_jail: frozenset[Player] = frozenset(),
        jail_roll: dict[Player, int] | None = None,
        jail_fails: dict[Player, int] | None = None,
    ) -> None:
        self.positions = dict(positions)
        self.in_jail: set[Player] = set(in_jail)
        self.jail_roll: dict[Player, int] = dict(jail_roll or {})
        self.jail_fails: dict[Player, int] = dict(jail_fails or {})

    def advance(self, new_events: list[LogEvent]) -> Replay:
        result = replay_log(
            self.positions, new_events, frozenset(self.in_jail), self.jail_roll, self.jail_fails
        )
        self.positions = dict(result.positions)
        self.in_jail = set(result.in_jail)
        self.jail_roll = dict(result.jail_roll)
        self.jail_fails = dict(result.jail_fails)
        return result


def last_landed_positions(events: list[LogEvent]) -> dict[Player, int]:
    """Log の最後の「landed on <場所>」から、各プレイヤーの位置を求める(起動時の位置の決定用)。

    名前が盤で一意な場所だけ使う(Chance などの複数ある場所は、位置が決まらないので除く)。
    カードで動いた後の位置は、そのカードの後の「landed on」で上書きされる。
    """
    index: dict[str, int | None] = {}
    for i, square in enumerate(BOARD):
        index[square.name] = None if square.name in index else i
    found: dict[Player, int] = {}
    for event in events:
        if isinstance(event, LandedOn) and index.get(event.square) is not None:
            found[event.player] = index[event.square]  # type: ignore[assignment]
    return found
