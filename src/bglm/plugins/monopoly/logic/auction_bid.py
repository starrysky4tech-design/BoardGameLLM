"""実機のオークションで、入札する額を決める(画面には依存しない)。

規則: 相手は、自分の現金までしか入札できない。相手の現金と同額で入札すれば、相手は「それより高い額」を
入れる必要があるが、持っていないので上回れない。したがって、落札に必要な最小の額は、
max(いまの最高入札額 + 1, 相手の現金)。ただし、相手の現金が最高入札額より少ないなら、最高入札額 + 1。
(2026-11-05 の指示。実機で St. James Place を、Dog の現金 ₼65 と同額の入札で落札した)

自分の上限(価値と、残す現金)は、呼び出し側が渡す。

落札を強いられない(相手の現金が多い)ときも、すぐには降りない。上限の範囲で、入札を少しずつ重ねる
(`raising_bid`)。相手が降りれば、上限以下で落札でき、相手が上回り続ければ、相手に、その分を払わせた
うえで、降りる(2026-11-05 の指示: 降りるときでも、相手の金をできるだけ使わせる)。
"""

RAISE_STEPS = (
    8  # 上限までを、この回数ほどで上がる刻みにする(1 回の入札は、キーパッドの操作で約 15 秒かかる)
)
RAISE_STEP_MIN = 10


def winning_bid(
    highest_bid: int,
    opponent_cash: int,
    my_limit: int,
    my_cash: int,
) -> int | None:
    """落札できる最小の入札額。上限・現金に届かないなら None。

    highest_bid: いまの最高入札額(誰も入札していなければ 0)
    opponent_cash: 相手の現金
    my_limit: 方針が許す上限(価値、残す現金を考慮済み)
    my_cash: 自分の現金
    """
    need = max(highest_bid + 1, opponent_cash)
    if opponent_cash < highest_bid + 1:
        need = highest_bid + 1  # 相手はもう届かない。最高入札額を 1 上回れば足りる
    if need > my_limit or need > my_cash:
        return None
    return need


def raising_bid(highest_bid: int, my_limit: int, my_cash: int) -> int | None:
    """相手に払わせるための入札額。最高入札額に刻みを足した額(上限・現金を超えない)。上限に届かなければ None(降りる)。

    刻みは、上限の 1/8(最小 ₼10)。
    """
    step = max(RAISE_STEP_MIN, my_limit // RAISE_STEPS)
    bid = min(highest_bid + step, my_limit, my_cash)
    return bid if bid > highest_bid else None


# --- 相手の入札の上限の推定を使う入札(logic/opponent_model.py) ---

DRAIN_MARGIN = (
    0.10  # (仮)推定の上限から、この割合を引いた額まで吊り上げる(外れて、落札してしまう危険を減らす)
)
DRAIN_MARGIN_CONSERVATIVE = (
    0.30  # (仮)推定が不明(相手の現金の全額)のとき。相手が全額まで入札するとは限らない
)
DRAIN_MAX_REGRET = (
    0.10  # (仮) 落札した場合の損(入札額 − 自分にとっての価値)の、定価に対する割合の上限
)


def probe_bid(
    highest_bid: int, ceiling: int, my_limit: int, my_cash: int, opponent_cash: int
) -> int | None:
    """相手の上限の推定のすぐ上から入札する額。相手の現金と同額で入札するより安く、落札できる見込みがある。

    次のとき None(呼び出し側が、相手の現金と同額の入札(`winning_bid`)に戻る):
    推定の上が、相手の現金と同額以上(安くならない)、自分の上限・現金を超える、最高入札額を上回らない。
    外れて、相手が上回ってきたら、次の入札で `winning_bid` に戻れる(相手の現金までなら、自分の上限の範囲で落札できる)。
    """
    bid = max(highest_bid + 1, ceiling + 1)
    if bid >= opponent_cash or bid > my_limit or bid > my_cash:
        return None
    return bid


def drain_bid(
    highest_bid: int,
    ceiling: int,
    my_cash: int,
    keep: int,
    my_value: float,
    deed_price: int,
    conservative: bool,
) -> int | None:
    """自分が落札したくない(できない)とき、相手に払わせるための入札額。上限を超えない範囲で、刻みを足す。

    上限(次の最小):
    - 相手の上限の推定から、余裕(`DRAIN_MARGIN`)を引いた額
    - 自分の現金から、残す現金を引いた額(誤って落札しても、残す現金を割らない)
    - 自分にとっての価値に、許す損(定価の `DRAIN_MAX_REGRET`)を足した額
    届かなければ None(降りる)。2026-11-05 の指示「降りるときでも、相手の金をできるだけ使わせる」を、推定で広げた。
    """
    margin = DRAIN_MARGIN_CONSERVATIVE if conservative else DRAIN_MARGIN
    cap = min(
        round(ceiling * (1 - margin)),
        my_cash - keep,
        int(my_value + DRAIN_MAX_REGRET * deed_price),
    )
    step = max(RAISE_STEP_MIN, cap // RAISE_STEPS)
    bid = min(highest_bid + step, cap)
    return bid if bid > highest_bid else None
