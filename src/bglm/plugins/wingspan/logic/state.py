"""ゲームの状態と、手番の途中の「いま答える決定」(Task)、手(Move)の定義。

手番は「行動を選ぶ → 餌・卵・札を選ぶ → 鳥の能力を 1 羽ずつ使うか決める」という決定の列で進む(アプリと同じ順)。
状態の `queue` の先頭が、いま答える決定。空なら「行動を選ぶ」。
"""

from dataclasses import dataclass, field, replace

from bglm.plugins.wingspan.logic.goals import GoalMode, GoalTile
from bglm.plugins.wingspan.logic.models import Food, Habitat, Placement, PlayerBoard

# ---- 手番の途中の決定(Task) ----


@dataclass(frozen=True)
class GainFoodTask:
    """餌箱のダイスを remaining 個取る。convert なら、取り終えた後に札 1 枚を捨てて 1 個足せる。"""

    remaining: int
    convert: bool = False


@dataclass(frozen=True)
class ConvertFoodTask:
    """手札 1 枚を捨てて、餌箱からもう 1 個取るか(R p.7)。"""


@dataclass(frozen=True)
class LayEggsTask:
    """卵を remaining 個、鳥に置く。置けなければ残りは失う(R p.8)。bonus なら、餌 1 個で 1 個足せる。

    where が None なら任意の鳥、Placement ならその 1 羽だけ(能力用)。
    """

    remaining: int
    bonus: bool = False
    where: Placement | None = None


@dataclass(frozen=True)
class EggBonusTask:
    """餌 1 個を払って卵をもう 1 個置くか(R p.8)。"""


@dataclass(frozen=True)
class DrawTask:
    """トレイか山札から札を remaining 枚引く。bonus なら、卵 1 個を捨てて 1 枚足せる(R p.9)。"""

    remaining: int
    bonus: bool = False


@dataclass(frozen=True)
class DrawBonusTask:
    """卵 1 個を捨てて札をもう 1 枚引くか(R p.9)。"""


@dataclass(frozen=True)
class PowersTask:
    """その行の茶色の能力を、右から左へ 1 羽ずつ使うか決める(R p.4)。next_index は次に見る鳥の位置。

    played=True は、いまプレイした鳥 1 羽の「プレイ時」の能力(白)だけを扱う(R p.6)。
    """

    habitat: Habitat
    next_index: int
    played: bool = False


@dataclass(frozen=True)
class TuckTask:
    """手札から 1 枚を鳥の下に差し込むか(差し込めば 1 点)。差し込んだら続きの効果を得る。"""

    at: Placement
    then_draw: int = 0
    then_food: Food | None = None
    then_lay: int = 0


@dataclass(frozen=True)
class SetupTask:
    """ゲームの初期選択(鳥と餌を合わせて 5 つ、ボーナス 1 枚。R p.2)。"""


Task = (
    GainFoodTask
    | ConvertFoodTask
    | LayEggsTask
    | EggBonusTask
    | DrawTask
    | DrawBonusTask
    | PowersTask
    | TuckTask
    | SetupTask
)

# ---- 手(Move) ----


@dataclass(frozen=True)
class PlayBird:
    """鳥をプレイする。札・生息地・払う餌・払う卵(どの鳥から)を 1 つの手にまとめる(アプリの複数操作は executor が展開)。"""

    card: str
    habitat: Habitat
    spend: tuple[int, int, int, int, int]
    egg_from: tuple[Placement, ...] = ()


@dataclass(frozen=True)
class GainFood:
    """餌の行動(森林)を選ぶ。"""


@dataclass(frozen=True)
class LayEggs:
    """産卵の行動(草原)を選ぶ。"""


@dataclass(frozen=True)
class DrawCards:
    """札を引く行動(湿地)を選ぶ。"""


@dataclass(frozen=True)
class TakeDie:
    """餌箱のダイスを 1 個取る。index は餌箱の並びの位置、food は得る餌(2 種の目のときは選ぶ)。"""

    index: int
    food: Food


@dataclass(frozen=True)
class Reroll:
    """餌箱の 5 個を振り直す(残りが全部同じ目のとき。R p.7)。"""


