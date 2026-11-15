"""Monopoly の実行ループ(1 画面ずつ、判別 → 判断 → 操作)。

共通基盤の `AgentRunner`(1 手ごとに認識 → 合法手 → 戦略 → 実行)は、盤面ゲーム向け。Monopoly は、手番の中に
Roll、購入、オークション、取引、カードが割り込むため、画面の種類ごとに処理を分けた、専用の薄いループにする。

1 回の `step` は、画面を 1 つ判別して、操作を高々 1 つ送り、結果(`StepResult`)を返す。次の場合は、入力を送らず止める:
- 画面の色が通常と違う(端末の色補正)。色に頼る読み取りが誤る
- 想定外・未知の画面
- 人の判断が要る画面(保釈の判断の基準が未決、取引を受ける流れが未確認、Forfeit の位置が未確認、など)
- 読み取りが不確実(購入の土地名、オークションの最高入札額、Log の取りこぼし)

位置は、毎手番の終わりに Log を読み、`PositionTracker` で追う。食い違い・読めない行・取りこぼしは、止める理由として返す。
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum

import numpy as np
from numpy.typing import NDArray

from bglm.core.models import ExecutionResult, Point, Tap
from bglm.plugins.monopoly.logic import events as ev
from bglm.plugins.monopoly.logic import rules
from bglm.plugins.monopoly.logic.board import POSITION_OF
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE
from bglm.plugins.monopoly.logic.decisions import Decider, LiveState
from bglm.plugins.monopoly.logic.events import AuctionStarted, LogEvent, UnknownLine
from bglm.plugins.monopoly.logic.funding import FundingStep, StepKind, next_step
from bglm.plugins.monopoly.logic.jail import JailAction
from bglm.plugins.monopoly.logic.ledger import BAIL_FEE
from bglm.plugins.monopoly.logic.log_replay import PositionTracker
from bglm.plugins.monopoly.logic.models import MonopolyState, Player
from bglm.plugins.monopoly.logic.policies import group_return_factor
from bglm.plugins.monopoly.logic.trade_advisor import Verdict
from bglm.plugins.monopoly.vision import builder
from bglm.plugins.monopoly.vision import executor as ex
from bglm.plugins.monopoly.vision import navigation as nav
from bglm.plugins.monopoly.vision import property_manager as pm
from bglm.plugins.monopoly.vision.cash import read_cash
from bglm.plugins.monopoly.vision.dialog_reader import (
    TextOcr,
    auction_cash_digits,
    read_auction,
    read_auction_square,
    read_purchase,
)
from bglm.plugins.monopoly.vision.log_reader import (
    LOG_CLOSE,
    LogCursor,
    Ocr,
    read_recent,
    read_until_joined,
)
from bglm.plugins.monopoly.vision.ownership import ZOOM_RETURN
from bglm.plugins.monopoly.vision.roll_reader import RollWatcher, roll_with_dice
from bglm.plugins.monopoly.vision.screens import (
    classify,
    color_is_normal,
    has_post_bail,
    has_use_card,
)
from bglm.plugins.monopoly.vision.trade_reader import read_trade_offer


class Outcome(Enum):
    ACTED = "acted"  # 操作を送った
    WAITED = "waited"  # 何もせず、待つ(AI の手番など)
    STOPPED = "stopped"  # 入力を送らず止めた。reason を確認する


@dataclass(frozen=True)
class StepResult:
    outcome: Outcome
    screen: str
    action: str = ""  # 送った操作の名前
    reason: str = ""  # STOPPED のときの理由


@dataclass
class Agent:
    """実行ループの状態と部品。実機の入出力は driver に入っている(テストでは偽物)。"""

    driver: ex.Driver
    decider: Decider
    log_ocr: Ocr
    box_ocr: TextOcr
    positions: PositionTracker
    state: MonopolyState  # 所有・家・所持金。起動時に画面から読み直したもの(今は呼び出し側が渡す)
    cursor: LogCursor = field(default_factory=LogCursor)
    events: list[LogEvent] = field(default_factory=list)  # 読んだ Log の出来事(新しい順に追加)
    sleep: Callable[[float], None] = lambda _s: None
    current_auction: str | None = (
        None  # いま進行中の競りの土地(自分が見送った直後に入る。盤に戻ると消える)
    )
    jail_cards: int = 0  # 自分が持つ釈放カードの枚数(Log の行が未確認のため、手で渡す)
    unknown_waits: int = 0  # 画面が分からない状態の連続回数(盤に戻ると 0)
    refused_trades: set[str] = field(
        default_factory=set
    )  # 取引を持ちかけられなかった(操作が未実装の)土地。手番ごとに空にする
    built_groups: set[str] = field(
        default_factory=set
    )  # この手番に建てた色グループ(各 1 回。状態の更新は Log の読み取りで行う)
    auction_bids: int = (
        0  # いまの競りで、自分が入札した回数(最初の入札だけ、相手の上限の推定を使う)
    )
    last_bid: int = 0  # いまの競りで、自分が最後に入札した額(これを超える最高入札額は、相手の入札)
    image: NDArray[np.uint8] | None = (
        None  # `step` が画面の判別に取得した画像。ハンドラーが、取り直さずに読む
    )

    def live(self) -> LiveState:
        return LiveState(
            self.state,
            dict(self.positions.positions),
            frozenset(self.positions.in_jail),
            jail_cards=self.jail_cards,
            jail_failed=self.positions.jail_fails.get(Player.SELF, 0),
            jail_fails=dict(self.positions.jail_fails),
        )


def _current(agent: Agent) -> NDArray[np.uint8]:
    """いまの画面の画像。`step` が判別に取得した画像を使う(同じ画面を、約 2 秒かけて取り直さない)。"""
    if agent.image is not None:
        return agent.image
    image: NDArray[np.uint8] = agent.driver.io.capture().image
    return image


def step(agent: Agent) -> StepResult:
    """画面を 1 つ判別して、操作を高々 1 つ送る。"""
    image = agent.driver.io.capture().image
    agent.image = image
    screen = classify(image).name
    if screen in ("board_my_turn_roll", "board_my_turn_end", "board_debt") and not color_is_normal(
        image
    ):
        return StepResult(
            Outcome.STOPPED,
            screen,
            reason="画面の色が通常と違う(端末の色補正の疑い)。読み取りが誤る",
        )

    if screen not in ("auction", "unknown", "confirm_dialog", "bid_keypad"):
        agent.current_auction = None
        agent.auction_bids = 0
        agent.last_bid = 0
    if screen != "unknown":
        agent.unknown_waits = 0
    handler = _HANDLERS.get(screen)
    if handler is None:
        return StepResult(Outcome.STOPPED, screen, reason=f"想定外の画面: {screen}")
    return handler(agent, screen)


def _build_before_end(agent: Agent, screen: str) -> StepResult | None:
    """End Turn の直前に、方針が建てると判断した家を建てる。建てる物が無ければ None(続けて End Turn)。

    Roll の後(止まって払った・買った後)の現金で判断し、建てた直後に相手が動く。相手の位置は、手番の最初に読んだ
    Log で分かっている(相手は、自分の手番の間は動かない)。

    建てる色グループは、土地の評価(`group_return_factor`)が高い順に 1 つずつ。+ の位置が未登録の色グループが、
    建てる対象のうち最も評価が高いときは、評価の低い色グループを先に建てず、見送る(2026-11-08 の指示:
    オレンジは緑より効果的。登録済みの低い評価の色グループが先に建つのを防ぐ)。
    """

    wanted = agent.decider.builds(agent.live())
    by_group: dict[str, dict[str, int]] = {}
    for square, count in wanted.items():
        by_group.setdefault(CATALOGUE[square].group, {})[square] = count
    factor = group_return_factor()
    for group in sorted(by_group, key=lambda g: -factor[g]):
        if group in agent.built_groups:
            continue
        if group not in builder.PLUS:
            return None  # 評価が最も高い対象が、位置未登録。低い評価の色グループを先に建てない
        plan = by_group[group]
        agent.built_groups.add(group)
        result = builder.build_group(agent.driver, group, plan)
        if not result.success:
            return StepResult(Outcome.STOPPED, screen, reason=result.reason or "建設に失敗した")
        _apply_own_action(agent, "build", plan)
        return StepResult(Outcome.ACTED, screen, f"build {group} {plan}")
    return None


def _apply_own_action(agent: Agent, kind: str, plan: dict[str, int]) -> None:
    """自分の操作(建設・抵当・売却)の結果を、状態へ反映する(Log の行は OCR で崩れるので、行には頼らない)。

    Log の同じ行は、`own_action_events` で読み取り側が捨てる(二重に数えない)。ルール上できない(例外)なら、
    反映しない(画面の現金との照合で、食い違いとして見つかる)。
    """

    position_of = POSITION_OF
    state = agent.state
    # 家は均等に建てる・売る規則があるので、土地ごとにまとめず、規則を満たす土地から 1 軒ずつ反映する
    # (実機の画面は最終状態だけを検査するので、操作の順とは別に、状態の更新は規則を通る順に行う)
    operate = {"build": rules.build, "mortgage": rules.mortgage}.get(kind, rules.sell_house)
    remaining = {n: c for n, c in plan.items() if c > 0}
    while remaining:
        for name in sorted(remaining, key=lambda n: -position_of[n]):
            try:
                state = operate(state, CATALOGUE, Player.SELF, name)
            except ValueError:
                continue
            remaining[name] -= 1
            if remaining[name] == 0:
                del remaining[name]
            break
        else:
            return  # どの土地も規則上できない。反映しない(画面の現金との照合で見つかる)
    agent.state = state


def own_action_events(events: list[LogEvent]) -> list[LogEvent]:
    """読み取った Log から、自分の建設・抵当・売却の行を除く(実行側で、操作の結果として反映済みのため)。"""

    own = (ev.HousesBuilt, ev.HotelBuilt, ev.HousesSold, ev.Mortgaged)
    return [
        e
        for e in events
        if not (isinstance(e, own) and e.player is Player.SELF)
        and not isinstance(e, ev.TradeResult)
    ]


def _fund_before_roll(agent: Agent, screen: str, force: bool = False) -> StepResult | None:
    """Roll の前に、次の 1 手の最悪の支払いに現金が足りないとき、資金調達(logic/funding.py)の 1 手を実行する。

    取引(抵当に入れたままの取引を持ちかける)は、操作が未実装なので、飛ばす(その手番は再び選ばない)。
    1 回の呼び出しで 1 手。状態の更新は、Log の行(抵当・売却)から、実行ループが行う。
    """

    def next_step_now() -> FundingStep | None:
        if force:  # 負債のメニュー: 所持金が負、または、刑務所で保釈金に足りない。不足の額は問わず、調達する
            return next_step(agent.state, CATALOGUE, Player.SELF, frozenset(agent.refused_trades))
        return agent.decider.funding_step(agent.live(), frozenset(agent.refused_trades))

    step = next_step_now()
    while step is not None and step.kind is StepKind.TRADE_MORTGAGED:
        agent.refused_trades.add(step.name)  # 取引の提案の操作は未実装。次の手へ
        step = next_step_now()
    if step is None:
        return None
    if step.kind is StepKind.MORTGAGE:
        result = pm.mortgage(agent.driver, step.name, agent.box_ocr)
        if (
            result.success
        ):  # Log の行は OCR で崩れることがあるので、状態は、操作の成功ですぐ更新する
            _apply_own_action(agent, "mortgage", {step.name: 1})
        reason = result.reason or ""
        if not result.success and (
            "すでに抵当済み" in reason
            or (
                "確認の本文が期待(mortgage)と合わない" in reason
                and "unmortgage" in reason.lower().replace(" ", "")
            )
        ):
            # 画面は、すでに抵当済み(ボタンが Unmortgage、または確認が「解除」を問うた)。記録の誤りなので、旗を直して、
            # 次の手へ(押した操作は取り消し済み)
            holdings = dict(agent.state.holdings)
            holdings[step.name] = replace(holdings[step.name], mortgaged=True)
            agent.state = replace(agent.state, holdings=holdings)
            return StepResult(Outcome.ACTED, screen, f"fix_mortgaged_flag {step.name}")
        return _do(result, screen, f"mortgage {step.name}")
    deed = CATALOGUE[step.name]
    result = pm.sell_houses(agent.driver, deed.group, {step.name: 1})
    if result.success:
        _apply_own_action(agent, "sell", {step.name: 1})
    return _do(result, screen, f"sell_house {step.name}")


def _roll(agent: Agent, screen: str) -> StepResult:
    if (
        Player.SELF in agent.positions.in_jail
    ):  # 刑務所のときだけ、メニューを確かめる(通常の手番は、取得しない)
        image = agent.driver.io.capture().image
        if has_post_bail(image) or has_use_card(image):
            agent.jail_cards = (
                1 if has_use_card(image) else 0
            )  # メニューの Use Card で、釈放カードの有無が分かる
            action = agent.decider.jail_action(agent.live())
            if action is JailAction.PAY_BAIL:
                return _do(ex.pay_bail(agent.driver), screen, "post_bail")
            if action is JailAction.USE_CARD:
                return _do(ex.use_jail_card(agent.driver), screen, "use_jail_card")
    watcher = RollWatcher(agent.driver)
    outcome = roll_with_dice(agent.driver, watcher)
    if outcome.read.values is not None:
        return StepResult(Outcome.ACTED, screen, f"roll {outcome.read.total}")
    if outcome.reason == "結果の表示が割り込んだ":
        return StepResult(Outcome.ACTED, screen, "roll(結果の表示が割り込んだ)")
    return StepResult(Outcome.STOPPED, screen, reason=outcome.reason or outcome.read.reason)


def _end_turn(agent: Agent, screen: str) -> StepResult:
    funded = _fund_before_roll(agent, screen)  # 止まって払った後の負債があれば、調達してから終える
    if funded is not None:
        return funded
    built = _build_before_end(
        agent, screen
    )  # 払い・購入を終えた現金で建てる(建てた直後に、相手が動く)
    if built is not None:
        return built
    agent.built_groups.clear()
    agent.refused_trades.clear()
    result = ex.end_turn(agent.driver)
    if not result.success:
        return StepResult(
            Outcome.STOPPED, screen, reason=result.reason or "End Turn が反映されない"
        )
    return StepResult(Outcome.ACTED, screen, "end_turn")


def _card(agent: Agent, screen: str) -> StepResult:
    result = ex.close_card(agent.driver)
    if not result.success:
        return StepResult(Outcome.STOPPED, screen, reason=result.reason or "カードが閉じない")
    return StepResult(Outcome.ACTED, screen, "close_card")


def _pass(agent: Agent, screen: str, square: str, note: str) -> StepResult:
    """見送る。成功したら、競りの土地を記録する(競りの画面では Log を読めないため)。"""

    result = ex.pass_on_purchase(agent.driver)
    if result.success:
        agent.events.append(AuctionStarted(Player.SELF, square))
        agent.current_auction = square
    return _do(result, screen, f"pass {square}{note}")


def _buy_dialog(agent: Agent, screen: str) -> StepResult:
    image = _current(agent)
    offer = read_purchase(image, agent.box_ocr)
    if offer is None:
        return StepResult(
            Outcome.STOPPED, screen, reason="購入画面の土地名・価格を読めない(推測で買わない)"
        )
    cash = agent.state.cash[Player.SELF]
    if offer.price > cash:
        return _pass(agent, screen, offer.square, "(現金不足)")
    if agent.decider.buy(agent.live(), offer.square):
        return _do(ex.buy(agent.driver), screen, f"buy {offer.square}")
    return _pass(agent, screen, offer.square, "")


def _trust_ledger(read: int | None, ledger: int) -> int | None:
    """読みの現金が、台帳の値の前に 1 桁の余計な数字が付いた形なら、台帳の値を返す(₼ が数字に化ける。実機: ₼56 が 456)。

    台帳と大きく違う読み(桁違い)は、そのまま返す。
    """
    if (
        read is not None
        and read != ledger
        and str(read).endswith(str(ledger))
        and len(str(read)) == len(str(ledger)) + 1
    ):
        return ledger
    return read


def _auction(agent: Agent, screen: str) -> StepResult:
    image = _current(agent)
    view = read_auction(image, agent.box_ocr)
    if view.highest_bid is None:
        return StepResult(Outcome.STOPPED, screen, reason="最高入札額を読めない(推測で入札しない)")
    cash_self, cash_ai = view.cash_self, view.cash_ai
    # 読みの現金は、台帳の現金と照合する。台帳の値が、読みの末尾と一致するなら、台帳の値を使う(₼ が「A4」に化けて、
    # 先頭に 4 が残ることがある。実機: ₼56 が 456)。台帳と大きく違う読み(桁違い)は、そのまま使わない
    me, ai = agent.state.cash[Player.SELF], agent.state.cash[Player.AI]
    cash_self, cash_ai = _trust_ledger(cash_self, me), _trust_ledger(cash_ai, ai)
    if cash_self is None or cash_ai is None:
        # 読みがノイズ(例: M4259、M.77)でも、台帳の現金が、読みの末尾の数字と一致するなら、台帳の値を使う
        digits = auction_cash_digits(image, agent.box_ocr)
        me, ai = agent.state.cash[Player.SELF], agent.state.cash[Player.AI]
        if any(d.endswith(str(me)) for d in digits) and any(d.endswith(str(ai)) for d in digits):
            cash_self, cash_ai = me, ai
        else:
            return StepResult(Outcome.STOPPED, screen, reason="両者の所持金を読めない")
    # 競りの土地は、画面のカードから読む。読めなければ、この競りの直前に自分が見送った土地だけ使う。
    # Log の見送りの行は、競りの間は読めず、古い競りの行が残るので、使わない(実機で、取り違えの疑いが出た)
    square = read_auction_square(image, agent.box_ocr) or agent.current_auction
    if square is None:
        return StepResult(
            Outcome.STOPPED,
            screen,
            reason="オークションの土地が分からない(カードを読めず、見送りの記録も無い)",
        )
    agent.current_auction = square
    if (
        view.highest_bid > agent.last_bid
    ):  # 自分の最後の入札を超える最高入札額は、相手の入札(上限の下限の観測)
        agent.decider.bid_model.record_ai_bid(CATALOGUE[square].price, view.highest_bid)
    live = _with_cash(agent.live(), cash_self, cash_ai)
    amount = agent.decider.auction_bid(
        live, square, view.highest_bid, first=agent.auction_bids == 0
    )
    if amount is None:
        return _do(ex.forfeit(agent.driver), screen, f"forfeit {square}")
    if amount > cash_self:
        # 方針の不具合の疑い(入札額が、画面の自分の現金を超える)。実機で、現金 ₼56 に ₼197 を入札した。送らず止める
        return StepResult(
            Outcome.STOPPED,
            screen,
            reason=f"入札額 {amount} が、画面の自分の現金 {cash_self} を超える(方針の不具合の疑い)。送らない",
        )
    result = ex.bid(agent.driver, amount)
    if result.success:
        agent.auction_bids += 1
        agent.last_bid = amount
    return _do(result, screen, f"bid {amount} {square}")


def _trade(agent: Agent, screen: str) -> StepResult:
    """相手の取引の提案。画面から双方の提供を読み、基準(logic/trade_advisor.py)で答える。

    - 読めなければ断る(推測で受けない)
    - 受ける(ACCEPT)と判断したら、Accept Trade。成功したら、所有と現金を状態に反映する
      (Log の取引の行は未確認なので、状態は画面の操作から更新する)
    - 対案(COUNTER)と断る(DECLINE)は、断る。対案の操作(取引ウィンドウの編集)は実機で未確認のため、
      対案の内容は、動作の記録に残す
    """
    image = _current(agent)
    offer = read_trade_offer(image, agent.box_ocr)
    if offer is None:
        return _do(
            ex.respond_to_trade(agent.driver, accept=False), screen, "decline trade(画面を読めない)"
        )
    decision = agent.decider.respond_trade(agent.live(), Player.AI, offer)
    if decision.verdict is Verdict.ACCEPT:
        result = ex.respond_to_trade(agent.driver, accept=True)
        if result.success:
            agent.state = rules.apply_trade(agent.state, CATALOGUE, Player.AI, Player.SELF, offer)
        return _do(result, screen, f"accept trade({decision.reason})")
    note = f"{decision.verdict.value}: {decision.reason}"
    if decision.counter is not None:
        note += f" 対案={decision.counter}"
    return _do(ex.respond_to_trade(agent.driver, accept=False), screen, f"decline trade({note})")


def _close_log(agent: Agent, screen: str) -> StepResult:
    """Log が開いたまま(読み取りの途中で止まった)。閉じる。"""

    for _ in range(3):
        agent.driver.perform(Tap(LOG_CLOSE))
        agent.driver.sleep(2.0)
        if agent.driver.screen() != "log":
            return StepResult(Outcome.ACTED, screen, "close_log")
    return StepResult(Outcome.STOPPED, screen, reason="Log を閉じられない")


def _pay_bail_only(agent: Agent, screen: str) -> StepResult:
    """Roll が無く、Post Bail が一番上の刑務所のメニュー。保釈金(M50)を払う以外に進めない。現金が足りる(押せる)ときだけ。"""

    if agent.state.cash[Player.SELF] < BAIL_FEE:
        return StepResult(Outcome.STOPPED, screen, reason="保釈金に現金が足りない(資金調達が先)")
    return _do(ex.pay_bail_top(agent.driver), screen, "post_bail")


STATS_MAIN_MENU = Point(1257, 909)  # Game Statistics の Main Menu(実機 2026-11-08)
DICE_HISTORY_OK = Point(1254, 903)  # Dice Rolling History の OK(実機 2026-11-08)


NOTICE_OK = nav.NOTICE_OK  # 通知ダイアログ(OK だけ)の OK(実機で確認)


def _dismiss_notice(agent: Agent, screen: str) -> StepResult:
    """通知ダイアログ(「入札に現金が足りない」「建設済みの上限」など)。OK で閉じる。内容は、その直前の操作の失敗を示す。"""
    agent.driver.perform(Tap(NOTICE_OK))
    agent.driver.sleep(2.0)
    return StepResult(Outcome.ACTED, screen, "dismiss_notice")


def _game_over(agent: Agent, screen: str) -> StepResult:
    """対局が終わった(Game Statistics)。Main Menu へ戻る。新しい対局は、ユーザーの確認が要るので、ここで止める。

    終了の流れ(実機 2026-11-08、Resign の場合): 「<駒> WINS!!」の演出 → Dice Rolling History(OK)→ Game Statistics
    (Main Menu)。「WINS」の演出と Dice Rolling History は、画面の種類が「不明」で、待つだけ(固まれば、盤の余白のタップ)。
    """
    agent.driver.perform(Tap(STATS_MAIN_MENU))
    agent.driver.sleep(4.0)
    return StepResult(
        Outcome.STOPPED,
        screen,
        "game_over",
        "対局が終了した。Main Menu へ戻した。新しい対局は、ユーザーの確認が要る",
    )


def _debt(agent: Agent, screen: str) -> StepResult:
    """所持金がマイナス(負債のメニュー: Auto Sell / Resign)。資金調達(logic/funding.py)の 1 手を実行する。

    手が尽きたら止める(Auto Sell と Resign は、自動では押さない。Resign は、降参で対局が終わるため)。
    この画面では、Log を読めない(メニューが違う)。状態の現金は、画面の値で更新する。
    """

    image = _current(agent)
    seen = read_cash(image)
    if seen.me.value is not None:
        agent.state = replace(
            agent.state, cash={Player.SELF: seen.me.value, Player.AI: agent.state.cash[Player.AI]}
        )
    stepped = _fund_before_roll(agent, screen, force=True)
    if stepped is not None:
        return stepped
    return StepResult(
        Outcome.STOPPED,
        screen,
        reason="負債(または保釈金不足)が残り、資金調達の手が尽きた。Auto Sell か Resign は、人が決める",
    )


def _return_from_improvements(agent: Agent, screen: str) -> StepResult:
    """建設画面が開いたまま(読み直しの中断など)。Return で戻す。Return で確認が出たら(確定前の変更がある)、止める。"""

    agent.driver.perform(Tap(ZOOM_RETURN))
    agent.driver.sleep(2.5)
    now = agent.driver.screen()
    if now == "confirm_dialog":
        return StepResult(
            Outcome.STOPPED,
            screen,
            reason="建設画面の Return で確認が出た(確定前の変更がある)。内容を確かめる",
        )
    return StepResult(Outcome.ACTED, screen, "return_from_improvements")


def _return_from_zoom(agent: Agent, screen: str) -> StepResult:
    """拡大盤が開いたまま(操作の途中で開いた)。Return で盤へ戻す。戻るたびに画面を確かめ、戻らなければ止める。"""
    if nav.return_to_board(agent.driver):
        return StepResult(Outcome.ACTED, screen, "return_from_zoom")
    return StepResult(Outcome.STOPPED, screen, reason="拡大盤から戻れない")


def _stop(reason: str) -> Callable[[Agent, str], StepResult]:
    def handler(_agent: Agent, screen: str) -> StepResult:
        return StepResult(Outcome.STOPPED, screen, reason=reason)

    return handler


WAKE_AFTER_WAITS = (
    8  # 画面が分からない状態がこの回数続いたら、盤の中央を 1 回タップして、固まった演出を進める
)
WAKE_POINT = Point(
    1900, 420
)  # 盤の右の余白(メニュー・ボタンに当たらない)。ダイスの演出で固まったとき、盤の中央のタップで進んだ(2026-11-08)
PAUSE_RESUME = Point(
    1255, 869
)  # ポーズ画面の Resume の緑のチェック(実機で確認 2026-11-08。ラベルの位置は効かない)


def _resume_from_pause(agent: Agent, screen: str) -> StepResult:
    """ポーズ画面(Options / Save & Exit / Abandon Game がある)。Resume だけを押して戻す。他のボタンは押さない。"""
    for _ in range(2):
        agent.driver.perform(Tap(PAUSE_RESUME))
        agent.driver.sleep(2.5)
        if agent.driver.screen() != "pause":
            return StepResult(Outcome.ACTED, screen, "resume_from_pause")
    return StepResult(Outcome.STOPPED, screen, reason="ポーズ画面から戻れない")


def _wait(agent: Agent, screen: str) -> StepResult:
    agent.unknown_waits += 1
    if agent.unknown_waits % WAKE_AFTER_WAITS == 0:
        agent.driver.perform(Tap(WAKE_POINT))
    agent.sleep(3.0)
    return StepResult(Outcome.WAITED, screen)


def _do(result: ExecutionResult, screen: str, action: str) -> StepResult:
    if result.success:
        return StepResult(Outcome.ACTED, screen, action)
    return StepResult(Outcome.STOPPED, screen, action, result.reason or "操作が反映されない")


def _with_cash(live: LiveState, me: int, ai: int) -> LiveState:
    return replace(live, state=replace(live.state, cash={Player.SELF: me, Player.AI: ai}))


def read_new_events(agent: Agent, pages: int = 3) -> tuple[list[LogEvent], bool]:
    """Log を読み、新しい出来事と、取りこぼしの疑い(gap)を返す。盤の通常の画面だけで呼ぶ。"""
    if agent.cursor.has_history:
        reading = read_until_joined(agent.driver, agent.log_ocr, agent.cursor)
    else:
        reading = read_recent(agent.driver, agent.log_ocr, pages=pages)
    new, gap = agent.cursor.update(reading.events)
    agent.events.extend(new)
    return new, gap


def unknown_lines(events: list[LogEvent]) -> list[str]:
    return [e.text for e in events if isinstance(e, UnknownLine)]


# 画面 → 処理。ここに無い画面は、想定外として止める
_HANDLERS: dict[str, Callable[[Agent, str], StepResult]] = {
    "board_my_turn_roll": _roll,
    "board_my_turn_end": _end_turn,
    "board_debt": _debt,
    "board_jail_bail_only": _pay_bail_only,
    "card_dialog": _card,
    "buy_dialog": _buy_dialog,
    "auction": _auction,
    "trade": _trade,
    "jail_dialog": _stop("刑務所の判断(保釈・釈放カード・ダブル待ち)の基準が未決。人が決める"),
    "confirm_dialog": _stop("確認ダイアログが開いたまま(操作の途中で止まった)。内容を確かめる"),
    "bid_keypad": _stop("入札のキーパッドが開いたまま。内容を確かめる(誤入札を確定しない)"),
    "improvements": _return_from_improvements,
    "zoomed_board": _return_from_zoom,
    "log": _close_log,
    "game_statistics": _game_over,
    "ok_dialog": _dismiss_notice,
    "main_menu": _stop(
        "メインメニュー。対局が終了した(統計の後)、またはアプリが落ちた。新しい対局は、ユーザーの確認が要る"
    ),
    "pause": _resume_from_pause,
    "unknown": _wait,
}


UNKNOWN_LIMIT = 40  # 画面が分からない状態が、この回数続いたら止める(3 秒間隔で約 2 分)


def run(agent: Agent, max_steps: int = 200) -> StepResult:
    """止まるまで step を繰り返す。止まった理由(または上限到達)を返す。

    AI の手番の待ち(unknown)が、UNKNOWN_LIMIT 回続いたら、未知の画面とみなして止める。
    """
    unknown_streak = 0
    last = StepResult(Outcome.WAITED, "")
    for _ in range(max_steps):
        last = step(agent)
        if last.outcome is Outcome.STOPPED:
            return last
        unknown_streak = unknown_streak + 1 if last.screen == "unknown" else 0
        if unknown_streak >= UNKNOWN_LIMIT:
            return StepResult(
                Outcome.STOPPED,
                "unknown",
                reason=f"画面が分からない状態が {UNKNOWN_LIMIT} 回続いた",
            )
    return StepResult(Outcome.STOPPED, last.screen, reason=f"ステップの上限({max_steps})に達した")
