"""購入画面とオークション画面の文字(土地名、価格、最高入札、所持金)を読む。座標は原寸(2432x1080)。

OCR は RapidOCR(Log と同じ)。誤読は、場所の名前の語彙と数字の形で補正する。読めなければ None(推測しない)。

- 購入画面: 見出し「FOR SALE!」の下の 1 行 `Purchase "<土地>" for ₼N?`
- オークション: 上の所持金(自分・Dog)、「Highest bid:」の黄色い枠の金額
"""

import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from bglm.plugins.monopoly.logic.events import match_square  # 場所の名前の補正(I と l、空白)
from bglm.toolkit.ocr_reader import recognize

PURCHASE_BOX = (890, 235, 1630, 280)
AUCTION_BID_BOX = (1270, 275, 1580, 365)  # 「Highest bid:」の枠全体(枠の文字を確かめる)
AUCTION_BID_AMOUNT_BOX = (
    1270,
    320,
    1580,
    365,
)  # 金額の行だけ。拡大して読むと「15」が信頼度 1.0 で読める
AUCTION_CASH_BOX = (870, 130, 1400, 190)
AUCTION_TITLE_BOX = (790, 385, 995, 435)  # 競りの土地のカードの名前(例: PENNSYLVANIA AVE.)
AUCTION_TITLE_BOX_TRANSPORT = (
    780,
    470,
    1010,
    540,
)  # 鉄道・会社のカードの名前(街より下。例: PENNSYLVANIA RAILROAD)
AUCTION_VALUE_BOX = (
    960,
    480,
    1250,
    700,
)  # 「Original Value: M320」。カードの長さで上下に動くので、広く取る
MIN_CONF = 0.85
FRAME_AGREE_CONF = 0.70
YELLOW_MIN_FRACTION = 0.03  # 「Highest bid:」の黄色い枠がある、とみなす面積の割合


@dataclass(frozen=True)
class OcrText:
    text: str
    confidence: float


class TextOcr(Protocol):
    def read_box(
        self, image: NDArray[np.uint8], box: tuple[int, int, int, int]
    ) -> list[OcrText]: ...


@dataclass(frozen=True)
class PurchaseOffer:
    square: str  # 盤の名前に合わせた土地名
    price: int


_PURCHASE = re.compile(r'Purchase\s*[:;]?\s*"?(.+?)"?\s*for\s*[MA]?\s*(\d+)\s*\??$', re.I)


def read_purchase(image: NDArray[np.uint8], ocr: TextOcr) -> PurchaseOffer | None:
    """購入画面の土地名と価格。読めない、土地名が盤に無い、信頼度が低い、は None。"""
    items = [i for i in ocr.read_box(image, PURCHASE_BOX) if i.confidence >= MIN_CONF]
    # OCR が「Purchase」と残りに分けて返すことがある(実機)。個別の行と、つなげた行の両方を試す
    texts = [i.text.strip() for i in items]
    if len(texts) > 1:
        texts.append(" ".join(texts))
    for text in texts:
        match = _PURCHASE.search(text)
        if not match:
            continue
        square = match_square(match.group(1))
        if square is None:
            return None
        from bglm.plugins.monopoly.logic.catalogue import CATALOGUE

        price = int(match.group(2))
        if CATALOGUE[square].price != price:
            return None  # 定価と合わない読み(誤読の疑い)では、買わない
        return PurchaseOffer(square, price)
    return None


@dataclass(frozen=True)
class AuctionView:
    highest_bid: int | None  # 誰も入札していなければ 0。読めなければ None
    cash_self: int | None
    cash_ai: int | None
    # 通貨記号(₼)が「A4」のように化けて、先頭に 4 が残ることがある(実機: ₼56 が「A456」)。読みの数字の列
    cash_digits: tuple[str, ...] = ()