@dataclass(frozen=True)
class ConvertCard:
    """手札の札を 1 枚捨てて、餌をもう 1 個取る。"""

    card: str


@dataclass(frozen=True)
class LayEgg:
    at: Placement


@dataclass(frozen=True)
class PayFoodForEgg:
    """餌 1 個(food)を払って卵をもう 1 個置く。"""

    food: Food


@dataclass(frozen=True)
class TakeTray:
    index: int


@dataclass(frozen=True)
class TakeDeck:
    pass


@dataclass(frozen=True)
class PayEggForCard:
    """卵 1 個(at の鳥から)を捨てて札をもう 1 枚引く。"""

    at: Placement


@dataclass(frozen=True)
class Decline:
    """任意の変換や効果を使わない。"""


@dataclass(frozen=True)
class UsePower:
    pass


@dataclass(frozen=True)
class SkipPower:
    pass


@dataclass(frozen=True)
class TuckCard:
    card: str


@dataclass(frozen=True)
class KeepSetup:
    """初期選択: 残す鳥、残す餌、残すボーナス。鳥の数 + 餌の数 = 5(R p.2)。"""

    birds: tuple[str, ...]
    foods: tuple[Food, ...]
    bonus: str


@dataclass(frozen=True)
class AckTurnStart:
    """「タップして手番を開始する。」のダイアログを閉じる(相手の手番の結果の案内も出る。RESULT.md §12)。"""


@dataclass(frozen=True)
class AckConfirm:
    """アプリが確認を求める能力の案内(実装済みの無料の獲得など)を、確定ボタンで受ける。"""


@dataclass(frozen=True)
class AckSkip:
    """未実装の能力の案内を、スキップする(能力はすべて任意。R p.10)。"""


@dataclass(frozen=True)
class AckMatView:
    """生息地の表示(新しい対局の始まりの既定)を、全体ボードの表示に切り替える。実行する手は全体ボードの座標を前提にする。"""


@dataclass(frozen=True)
class AckRound:
    """ラウンドの採点の画面を、確定ボタンで進める。"""


Move = (
    PlayBird
    | GainFood
    | LayEggs
    | DrawCards
    | TakeDie
    | Reroll
    | ConvertCard
    | LayEgg
    | PayFoodForEgg
    | TakeTray
    | TakeDeck
    | PayEggForCard
    | Decline
    | UsePower
    | SkipPower
    | TuckCard
    | KeepSetup
    | AckTurnStart
    | AckConfirm
    | AckSkip
    | AckRound
    | AckMatView
)

# ---- 状態 ----


@dataclass(frozen=True)
class WingspanState:
    players: tuple[PlayerBoard, ...]
    to_move: int
    first_player: int
    round_index: int  # 0〜3。4 になったら終了
    feeder: tuple[str, ...]  # 餌箱に残るダイスの目(Food の値、または INV_OR_SEED)。並びは昇順
    tray: tuple[str, ...]  # カードトレイ。取られた枠は空文字(手番の終わりに補充。R p.9)
    deck: tuple[str, ...]  # 山札(上が先頭)。実機の追跡では空(不明)のまま
    discard: tuple[str, ...]
    goals: tuple[GoalTile, ...]  # ラウンド 1〜4 の目的
    goal_mode: GoalMode = GoalMode.MAJORITY
    queue: tuple[Task, ...] = ()
    events: tuple[str, ...] = ()  # この手番に起きたこと(桃色の能力の引き金)
    pending_setup: tuple[int, ...] = field(default=())  # 初期選択が済んでいないプレイヤー
    # 乱数の種。乱数を使うたびに進める(同じ状態と手なら同じ結果になり、Rules.apply が純粋に保てる)
    seed: int = 0
    # 画面が、決定ではなく「確認を求める画面」のとき、その種類(認識が立てる。空なら通常の決定)
    # "turn_start" / "confirm" / "skip" / "round" / "mat_view"
    ack: str = ""

    @property
    def terminal(self) -> bool:
        return self.round_index >= 4

    def with_player(self, index: int, board: PlayerBoard) -> "WingspanState":
        players = list(self.players)
        players[index] = board
        return replace(self, players=tuple(players))
