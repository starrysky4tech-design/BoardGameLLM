"""札名の照合。OCR で読んだ文字列を、札の表の名前に当てはめる(02_DESIGN.md 論点 4)。

日本語の認識モデルは、カタカナで次の誤読をする(RESULT.md §6): シ↔ツ、ン↔ソ、コ↔ユ、濁点の欠け、2 行に分かれた名前。
照合は、これらを畳み込んだ文字列どうしの類似度で行う。**表に無い札を近い名前へ無理に当てはめない**:
類似度が低い、または 2 番目の候補との差が小さいときは None(読めない)を返す。

名前の他に、翼長と点が読めていれば、表の値と合わないときも None にする(別の札を当てた疑い)。
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from bglm.plugins.wingspan.logic.models import BirdCard

# 似た形で読み違えやすい字を 1 つに畳む(畳んだ後の文字列どうしで比べる)
_CONFUSABLE = str.maketrans(
    {"シ": "ツ", "ソ": "ン", "ユ": "コ", "一": "ー", "へ": "ヘ", "り": "リ", "三": "ミ"}
)
_SMALL_KANA = str.maketrans("ャュョッァィゥェォ", "ヤユヨツアイウエオ")
_IGNORED = re.compile(r"[\s・･.\-‐‑–—_'’`´,，、。:：;；()（）\[\]「」]")

MIN_SCORE = 0.82  # これ未満の類似度は、別の札(または読み誤り)として扱う
MIN_MARGIN = 0.08  # 1 位と 2 位の差がこれ未満なら、どちらか決められない


def fold(text: str) -> str:
    """比べるために文字列を畳む: 全角半角の統一、空白と記号の除去、濁点の除去、小さい仮名、似た字の統一。"""
    text = unicodedata.normalize("NFKC", text)
    text = _IGNORED.sub("", text)
    text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    text = text.translate(_SMALL_KANA)
    return text.translate(_CONFUSABLE)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, fold(a), fold(b)).ratio()


@dataclass(frozen=True)
class NameMatch:
    name: str  # 表の札名
    score: float  # 1 位の類似度(0〜1)
    margin: float  # 2 位との差(候補が 1 つなら 1 位の類似度)


def match_name(
    text: str,
    names: Iterable[str],
    *,
    min_score: float = MIN_SCORE,
    min_margin: float = MIN_MARGIN,
) -> NameMatch | None:
    """OCR の文字列に最も近い札名。読めない、表に無い、決められないときは None。"""
    if not fold(text):
        return None
    scored = sorted(((similarity(text, n), n) for n in names), reverse=True)
    if not scored or scored[0][0] < min_score:
        return None
    margin = scored[0][0] - (scored[1][0] if len(scored) > 1 else 0.0)
    if margin < min_margin:
        return None
    return NameMatch(scored[0][1], scored[0][0], margin)


def consistent(
    card: BirdCard, *, wingspan_cm: int | None = None, points: int | None = None
) -> bool:
    """読めた翼長・点が、表の値と合っているか。読めていない値(None)は比べない。"""
    if wingspan_cm is not None and wingspan_cm != card.wingspan_cm:
        return False
    return points is None or points == card.points


def match_card(
    text: str,
    birds: dict[str, BirdCard],
    *,
    wingspan_cm: int | None = None,
    points: int | None = None,
) -> NameMatch | None:
    """札名と、読めていれば翼長・点で、表の札を 1 枚に決める。決められなければ None。"""
    found = match_name(text, birds)
    if found is None:
        return None
    return found if consistent(birds[found.name], wingspan_cm=wingspan_cm, points=points) else None
