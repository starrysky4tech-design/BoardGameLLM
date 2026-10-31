"""Hive のルール。合法手の列挙、手の適用、勝敗(docs/02 の「Rules」、正本は docs/ideas/Hive_アプリ内ルール.md)。

画面にも VLM にも依存しない。ここの期待値はアプリ内の説明から手で作る(テストの出典はそちら)。
"""

from collections.abc import Iterable

from bglm.plugins.hive.logic.models import (
    DIRECTIONS,
    QUEEN_DEADLINE_INDEX,
    Color,
    HexCoord,
    HiveMove,
    HiveState,
    Kind,
    Move,
    Pass,
    Piece,
    Place,
    opponent,
)


def hive_connected(cells: frozenset[HexCoord]) -> bool:
    """駒の集まりが1つにつながっているか(ワンハイブ規則)。空は連結とみなす。"""
    if not cells:
        return True
    start = next(iter(cells))
    seen = {start}
    stack = [start]
    while stack:
        cur = stack.pop()
        for n in cur.neighbors():
            if n in cells and n not in seen:
                seen.add(n)
                stack.append(n)
    return len(seen) == len(cells)


def can_slide(base: frozenset[HexCoord], frm: HexCoord, to: HexCoord) -> bool:
    """隣へ滑り込めるか。2つの共通の隣のうち、ちょうど1つが駒で埋まっていること。

    両方が埋まっていれば門(ゲート)で阻まれる(Tutorial 11/12)。両方が空いていれば、
    駒が盤から離れて滑れない(実機で確かめた。黒のクイーンの左上への移動は候補に出なかった)。
    """
    shared = [n for n in frm.neighbors() if n in to.neighbors()]
    return sum(1 for n in shared if n in base) == 1


class HiveRules:
    def legal_moves(self, state: HiveState) -> list[HiveMove]:
        if self.is_terminal(state):
            return []
        moves: list[HiveMove] = [*self._placements(state), *self._movements(state)]
        return moves or [Pass()]

    def apply(self, state: HiveState, move: HiveMove) -> HiveState:
        color = state.to_move
        stacks = dict(state.stacks)
        hand = dict(state.hand)
        match move:
            case Place(kind=kind, to=to):
                hand[(color, kind)] = hand[(color, kind)] - 1
                stacks[to] = stacks.get(to, ()) + (Piece(color, kind),)
            case Move(frm=frm, to=to):
                stack = stacks[frm]
                piece = stack[-1]
                if len(stack) == 1:
                    del stacks[frm]
                else:
                    stacks[frm] = stack[:-1]
                stacks[to] = stacks.get(to, ()) + (piece,)
            case Pass():
                pass
        return HiveState(
            stacks=stacks,
            hand=hand,
            to_move=opponent(color),
            turn=state.turn + 1,
        )

    def is_terminal(self, state: HiveState) -> bool:
        return _surrounded(state, Color.WHITE) or _surrounded(state, Color.BLACK)

    def outcome(self, state: HiveState) -> str | None:
        """to_move の視点の結果。囲まれたのは to_move 側(相手の手で囲まれた)なので "lose"。両方囲まれたら "draw"(既定値。未確認)。"""
        if not self.is_terminal(state):
            return None
        white = _surrounded(state, Color.WHITE)
        black = _surrounded(state, Color.BLACK)
        if white and black:
            return "draw"
        lost = Color.WHITE if white else Color.BLACK
        return "lose" if state.to_move is lost else "win"

    def diff(self, predicted: HiveState, actual: HiveState) -> dict[str, object]:
        pairs = {
            "stacks": (predicted.stacks, actual.stacks),
            "hand": (predicted.hand, actual.hand),
            "to_move": (predicted.to_move, actual.to_move),
            "turn": (predicted.turn, actual.turn),
        }
        return {name: {"predicted": p, "actual": a} for name, (p, a) in pairs.items() if p != a}

    # 配置

    def _placements(self, state: HiveState) -> list[Place]:
        color = state.to_move
        if (
            state.remaining(color, Kind.QUEEN) > 0
            and state.own_turn_index() >= QUEEN_DEADLINE_INDEX
        ):
            kinds: Iterable[Kind] = (Kind.QUEEN,)
        else:
            kinds = (k for k in Kind if state.remaining(color, k) > 0)
        spots = _placement_spots(state, color)
        return [Place(kind, at) for kind in kinds for at in spots]

    # 移動

    def _movements(self, state: HiveState) -> list[Move]:
        color = state.to_move
        if state.remaining(color, Kind.QUEEN) > 0:
            return []  # 女王を置くまで駒を動かせない(Tutorial 4/12)
        occupied = state.occupied()
        moves: list[Move] = []
        for at, stack in state.stacks.items():
            top = stack[-1]
            if top.color is not color:
                continue
            # ワンハイブ: 動かす駒を取り除いた残りが1つにつながっていること(動いた先とのつながりは見ない)。
            # 実機で確かめた。動かすとクイーンが切り離される駒は、動けないと表示された
            remainder = occupied if len(stack) > 1 else occupied - {at}
            if not hive_connected(remainder):
                continue
            remaining = frozenset(remainder)
            for to in _destinations(occupied, stack, at, top):
                if to in remaining or any(n in remaining for n in to.neighbors()):
                    moves.append(Move(at, to))  # 移動先が残りの駒に触れている(ハイブから離れない)
        return moves


