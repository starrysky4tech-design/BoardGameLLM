"""中央のダイアログの種別の判別(`screens.classify` が DIALOG と決めた画面の、文言による区別)。

文言は、保存画面 66 枚の OCR で確かめた(RESULT.md §9〜§12)。OCR は倍率 2 で十分読める。
- TURN_START: 「ラウンド n/4」「残り m 手番」「タップして手番を開始する。」(相手の行動の案内が付くこともある)
- ROUND_SCORE: ラウンドの目的の採点(「総合スコア」)
- FINAL: 終局の得点の画面(「メニュー 概観 リプレイ 詳細」、得点の演出の「勝利点」)
- SAVE_PROMPT: 終局後の「ゲームをセーブして保護区の記録をしますか?」(× で保存しない。RESULT.md §10)
- GAME_MENU: 歯車のメニュー(再開・設定・メインメニュー)。メインメニューは押さない
- STORE: 起動直後のストアの案内。押さない
どれにも当てはまらなければ UNKNOWN。
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from bglm.plugins.wingspan.vision.mat import Image, LineReader
from bglm.plugins.wingspan.vision.prompt import MIN_SCORE, phrase_score

DIALOG_REGION = (500, 60, 1930, 1000)  # 中央のパネルが覆う範囲(原寸)
DIALOG_SCALE = 2  # OCR の倍率(1 で読めるが崩れやすく、3 は遅い)


class DialogKind(StrEnum):
    TURN_START = "turn_start"
    ROUND_SCORE = "round_score"
    FINAL = "final"
    SAVE_PROMPT = "save_prompt"
    GAME_MENU = "game_menu"
    STORE = "store"
    UNKNOWN = "unknown"


# (種類, 必要な文言のすべて)。同点のときは上にあるものを選ぶ(保存の確認は、背景に終局の画面があるので FINAL より上)
_RULES: tuple[tuple[DialogKind, tuple[str, ...]], ...] = (
    (DialogKind.SAVE_PROMPT, ("ゲームをセーブして保護区の記録",)),
    (DialogKind.STORE, ("ストアに移動",)),
    (DialogKind.GAME_MENU, ("メインメニュー", "再開")),
    (DialogKind.TURN_START, ("タップして手番を開始する",)),
    (DialogKind.ROUND_SCORE, ("総合スコア",)),
    (DialogKind.FINAL, ("概観リプレイ詳細",)),
    (DialogKind.FINAL, ("1つにつき1勝利点",)),
)

_ROUND = re.compile(r"ラウンド\s*([1-4])\s*/\s*4")
_REMAINING = re.compile(r"残り\s*(\d)\s*手番")


@dataclass(frozen=True)
class DialogRead:
    kind: DialogKind
    text: str  # OCR の生の文字列(記録用)
    round_no: int | None  # 手番開始の表示の「ラウンド n/4」(1〜4)
    remaining: int | None  # 「残り m 手番」


def classify_dialog_text(text: str) -> DialogKind:
    best_kind, best = DialogKind.UNKNOWN, 0.0
    for kind, phrases in _RULES:
        score = min(phrase_score(text, p) for p in phrases)
        if score > best:
            best_kind, best = kind, score
    return best_kind if best >= MIN_SCORE else DialogKind.UNKNOWN


def parse_turn_header(text: str) -> tuple[int | None, int | None]:
    """手番開始の表示の「ラウンド n/4」と「残り m 手番」。読めない方は None。"""
    round_match, remaining = _ROUND.search(text), _REMAINING.search(text)
    return (
        int(round_match.group(1)) if round_match else None,
        int(remaining.group(1)) if remaining else None,
    )


def read_dialog(image: Image, read_lines: LineReader) -> DialogRead:
    text = " ".join(read_lines(image, DIALOG_REGION))
    kind = classify_dialog_text(text)
    round_no, remaining = parse_turn_header(text) if kind is DialogKind.TURN_START else (None, None)
    return DialogRead(kind, text, round_no, remaining)


CONFIRM_REGION = (960, 330, 1460, 740)  # 確認ダイアログの紙のパネル(原寸)


def is_skip_confirm(image: Image, read_lines: LineReader) -> bool:
    """確認ダイアログの文言に「スキップ」があるか(能力のスキップ、「まだ餌を取れます」の警告のどちらも)。

    色だけでは、確認ダイアログと、紙の色が広がった盤を取り違えうる(`screens.classify` の CONFIRM は候補)。
    """
    text = " ".join(read_lines(image, CONFIRM_REGION))
    return phrase_score(text, "スキップ") >= MIN_SCORE


class SetupKind(StrEnum):
    KEEP = "keep"  # 「鳥カードと餌の中からキープしたいものを 5 選んでください」
    BONUS = "bonus"  # 「キープする 1 ボーナスカードを選んでください」
    NONE = "none"


SETUP_TITLE_PHRASES: tuple[tuple[SetupKind, str], ...] = (
    (SetupKind.KEEP, "鳥カードと餌の中からキープしたいものを"),
    (SetupKind.BONUS, "ボーナスカードを選んでください"),
)


def classify_setup_title(text: str) -> SetupKind:
    best_kind, best = SetupKind.NONE, 0.0
    for kind, phrase in SETUP_TITLE_PHRASES:
        score = phrase_score(text, phrase)
        if score > best:
            best_kind, best = kind, score
    return best_kind if best >= MIN_SCORE else SetupKind.NONE


def read_setup(image: Image, read_lines: LineReader) -> SetupKind:
    """初期選択の画面か(画面上部の題)。他の画面では NONE。"""
    from bglm.plugins.wingspan.vision.layout import SETUP_TITLE

    return classify_setup_title(" ".join(read_lines(image, SETUP_TITLE)))
