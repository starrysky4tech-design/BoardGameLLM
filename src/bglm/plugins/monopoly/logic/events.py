"""Log の 1 行を、対局の出来事に変える(画面に依存しない。文字の読み取りは vision/log_reader.py)。

入力は、Log の行の文字列。OCR の誤読(「Illinois」→「lllinois」、「₼」→「M」、空白の欠け)は、
ここで語彙(プレイヤー名、場所の名前)に合わせて補正する。補正できない行は、出来事にせず UnknownLine で返す。
推測で別の出来事にしない。

プレイヤー名: Log の名前 "Top Hat" = 自分、"Dog" = AI(2026-11-05 の対局。名前は設定で変える想定)。
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches

from bglm.plugins.monopoly.logic.board import BOARD
from bglm.plugins.monopoly.logic.models import Player

# 自分は Top Hat、相手は、それ以外の駒のどれか(実機: Dog、Thimble)。駒が変わっても、相手として読む。
# 実機で確かめた駒だけを入れる(他の駒は、名前を確かめて足す)。名前が無い行は、未知の行として止まる(推測で読まない)
# 自分の駒は、対局の設定で変わる(実機: Top Hat、Shoe)。Shoe は設定画面の表記。Log の表記は、対局の最初の行で確かめる。
PLAYER_NAMES: dict[str, Player] = {
    **dict.fromkeys(("Top Hat", "Shoe"), Player.SELF),
    **dict.fromkeys(
        ("Dog", "Thimble", "Wheelbarrow"),
        Player.AI,
    ),
}
SQUARE_NAMES: tuple[str, ...] = tuple(dict.fromkeys(sq.name for sq in BOARD))


@dataclass(frozen=True)
class TurnStarted:
    player: Player


@dataclass(frozen=True)
class DiceRolled:
    player: Player
    total: int
    doubles: bool


@dataclass(frozen=True)
class LandedOn:
    player: Player
    square: str


@dataclass(frozen=True)
class RentPaid:
    payer: Player
    amount: int
    owner: Player


@dataclass(frozen=True)
class AuctionStarted:
    player: Player  # 買わずに見送った側
    square: str


@dataclass(frozen=True)
class AuctionWon:
    winner: Player
    square: str
    price: (
        int | None
    )  # "wins <場所> for ₼N." の行にだけ金額がある。"won ... at auction" の行では None
    direct: bool = False  # "bought <場所> for ₼N."(通常の購入)。購入者は、その土地に止まっている


@dataclass(frozen=True)
class TradeInitiated:
    """取引の提案(`<P> initiated a trade with <Q>.`)。状態は変わらない(成立した取引は、別の行で出る)。"""

    proposer: Player


@dataclass(frozen=True)
class TradeResult:
    """取引の成立の行(`<P> accepted trade with <Q>`、`<P> received M<額> from <Q>`、`<P> received <土地> from <Q>`)。

    結果(所有と現金)は、取引を操作した側(実行ループ)が、成功時に状態へ反映する。Log の行は、数えない。
    """

    player: Player
    kind: str  # "accepted" / "cash" / "deed"
    detail: str = ""  # 現金の額、または土地の名前


@dataclass(frozen=True)
class GameStarted:
    """対局の開始(`<P> gets to go first.`)。状態は変わらない。"""

    first: Player


@dataclass(frozen=True)
class SentToJail:
    player: Player


@dataclass(frozen=True)
class HotelBuilt:
    """ホテルの建設(`<P> built a hotel on <土地>`)。家 4 軒をホテル 1 つに替える。費用は、家 1 軒分(実機で確認済みの規則)。"""

    player: Player
    square: str


@dataclass(frozen=True)
class Unmortgaged:
    """抵当の解除(`<P> unmortgaged <土地> for M<額>`)。額は、抵当価値の 1.1 倍(Log の表記)。"""

    player: Player
    square: str
    amount: int


@dataclass(frozen=True)
class NoRentCollected:
    """抵当に入っている土地に止まった(`Property is mortgaged. No rent collected.`)。現金も所有も変わらない。"""


@dataclass(frozen=True)
class MoneyReceived:
    """Community Chest や Chance などから、現金を受け取った(`<P> receives ₼N from <出どころ>`)。"""

    player: Player
    amount: int
    source: str


@dataclass(frozen=True)
class MoneyLost:
    """Community Chest や Chance などで、現金を失った(`<P> loses ₼N from <出どころ>`)。"""

    player: Player
    amount: int
    source: str


@dataclass(frozen=True)
class TaxPaid:
    """税金の支払い(`<P> pays ₼N in <税金>.`)。現金は、止まったマスの税額で台帳が計算済み(二重に数えない)。"""

    player: Player
    amount: int
    tax: str


@dataclass(frozen=True)
class HousesSold:
    player: Player
    count: int
    square: str


@dataclass(frozen=True)
class Mortgaged:
    player: Player
    square: str
    amount: int  # 受け取った抵当価値


@dataclass(frozen=True)
class BailPosted:
    """罰金 ₼50 を払って刑務所を出た。3 回目の出目が出なかった手番では、その出目で進む(実機の Log で確認)。"""

    player: Player


@dataclass(frozen=True)
class HousesBuilt:
    player: Player
    count: int
    square: str


@dataclass(frozen=True)
class UnknownLine:
    text: str  # 補正後の文字列(読めなかった行。保存して、文型を増やす入力にする)


LogEvent = (
    TurnStarted
    | DiceRolled
    | LandedOn
    | RentPaid
    | AuctionStarted
    | AuctionWon
    | SentToJail
    | BailPosted
    | HousesSold
    | MoneyReceived
    | HotelBuilt
    | NoRentCollected
    | GameStarted
    | TradeResult
    | TradeInitiated
    | Unmortgaged
    | TaxPaid
    | MoneyLost
    | Mortgaged
    | HousesBuilt
    | UnknownLine
)

_CHAR_FIXES = str.maketrans({"₼": "M", "|": "l"})
_SQUARE_BY_KEY = {re.sub(r"[^a-z0-9]", "", name.lower()): name for name in SQUARE_NAMES}


def normalize(text: str) -> str:
    """OCR の誤読を、文型の照合ができる形に直す。大文字の I と小文字の l の取り違えは、場所の名前で直す。"""
    cleaned = text.strip().translate(_CHAR_FIXES)
    # 数字の直後の o / O(後ろに英字が続かない)は、0 の誤読(実機: M1o0、M5o)
    cleaned = re.sub(r"(?<=\d)[oO]+(?![A-Za-z])", lambda m: "0" * len(m.group(0)), cleaned)
    # 金額の前の A は、通貨記号(₼)の誤読(実機: A6、AA442)
    cleaned = re.sub(r"(?<![A-Za-z])(?:A|M)?A(?=\d)", "M", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    # 空白が欠けた行(TopHatlandedonVermontAvenue)は、語彙で区切り直す
    cleaned = _respace(cleaned)
    return cleaned


_WORDS = (
    *PLAYER_NAMES,
    "is",
    "starting",
    "its",
    "turn",
    "rolled",
    "Doubles",
    "landed",
    "paid",
    "in",
    "rent",
    "to",
    "passed",
    "Starting",
    "auction",
    "wins",
    "won",
    "at",
    "for",
    "built",
    "initiated",
    "a trade",
    "trade",
    "with",
    "with",
    "trade",
    "received",
    "accepted",
    "bought",
    "unmortgaged",
    "gets",
    "go",
    "first",
    "hotel",
    "sold",
    "mortgaged",
    "receives",
    "loses",
    "pays",
    "Tax",
    "from",
    "houses",
    "house",
    "on",
    "Oh no",
    "has",
    "been",
    "sent",
    "Jail",
    "posted",
    "bail",
)


def _respace(text: str) -> str:
    """空白が欠けた行を、既知の語句(プレイヤー名、動詞、場所の名前)で区切り直す。

    正しい行は、そのまま返す(記号や金額の書き方を、変えない)。欠けを疑うのは、次のとき:
    - 13 文字以上の長い語がある
    - 既知の語(動詞、プレイヤー名)が、他の語にくっついている(「Dogis」「TopHatrolled5」「startingits」)
    区切り直しは、語の先頭から、既知の語句を最長一致で切り出し、数字は 1 語にする。切り出せなければ、元の語のまま。
    """
    per_word = " ".join(_split_word(word) for word in text.split(" "))
    if _matches_a_pattern(per_word):
        return per_word
    # 語ごとの分割で、どの文型にも合わない。語の境目をまたいで、くっついている(「Top Hatrolled 9」)
    # 可能性がある。行全体を、いったんつなげて、区切り直す。区切れなければ、語ごとの結果を返す
    glued = _split_word("".join(text.split(" ")), force=True)
    return glued if _matches_a_pattern(glued) else per_word


def _fold(text: str) -> str:
    """区切りの照合用。小文字にして、l と I(OCR が取り違える)を同じ文字にする。"""
    return text.lower().replace("l", "i")


def _known_keyed() -> list[tuple[str, str]]:
    known = sorted([*_WORDS, *SQUARE_NAMES, *PLAYER_NAMES], key=len, reverse=True)
    return [(_fold(re.sub(r"[^A-Za-z0-9]", "", ph)), ph) for ph in known]


def _split_word(word: str, force: bool = False) -> str:
    """1 語を、既知の語句と数字の連結として分ける。短い語や、既に 1 つの語句の語は、そのまま返す。

    force=True は、行全体をつなげた文字列を、長さに関係なく分ける。
    """
    if len(word) < 5 and not force:
        return word
    key = _fold(re.sub(r"[^A-Za-z0-9]", "", word))
    if not key:
        return word
    keyed = _known_keyed()
    if any(key == pk for pk, _ in keyed):
        return word  # すでに、1 つの既知の語句
    parts: list[str] = []
    rest = key
    while rest:
        # 金額(M の後に数字。₼ の OCR の誤読)と、数字は、1 つのまとまりとして切り出す
        # ₼ は、M や A に誤読される(実機: forA40)。「M / A + 数字」は、金額(M + 数字)として切り出す
        digits = re.match(r"[ma]\d+", rest) if re.match(r"[ma]\d", rest) else re.match(r"\d+", rest)
        if digits:
            text = digits.group(0)
            parts.append("M" + text[1:] if text[0] in "ma" else text)
            rest = rest[len(digits.group(0)) :]
            continue
        for pk, phrase in keyed:
            if pk and rest.startswith(pk):
                parts.append(phrase)
                rest = rest[len(pk) :]
                break
        else:
            return word  # 切り出せない部分がある。推測で分けない
    return " ".join(parts) if len(parts) > 1 else word


def _matches_a_pattern(line: str) -> bool:
    return any(
        pattern.match(line)
        for pattern in (
            _TURN,
            _ROLL,
            _LAND,
            _RENT,
            _PASS,
            _WINS,
            _WON,
            _BOUGHT,
            _JAIL,
            _BAIL,
            _SOLD,
            _MORTGAGED,
            _BUILT,
            _HOTEL,
            _NO_RENT,
            _FIRST,
            _TRADE,
            _TRADE_ACCEPTED,
            _TRADE_CASH,
            _TRADE_DEED,
            _UNMORTGAGED,
        )
    )


def _player(name: str) -> Player | None:
    key = re.sub(r"\s", "", name).lower()
    for known, player in PLAYER_NAMES.items():
        if re.sub(r"\s", "", known).lower() == key:
            return player
    return None


def match_square(name: str) -> str | None:
    """場所の名前を、盤の名前に合わせる。大文字 I と小文字 l、空白の差を許す。曖昧なら None。"""
    key = re.sub(r"[^a-z0-9]", "", name.lower().replace("l", "i"))
    candidates = {
        re.sub(r"[^a-z0-9]", "", k.replace("l", "i")): v for k, v in _SQUARE_BY_KEY.items()
    }
    if key in candidates:
        return candidates[key]
    close = get_close_matches(key, list(candidates), n=1, cutoff=0.9)
    return candidates[close[0]] if close else None


_PLAYER = "(" + "|".join(name.replace(" ", " ?") for name in PLAYER_NAMES) + ")"
_TURN = re.compile(rf"^{_PLAYER} ?is ?start\w{{0,4}} ?its ?turn\.?$", re.I)
_ROLL = re.compile(rf"^{_PLAYER} ?rolled (\d{{1,2}})(!? ?Doubles!?)?\.?$", re.I)
_LAND = re.compile(rf"^{_PLAYER} ?landed on (.+?)\.?$", re.I)
_RENT = re.compile(rf"^{_PLAYER} ?paid M?(\d+) in rent to {_PLAYER}\.?$", re.I)
_PASS = re.compile(rf"^{_PLAYER} ?passed ?on (.+?)[. ]*starting ?auction\.?$", re.I)
_WINS = re.compile(rf"^{_PLAYER} ?wins (.+?) for M?(\d+)\.?$", re.I)
_BOUGHT = re.compile(rf"^{_PLAYER} ?bought (.+?) for M?(\d+)\.?$", re.I)
_WON = re.compile(rf"^{_PLAYER} ?won (.+?) at auction\.?$", re.I)
_JAIL = re.compile(rf"^Oh no!? ?{_PLAYER} has ?been sent to Jail\.?$", re.I)
_SOLD = re.compile(rf"^{_PLAYER} ?sold (\d+) houses? on (.+?)\.?$", re.I)
_MORTGAGED = re.compile(rf"^{_PLAYER} ?mortgaged (.+?) for M?(\d+)\.?$", re.I)
_RECEIVES = re.compile(rf"^{_PLAYER} ?receives M?(\d+) from (.+?)\.?$", re.I)
_LOSES = re.compile(rf"^{_PLAYER} ?loses M?(\d+) from (.+?)\.?$", re.I)
_TAX = re.compile(rf"^{_PLAYER} ?pays M?(\d+) in (Luxury Tax|Income Tax)\.?$", re.I)
_HOTEL = re.compile(rf"^{_PLAYER} ?built ?a ?hotel on (.+?)\.?$", re.I)
_NO_RENT = re.compile(r"^Property is mortgaged\. ?No rent collected\.?$", re.I)
_UNMORTGAGED = re.compile(rf"^{_PLAYER} ?unmortgaged (.+?) for M?(\d+)\.?$", re.I)
_FIRST = re.compile(rf"^{_PLAYER} ?gets to go first\.?$", re.I)
_TRADE = re.compile(rf"^{_PLAYER} ?initiated a trade with {_PLAYER}\.?$", re.I)
_TRADE_ACCEPTED = re.compile(rf"^{_PLAYER} ?accepted ?trade ?with ?{_PLAYER}\.?$", re.I)
_TRADE_CASH = re.compile(rf"^{_PLAYER} ?received M?(\d+) ?from ?{_PLAYER}\.?$", re.I)
_TRADE_DEED = re.compile(rf"^{_PLAYER} ?received (.+?) ?from ?{_PLAYER}\.?$", re.I)
_BAIL = re.compile(rf"^{_PLAYER} ?has posted bail\.?$", re.I)
_BUILT = re.compile(rf"^{_PLAYER} ?built (\d+) houses? on (.+?)\.?$", re.I)


def _fuzzy_turn(line: str) -> LogEvent:
    """「<駒> is starting its turn」の、文字の誤読と空白の欠落が重なった行を、手番の開始として読む。

    手番の開始は、状態を変えない行なので、近い綴り(類似度 0.85 以上)を採る。最も近い駒の名前を、手番の主にする。
    他の行は、取り違えを避けるため、この方法を使わない(未知の行のまま)。
    """
    key = re.sub(r"[^a-z]", "", line.lower())
    best: tuple[float, Player] | None = None
    for name, player in PLAYER_NAMES.items():
        target = re.sub(r"[^a-z]", "", name.lower()) + "isstartingitsturn"
        ratio = SequenceMatcher(None, key, target).ratio()
        if ratio >= 0.85 and (best is None or ratio > best[0]):
            best = (ratio, player)
    return TurnStarted(best[1]) if best else UnknownLine(line)


def parse_line(text: str) -> LogEvent:
    """Log の 1 行を出来事にする。文型にも語彙にも合わなければ UnknownLine。"""
    line = normalize(text)
    if m := _TURN.match(line):
        player = _player(m.group(1))
        return TurnStarted(player) if player else UnknownLine(line)
    if m := _ROLL.match(line):
        player = _player(m.group(1))
        total = int(m.group(2))
        if player is None or not 2 <= total <= 12:
            return UnknownLine(line)
        return DiceRolled(player, total, doubles=m.group(3) is not None)
    if m := _LAND.match(line):
        player, square = _player(m.group(1)), match_square(m.group(2))
        return LandedOn(player, square) if player and square else UnknownLine(line)
    if m := _RENT.match(line):
        payer, owner = _player(m.group(1)), _player(m.group(3))
        if payer and owner and payer is not owner:
            return RentPaid(payer, int(m.group(2)), owner)
        return UnknownLine(line)
    if m := _PASS.match(line):
        player, square = _player(m.group(1)), match_square(m.group(2))
        return AuctionStarted(player, square) if player and square else UnknownLine(line)
    if m := _WINS.match(line):
        player, square = _player(m.group(1)), match_square(m.group(2))
        return (
            AuctionWon(player, square, int(m.group(3))) if player and square else UnknownLine(line)
        )
    if m := _BOUGHT.match(line):  # 通常の購入。効果は落札(価格を払い、所有者になる)と同じ
        player, square = _player(m.group(1)), match_square(m.group(2))
        return (
            AuctionWon(player, square, int(m.group(3)), direct=True)
            if player and square
            else UnknownLine(line)
        )
    if m := _WON.match(line):
        player, square = _player(m.group(1)), match_square(m.group(2))
        return AuctionWon(player, square, None) if player and square else UnknownLine(line)
    if m := _JAIL.match(line):
        player = _player(m.group(1))
        return SentToJail(player) if player else UnknownLine(line)
    if m := _RECEIVES.match(line):
        player = _player(m.group(1))
        return MoneyReceived(player, int(m.group(2)), m.group(3)) if player else UnknownLine(line)
    if m := _TAX.match(line):
        player = _player(m.group(1))
        return TaxPaid(player, int(m.group(2)), m.group(3).title()) if player else UnknownLine(line)
    if m := _LOSES.match(line):
        player = _player(m.group(1))
        return MoneyLost(player, int(m.group(2)), m.group(3)) if player else UnknownLine(line)
    if m := _SOLD.match(line):
        player, square = _player(m.group(1)), match_square(m.group(3))
        return (
            HousesSold(player, int(m.group(2)), square) if player and square else UnknownLine(line)
        )
    if m := _MORTGAGED.match(line):
        player, square = _player(m.group(1)), match_square(m.group(2))
        return (
            Mortgaged(player, square, int(m.group(3))) if player and square else UnknownLine(line)
        )
    if m := _BAIL.match(line):
        player = _player(m.group(1))
        return BailPosted(player) if player else UnknownLine(line)
    if m := _UNMORTGAGED.match(line):
        player, square = _player(m.group(1)), match_square(m.group(2))
        return (
            Unmortgaged(player, square, int(m.group(3))) if player and square else UnknownLine(line)
        )
    if m := _TRADE_ACCEPTED.match(line):
        player = _player(m.group(1))
        return TradeResult(player, "accepted") if player else UnknownLine(line)
    if m := _TRADE_CASH.match(line):
        player = _player(m.group(1))
        return TradeResult(player, "cash", m.group(2)) if player else UnknownLine(line)
    if m := _TRADE_DEED.match(line):
        player, square = _player(m.group(1)), match_square(m.group(2))
        return TradeResult(player, "deed", square) if player and square else UnknownLine(line)
    if m := _TRADE.match(line):
        proposer = _player(m.group(1))
        return TradeInitiated(proposer) if proposer else UnknownLine(line)
    if m := _FIRST.match(line):
        player = _player(m.group(1))
        return GameStarted(player) if player else UnknownLine(line)
    if _NO_RENT.match(line):
        return NoRentCollected()
    if m := _HOTEL.match(line):
        player, square = _player(m.group(1)), match_square(m.group(2))
        return HotelBuilt(player, square) if player and square else UnknownLine(line)
    if m := _BUILT.match(line):
        player, square = _player(m.group(1)), match_square(m.group(3))
        return (
            HousesBuilt(player, int(m.group(2)), square) if player and square else UnknownLine(line)
        )
    return _fuzzy_turn(line)
