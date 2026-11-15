r"""チャンスとコミュニティチェストのカード(各 16 枚)と、山札。

出典: カード一覧のキャプチャー(K:\monopoly_img\カード)。金額が一覧とゲーム内で違う 2 件は、
ゲーム内の表示を使う(株式売却 50、教育費 50)。ほかのカードは、引いたときに実機で確かめる。
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class CardKind(Enum):
    MOVE_TO = "move_to"  # target へ進む。GO を通る(戻らず進む)ときは給料を受け取る
    NEAREST_RAILROAD = "nearest_railroad"  # 次の鉄道へ。所有者がいれば賃料の 2 倍
    NEAREST_UTILITY = "nearest_utility"  # 次の会社へ。所有者がいればダイスの目の 10 倍
    BACK = "back"  # amount マス戻る(GO の給料は受け取らない)
    GET_OUT_OF_JAIL = "get_out_of_jail"  # 持っておいて、刑務所で使う
    GO_TO_JAIL = "go_to_jail"
    RECEIVE = "receive"  # 銀行から amount 受け取る
    PAY = "pay"  # 銀行へ amount 払う
    PAY_EACH = "pay_each"  # 各プレイヤーへ amount 払う
    COLLECT_EACH = "collect_each"  # 各プレイヤーから amount 受け取る
    REPAIRS = "repairs"  # 家 1 軒ごとに per_house、ホテル 1 軒ごとに per_hotel 払う


@dataclass(frozen=True)
class Card:
    kind: CardKind
    text: str
    amount: int = 0
    target: int = 0
    per_house: int = 0
    per_hotel: int = 0


CHANCE_CARDS: tuple[Card, ...] = (
    Card(CardKind.MOVE_TO, "ボードウォークへ進む", target=39),
    Card(CardKind.MOVE_TO, "イリノイ通りへ進む", target=24),
    Card(CardKind.MOVE_TO, "St. チャールズプレースへ進む", target=11),
    Card(CardKind.MOVE_TO, "リーディング鉄道に進む", target=5),
    Card(CardKind.NEAREST_RAILROAD, "次の鉄道まで進む(1/2)"),
    Card(CardKind.NEAREST_RAILROAD, "次の鉄道まで進む(2/2)"),
    Card(CardKind.NEAREST_UTILITY, "次の水道会社か電力会社に進む"),
    Card(CardKind.BACK, "3 マス戻る", amount=3),
    Card(CardKind.MOVE_TO, "GO に行き、200 貰う", target=0),
    Card(CardKind.GO_TO_JAIL, "刑務所に行く"),
    Card(CardKind.RECEIVE, "銀行より 150 ドル受け取る", amount=150),
    Card(CardKind.RECEIVE, "銀行より 50 ドル受け取る", amount=50),
    Card(CardKind.PAY, "銀行へ 15 ドル払う", amount=15),
    Card(CardKind.PAY_EACH, "各プレイヤーに 50 ドル払う", amount=50),
    Card(CardKind.REPAIRS, "修理代(家 25、ホテル 100)", per_house=25, per_hotel=100),
    Card(CardKind.GET_OUT_OF_JAIL, "刑務所から釈放される"),
)

COMMUNITY_CHEST_CARDS: tuple[Card, ...] = (
    Card(CardKind.RECEIVE, "銀行より 200 ドル受け取る", amount=200),
    Card(CardKind.RECEIVE, "生命保険満期により 100 ドル受け取る", amount=100),
    Card(CardKind.RECEIVE, "遺産を 100 ドル受け取る", amount=100),
    Card(CardKind.RECEIVE, "クリスマス基金の満期により 100 ドル受け取る", amount=100),
    Card(CardKind.RECEIVE, "株式売却により 50 ドル受け取る(一覧は 45、ゲーム内は 50)", amount=50),
    Card(CardKind.RECEIVE, "礼金として 25 ドル受け取る", amount=25),
    Card(CardKind.RECEIVE, "所得税 20 ドルが戻る", amount=20),
    Card(CardKind.RECEIVE, "ビューティーコンテスト準優勝、10 ドル受け取る", amount=10),
    Card(CardKind.COLLECT_EACH, "オペラのチケット代 50 ドルを各人から徴収", amount=50),
    Card(CardKind.MOVE_TO, "GO のマスへ進み、200 ドル受け取る", target=0),
    Card(CardKind.GO_TO_JAIL, "刑務所へ行く(200 ドルは受け取れない)"),
    Card(CardKind.PAY, "教育費として 50 ドル払う(一覧は 150、ゲーム内は 50)", amount=50),
    Card(CardKind.PAY, "出産費 100 ドル支払う", amount=100),
    Card(CardKind.PAY, "治療費 50 ドル支払う", amount=50),
    Card(CardKind.REPAIRS, "道路の修理費(家 40、ホテル 115)", per_house=40, per_hotel=115),
    Card(CardKind.GET_OUT_OF_JAIL, "刑務所から釈放される"),
)


class Deck:
    """山札。引いたカードは山の底へ戻る。釈放カードだけは、使うまで持ち主が持つ。"""

    def __init__(
        self,
        cards: Sequence[Card],
        rng: random.Random,
        order: Sequence[Card] | None = None,
    ) -> None:
        self._cards = list(order) if order is not None else list(cards)
        if order is None:
            rng.shuffle(self._cards)

    def draw(self) -> Card:
        card = self._cards.pop(0)
        if card.kind is not CardKind.GET_OUT_OF_JAIL:
            self._cards.append(card)
        return card

    def release(self, card: Card) -> None:
        """使った釈放カードを、山の底へ戻す。"""
        self._cards.append(card)