def _placement_spots(state: HiveState, color: Color) -> list[HexCoord]:
    occupied = state.occupied()
    if not occupied:
        return [HexCoord(0, 0)]  # 先手の1手目は盤の中央
    own = [at for at, stack in state.stacks.items() if any(p.color is color for p in stack)]
    if not own:
        # 後手の1手目は、先手の駒の隣に置く(Tutorial 2/12)。相手の隣を避ける規則はまだ適用しない
        return sorted({n for at in occupied for n in at.neighbors() if n not in occupied})
    spots = {n for at in own for n in at.neighbors() if n not in occupied}
    return sorted(at for at in spots if _touches_only(state, at, color))


def _touches_only(state: HiveState, at: HexCoord, color: Color) -> bool:
    """隣の駒が、すべて color の駒か(相手の隣に置けない。Tutorial 3/12)。"""
    tops = (state.top(n) for n in at.neighbors())
    return all(top is None or top.color is color for top in tops)


def _occupied_after(
    occupied: frozenset[HexCoord], stack: tuple[Piece, ...], frm: HexCoord, to: HexCoord
) -> frozenset[HexCoord]:
    after = set(occupied)
    if len(stack) == 1:
        after.discard(frm)
    after.add(to)
    return frozenset(after)


def _destinations(
    occupied: frozenset[HexCoord], stack: tuple[Piece, ...], at: HexCoord, piece: Piece
) -> list[HexCoord]:
    if piece.kind is Kind.BEETLE:
        # カブトムシは滑り込みの規則を受けず、隣へ動ける。駒の上にも乗れる(Tutorial 7/12、11/12)
        return list(at.neighbors())
    if len(stack) > 1:
        return []  # 駒の下にある駒は動けない(Tutorial 7/12)
    base = occupied - {at}  # 動かす駒を持ち上げた後の盤
    empty_targets: list[HexCoord]
    match piece.kind:
        case Kind.QUEEN:
            empty_targets = [n for n in at.neighbors() if n not in base and can_slide(base, at, n)]
        case Kind.ANT:
            empty_targets = _slide_reach(base, at)
        case Kind.SPIDER:
            empty_targets = _spider_steps(base, at)
        case Kind.GRASSHOPPER:
            empty_targets = _grasshopper_jumps(base, at)
        case _:
            empty_targets = []
    return [t for t in empty_targets if t not in base]


def _slide_reach(base: frozenset[HexCoord], start: HexCoord) -> list[HexCoord]:
    """ハイブの縁を滑って到達できるマス(アリ)。通るマスは駒の隣に限る(盤が無限なので、縁に沿って探す)。"""
    seen = {start}
    frontier = [start]
    reached: list[HexCoord] = []
    while frontier:
        cur = frontier.pop()
        for n in cur.neighbors():
            if n in seen or n in base or not can_slide(base, cur, n):
                continue
            if not any(m in base for m in n.neighbors()):
                continue
            seen.add(n)
            reached.append(n)
            frontier.append(n)
    return reached


def _spider_steps(base: frozenset[HexCoord], start: HexCoord) -> list[HexCoord]:
    """ちょうど3マス、同じマスを通らず(戻らず)に滑るマス(クモ。Tutorial 9/12)。"""
    ends: set[HexCoord] = set()

    def walk(cur: HexCoord, path: set[HexCoord], depth: int) -> None:
        if depth == 3:
            ends.add(cur)
            return
        for n in cur.neighbors():
            if n in path or n in base or not can_slide(base, cur, n):
                continue
            walk(n, path | {n}, depth + 1)

    walk(start, {start}, 0)
    return sorted(ends)


def _grasshopper_jumps(base: frozenset[HexCoord], start: HexCoord) -> list[HexCoord]:
    """直線上の駒を1つ以上越えて、最初の空きマスへ跳ぶ(バッタ。Tutorial 8/12)。"""
    landings: list[HexCoord] = []
    for dq, dr in DIRECTIONS:
        step = HexCoord(dq, dr)
        cur = start + step
        if cur not in base:
            continue  # 隣が空きなら跳べない
        while cur in base:
            cur = cur + step
        landings.append(cur)
    return landings


def _surrounded(state: HiveState, color: Color) -> bool:
    at = state.queen_at(color)
    if at is None:
        return False
    return all(n in state.stacks for n in at.neighbors())
