"""相手(AI)の、競りでの入札の上限の推定(画面には依存しない)。

使い道: ① 購入画面で、定価で買うより競りの方が安く取れそうなとき、見送る ② 競りで、相手が止まりそうな額の少し上から
入札する(相手の現金と同額で入札するより安い) ③ 自分が買わない土地で、相手に高く買わせる。

**推定の根拠は、対局中の観測だけ**にする。既存の記録(`events_game2_easy_final.log`、`events_game3_veryeasy.log`)の
落札額は、自分が「相手の現金と同額」で入札した額と混ざっていて(相手の上限ではない)、相手の現金も記録に無い。
難易度ごとの値を、記録から決めることはできなかった(2026-11-10。`RESULT.md`)。観測が無い間は、保守的な値
(相手は現金の全額まで入札する)にして、現行の動作と同じにする。

観測の種類:
- 相手の入札: 相手が実際に入札した額 ÷ 定価。相手の上限の**下限**(それより上まで入札する)
- 相手の降り: 自分が落札した額 ÷ 定価(そのとき相手の現金が、その額を**超えて**いたもの)。相手の上限の**上限**
  (上回れたのに、入札しなかった)。相手の現金が足りなかった・同額だったときは、観測にならないので数えない

推定: 降りの観測があれば、その最小値と、入札の観測の最大値の大きい方。降りの観測が無ければ、不明(保守的)。
土地ごとに相手の評価は違う(独占に近づく土地は高く入札しうる)ので、推定は目安。外れたときは、呼び出し側が、
相手の現金と同額で入札する現行の方法に戻れる(落札できなくなる危険は、無い)。
"""

from dataclasses import asdict, dataclass, field


@dataclass
class BidModel:
    ai_bids: list[float] = field(default_factory=list)  # 相手が入札した額 ÷ 定価
    ai_stops: list[float] = field(
        default_factory=list
    )  # 自分の落札額 ÷ 定価(相手の現金が足りていたもの)
    max_samples: int = 40  # 古い観測を捨てる(1 局で、競りは多くて 20 回ほど)

    def record_ai_bid(self, deed_price: int, amount: int) -> None:
        if deed_price > 0 and amount > 0:
            self._add(self.ai_bids, amount / deed_price)

    def record_ai_stop(self, deed_price: int, my_price: int, ai_cash: int) -> None:
        """自分が my_price で落札した。相手の現金が my_price を超えていたなら、相手は、上回れたのに入札しなかった。

        現金が my_price と同額(自分が「相手の現金と同額」で入札した)なら、相手は上回れなかっただけで、観測にならない。
        """
        if deed_price > 0 and my_price > 0 and ai_cash > my_price:
            self._add(self.ai_stops, my_price / deed_price)

    def _add(self, values: list[float], ratio: float) -> None:
        values.append(ratio)
        del values[: -self.max_samples]

    @property
    def ratio(self) -> float | None:
        """相手の上限 ÷ 定価の推定。降りの観測が無ければ None(不明)。"""
        if not self.ai_stops:
            return None
        return max(min(self.ai_stops), max(self.ai_bids, default=0.0))

    @property
    def conservative(self) -> bool:
        return self.ratio is None

    def ceiling(self, deed_price: int, ai_cash: int) -> int:
        """相手がこの土地に入札する上限の推定。不明なら、相手の現金の全額。"""
        ratio = self.ratio
        if ratio is None:
            return ai_cash
        return min(ai_cash, round(ratio * deed_price))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "BidModel":
        bids, stops, limit = (
            data.get("ai_bids", []),
            data.get("ai_stops", []),
            data.get("max_samples", 40),
        )
        assert isinstance(bids, list) and isinstance(stops, list) and isinstance(limit, int)
        return cls([float(b) for b in bids], [float(s) for s in stops], limit)
