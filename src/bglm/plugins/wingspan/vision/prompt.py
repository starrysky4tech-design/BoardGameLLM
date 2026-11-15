"""右下の案内パネルの文言から、いま答える決定の種類を決める(02_DESIGN.md 論点 5)。

案内の文言は閉じた集合(保存画面 324 枚の OCR で確かめた。RESULT.md §9〜§11)。OCR は一部の字を誤る
(「餌」→「館」「朗」、「いずれか」→「いすれか」)ので、文言との類似度を、OCR の文字列の部分文字列に対して測る。
どの文言にも当てはまらない案内は UNKNOWN とし、文字列を残す(鳥の能力の案内は札ごとに文が違うので、
実装していない能力は UNKNOWN になる。executor はスキップする。02_DESIGN.md 論点 2)。
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from bglm.plugins.wingspan.logic.state import (
    ConvertFoodTask,
    DrawBonusTask,
    DrawTask,
    EggBonusTask,
    GainFoodTask,
    LayEggsTask,
    PowersTask,
    SetupTask,
    Task,
    TuckTask,
)
from bglm.plugins.wingspan.vision.mat import Image, LineReader
from bglm.plugins.wingspan.vision.names import fold

PANEL_REGION = (1500, 760, 2240, 1030)  # 案内パネル(原寸)。カードトレイの札の文字も少し入る
MIN_SCORE = 0.78  # 文言と、OCR の部分文字列の類似度の下限


class PromptKind(StrEnum):
    LAY_EGGS = "lay_eggs"  # 鳥をタップして産卵してください。
    PICK_DIE = "pick_die"  # 餌箱から餌を選んでください。
    PAY_FOOD = "pay_food"  # 鳥のプレイの支払い(コスト / 払う / 変更)
    PICK_CARD = "pick_card"  # 1 枚カードを選ぶ。残りカード
    PAY_EGGS = "pay_eggs"  # いずれかの生息地の鳥をタップして卵を使う。
    DISCARD_EGG = "discard_egg"  # 卵を捨てる(卵 → 札の変換)
    DISCARD_CARD = "discard_card"  # カードを捨てる(札 → 餌の変換)
    DISCARD_FOOD = "discard_food"  # 捨てる餌を選ぶ。(餌 → 卵の変換)
    TUCK = "tuck"  # 手札からカードを差し込む。
    CHOOSE_HABITAT = "choose_habitat"  # 鳥をプレイする生息地を選んでください。
    POWER_FEEDER_CACHE = "power_feeder_cache"  # 餌箱から餌を獲得し、蓄えてもよい
    POWER_GAIN_CACHE = "power_gain_cache"  # 共通在庫から獲得してこのカードに蓄える
    POWER_GAIN = "power_gain"  # 共通在庫から獲得する
    DRAW_DECK = "draw_deck"  # 山札から引く(山札だけが選べる。能力で全員が引く)
    POWER_MOVE = "power_move"  # 別の生息地に移動させる(未実装の能力)
    NOTHING_TO_DO = "nothing_to_do"  # 産卵できる鳥がいません。このアクションをスキップしてください(実行できる対象が無い)
    UNKNOWN = "unknown"


# (種類, 必要な文言のすべて)。同点のときは上にあるものを選ぶ(長い文言・特殊な文言を先に)
_RULES: tuple[tuple[PromptKind, tuple[str, ...]], ...] = (
    (PromptKind.NOTHING_TO_DO, ("このアクションをスキップしてください",)),
    (PromptKind.POWER_FEEDER_CACHE, ("それをこの鳥の上に蓄えてもよい",)),
    (PromptKind.POWER_GAIN_CACHE, ("共通在庫から獲得してこのカードに蓄える",)),
    (PromptKind.POWER_MOVE, ("別の生息地に移動させる",)),
    (PromptKind.POWER_GAIN, ("共通在庫から獲得する",)),
    (
        PromptKind.POWER_GAIN,
        ("最も少ない", "を引く"),
    ),  # 最も少ない湿地の鳥のプレイヤーが 1 枚引く(実機)
    (PromptKind.DRAW_DECK, ("を山札から引く",)),
    (PromptKind.CHOOSE_HABITAT, ("生息地を選んでください",)),
    (PromptKind.PAY_EGGS, ("鳥をタップして卵を使う",)),
    (PromptKind.LAY_EGGS, ("鳥をタップして産卵してください",)),
    (PromptKind.PICK_DIE, ("餌箱から餌を選んでください",)),
    (PromptKind.DISCARD_FOOD, ("捨てる餌を選ぶ",)),
    (PromptKind.DISCARD_EGG, ("卵を捨てる",)),
    (PromptKind.TUCK, ("手札からカードを差し込む",)),
    (PromptKind.DISCARD_CARD, ("カードを捨てる",)),
    (PromptKind.PICK_CARD, ("1枚カードを選ぶ",)),
    (PromptKind.PAY_FOOD, ("コスト", "払う")),
)

# 文言の判別にだけ使う、OCR の読み違い(餌 → 館・朗)。名前の照合(names.fold)とは別に持つ
_PROMPT_FIX = str.maketrans({"館": "餌", "朗": "餌", "畜": "蓄", "丼": "蓄"})


def _norm(text: str) -> str:
    return fold(text.translate(_PROMPT_FIX))


def phrase_score(text: str, phrase: str) -> float:
    """phrase が text の部分文字列として、どれだけ近く現れるか(0〜1)。"""
    target, hay = _norm(phrase), _norm(text)
    if not target or not hay:
        return 0.0
    if target in hay:
        return 1.0
    best = 0.0
    for length in (len(target) - 1, len(target), len(target) + 1):
        for i in range(max(1, len(hay) - length + 1)):
            window = hay[i : i + length]
            best = max(best, SequenceMatcher(None, window, target).ratio())
    return best


@dataclass(frozen=True)
class PromptRead:
    kind: PromptKind
    text: str  # OCR の生の文字列(記録用。UNKNOWN の能力の案内はこれで追う)


def classify_text(text: str) -> PromptKind:
    """最も類似度の高い文言の種類。「カードを捨てる」と「卵を捨てる」のように近い文言があるので、
    基準を超えた最初のものではなく、最高点を選ぶ(同点は上の順)。どれも基準未満なら UNKNOWN。"""
    best_kind, best = PromptKind.UNKNOWN, 0.0
    for kind, phrases in _RULES:
        score = min(phrase_score(text, p) for p in phrases)
        if score > best:
            best_kind, best = kind, score
    return best_kind if best >= MIN_SCORE else PromptKind.UNKNOWN


def read_prompt(image: Image, read_lines: LineReader) -> PromptRead:
    """案内パネルを読み、決定の種類を返す。パネルが無い画面では呼ばない(`screens.classify` の prompt)。"""
    text = " ".join(read_lines(image, PANEL_REGION))
    return PromptRead(classify_text(text), text)


_POWER_PROMPTS = frozenset(
    {
        PromptKind.POWER_FEEDER_CACHE,
        PromptKind.POWER_GAIN_CACHE,
        PromptKind.POWER_GAIN,
        PromptKind.POWER_MOVE,
        PromptKind.TUCK,
        PromptKind.UNKNOWN,  # 実装していない能力の案内は、文言が決まらない(スキップで進める)
    }
)


def expected_prompts(task: Task) -> frozenset[PromptKind]:
    """追跡している決定(Task)に対して、画面に出てよい案内の種類。

    鳥のプレイの途中(PAY_FOOD、PAY_EGGS、CHOOSE_HABITAT)は、決定の列ではなく 1 つの手 `PlayBird` の中の操作なので、
    ここには含めない(executor が手の途中で確かめる)。
    """
    match task:
        case GainFoodTask():
            return frozenset({PromptKind.PICK_DIE})
        case ConvertFoodTask():
            # 変換の決定の間も、パネルは「餌を選んでください」のまま(札を捨てるボタンを押すと DISCARD_CARD)
            return frozenset({PromptKind.PICK_DIE, PromptKind.DISCARD_CARD})
        case LayEggsTask():
            return frozenset({PromptKind.LAY_EGGS})
        case EggBonusTask():
            return frozenset({PromptKind.LAY_EGGS, PromptKind.DISCARD_FOOD})
        case DrawTask():
            return frozenset({PromptKind.PICK_CARD, PromptKind.DRAW_DECK})
        case DrawBonusTask():
            return frozenset({PromptKind.PICK_CARD, PromptKind.DISCARD_EGG})
        case TuckTask():
            return frozenset({PromptKind.TUCK})
        case PowersTask():
            return _POWER_PROMPTS
        case SetupTask():
            return frozenset()
    raise AssertionError(f"未知の決定: {task}")
