"""隠れた情報の標本化(02_DESIGN.md 論点 2)。

思考が見てはいけない情報(山札の並び、今後の乱数)を、標本で置き換える。
これをしないと、`apply` の結果が真の山札の上や乱数を反映し、思考が先を覗き見てしまう。
"""

import random
from dataclasses import replace

from bglm.plugins.wingspan.logic.state import WingspanState


def determinize(state: WingspanState, rng: random.Random) -> WingspanState:
    """山札の並びと乱数の種を、無作為に取り直した状態を返す。

    山札と捨て札は、同じ札の集まりのまま並びだけを変える(札の内訳は公開情報の範囲)。
    相手の手札は、評価に使わないので触らない(実機では中身が分からない)。
    """
    cards = list(state.deck)
    rng.shuffle(cards)
    return replace(state, deck=tuple(cards), seed=rng.getrandbits(31))