def read_auction(image: NDArray[np.uint8], ocr: TextOcr) -> AuctionView:
    """オークションの最高入札額と、両者の所持金。読めない項目は None(推測で 0 などにしない)。"""
    bid = _read_bid(
        ocr.read_box(image, AUCTION_BID_BOX), ocr.read_box(image, AUCTION_BID_AMOUNT_BOX)
    )
    cash_texts = [
        m.group(1)
        for item in ocr.read_box(image, AUCTION_CASH_BOX)
        if item.confidence >= MIN_CONF and (m := re.fullmatch(r"[MA]{0,2}(\d+)", item.text.strip()))
    ]
    cash = [int(d) for d in cash_texts]
    if bid is None and not ocr.read_box(image, AUCTION_BID_BOX) and not _has_bid_frame(image):
        bid = 0  # 誰も入札していないと、「Highest bid:」の黄色い枠そのものが出ない(実機 2026-11-07)
    return AuctionView(
        bid,
        cash[0] if len(cash) >= 1 else None,
        cash[1] if len(cash) >= 2 else None,
        tuple(cash_texts),
    )


def auction_cash_digits(image: NDArray[np.uint8], ocr: TextOcr) -> list[str]:
    """競りの画面の上部にある所持金の読みから、数字だけを取り出す(ノイズや低い信頼度でも)。

    通常の読み取りで両者の現金が確定しないとき、台帳の値との照合に使う。
    """
    out: list[str] = []
    for item in ocr.read_box(image, AUCTION_CASH_BOX):
        if item.confidence >= 0.6:
            digits = re.sub(r"\D", "", item.text)
            if digits:
                out.append(digits)
    return out


def _has_bid_frame(image: NDArray[np.uint8]) -> bool:
    """「Highest bid:」の黄色い枠が出ているか。"""
    x0, y0, x1, y1 = AUCTION_BID_BOX
    b, g, r = (image[y0:y1, x0:x1, c].astype(int) for c in range(3))
    yellow = (r > 200) & (g > 180) & (b < 90)
    return float(yellow.mean()) >= YELLOW_MIN_FRACTION


_ABBREVIATIONS = (("ave.", "avenue"), ("pl.", "place"), ("r.r.", "railroad"))


_NOISE_WORDS = ("ent", "rent")


def _match_title(lines: list[OcrText]) -> str | None:
    """カードの題名の行から、土地を求める。題名は 1 行のことも、「NO.」と「CAROLINAAVE.」のように分かれることもある。

    「TITLE DEED」や賃料の行も混ざるので、個別の行と、つなげた行の両方を試す。
    """
    texts = [it.text for it in lines if it.text.strip().lower() not in _NOISE_WORDS]
    candidates = list(texts)
    if len(texts) > 1:
        candidates.append(" ".join(texts))
        candidates.append(" ".join(texts[1:]))
        candidates.append(" ".join(texts[:2]))
    for text in candidates:
        name = text.lower().strip()
        name = re.sub(r"no\.", "north", name)
        name = re.sub(r"ave\.?$", " avenue", name)
        for short, full in _ABBREVIATIONS:
            name = name.replace(short, full)
        if (found := match_square(name)) is not None:
            return found
    return None


def _title_fragments(ocr: TextOcr, image: NDArray[np.uint8]) -> list[str]:
    """題名の枠の、英字 3 文字以上の行(断片)。「TITLE DEED」や「AVE.」のような、土地を決めない語は除く。"""
    stop = {"ave", "avenue", "place", "title", "deed", "rent"}
    out: list[str] = []
    for it in ocr.read_box(image, AUCTION_TITLE_BOX):
        letters = re.sub(r"[^a-z]", "", it.text.lower())
        if it.confidence >= 0.8 and len(letters) >= 3 and letters not in stop:
            out.append(letters)
    return out


def _match_fragment(fragments: list[str], prices: list[int]) -> str | None:
    """題名の断片(例: 「IND」)で始まる土地のうち、定価が「Original Value」と一致するものが 1 つだけなら、それを返す。

    矢印などが題名を隠して、一部しか読めないとき(実機: Indiana Avenue が「IND」「AVE.」)の補助。
    `l` と `i` は、OCR が取り違える。
    """
    from bglm.plugins.monopoly.logic.catalogue import CATALOGUE

    def fold(s: str) -> str:
        return re.sub(r"[^a-z]", "", s.lower()).replace("l", "i")

    found = {
        name
        for name, deed in CATALOGUE.items()
        if deed.price in prices and any(fold(name).startswith(fold(f)) for f in fragments)
    }
    return next(iter(found)) if len(found) == 1 else None


def _value_digits(items: list[OcrText]) -> list[int]:
    """「Original Value: ₼350」の定価。広い枠には賃料などの数字も入るので、「Value」を含む行(または、その次の行)だけ見る。"""
    digits: list[int] = []
    for k, i in enumerate(items):
        if i.confidence < 0.8 or "value" not in i.text.lower():
            continue
        same = re.search(r"(\d{2,3})\s*$", i.text.strip())
        if same:
            digits.append(int(same.group(1)))
        elif k + 1 < len(items) and (
            nxt := re.fullmatch(r"\D?(\d{2,3})", items[k + 1].text.strip())
        ):
            digits.append(int(nxt.group(1)))
    return digits


def read_auction_square(image: NDArray[np.uint8], ocr: TextOcr) -> str | None:
    """競りの画面のカードから、土地を読む。名前を盤に合わせ、「Original Value」が定価と一致するときだけ返す。

    見送りの行は、競りの間は Log を読めないので、画面のカードが、土地を知る手段になる。
    """
    from bglm.plugins.monopoly.logic.catalogue import CATALOGUE

    lines = [it for it in ocr.read_box(image, AUCTION_TITLE_BOX) if it.confidence >= 0.8]
    square = _match_title(lines)
    if square is None:  # 鉄道・会社は、題名の位置が違う
        transport = ocr.read_box(image, AUCTION_TITLE_BOX_TRANSPORT)
        square = _match_title([it for it in transport if it.confidence >= 0.8])
    prices = _value_digits(ocr.read_box(image, AUCTION_VALUE_BOX))
    if square is None:
        square = _match_fragment(_title_fragments(ocr, image), prices)
    if square is None or CATALOGUE[square].price not in prices:
        return None
    return square


def _read_bid(frame: list[OcrText], amount: list[OcrText]) -> int | None:
    """「Highest bid:」の枠。金額は、その下の行に出る。

    - 枠の文字(Highest)を読めなければ None(枠を読めていない)
    - 金額の行(専用の領域)に、信頼度が足りる数字があれば、その金額
    - 金額の行に数字らしいものがあるが、信頼度が低いときは None(読めなかった。0 と取り違えない)
    - 金額の行に何も無ければ、まだ誰も入札していない(0)
    """
    if not any("highest" in t.text.lower() and t.confidence >= MIN_CONF for t in frame):
        return None
    numbers = [(i, re.fullmatch(r"\D?\s*(\d+)", i.text.strip())) for i in amount]
    numbers = [(i, m) for i, m in numbers if m]
    for item, match in numbers:
        if item.confidence >= MIN_CONF and match:
            return int(match.group(1))
    # 専用の領域の信頼度が低くても、枠全体の読みが高信頼で、同じ金額なら受け入れる(実機: 0.82 と 0.97 で M84)
    in_frame: set[int] = set()
    for i in frame:
        if (
            i.confidence < FRAME_AGREE_CONF
        ):  # 金額枠の読みと一致するときだけ使うので、下限は低めでよい
            continue
        if m := re.fullmatch(r"[MA*]{0,2}(\d+)", i.text.strip()):
            digits = m.group(1)
            in_frame.add(int(digits))
            # 通貨記号(₼)が「4」に化けることがある(実機: 「₼40」が「440」)。先頭の 4 を除いた値も、候補にする
            if len(digits) >= 2 and digits[0] == "4":
                in_frame.add(int(digits[1:]))
    low = {int(m.group(1)) for _i, m in numbers if m}
    agreed = in_frame & low
    if len(agreed) == 1 and len(low) == 1:
        return next(iter(agreed))
    return None if numbers else 0


class BoxOcr:
    """RapidOCR で、画面の指定した領域を読む。エンジンは、Log の読み取りと共有する(`toolkit/ocr_reader`)。"""

    SCALE = 2

    def read_box(self, image: NDArray[np.uint8], box: tuple[int, int, int, int]) -> list[OcrText]:
        return [OcrText(raw.text, raw.confidence) for raw in recognize(image, box, self.SCALE)]
