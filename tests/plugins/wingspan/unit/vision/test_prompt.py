"""案内の文言の判別テスト。OCR の文字列は、保存画面を日本語の認識モデルで読んだ実測(崩れ方もそのまま)。"""

from pathlib import Path

import cv2
import pytest

from bglm.plugins.wingspan.logic.models import Habitat, Placement
from bglm.plugins.wingspan.logic.state import (
    ConvertFoodTask,
    DrawBonusTask,
    DrawTask,
    EggBonusTask,
    GainFoodTask,
    LayEggsTask,
    PowersTask,
    SetupTask,
    TuckTask,
)
from bglm.plugins.wingspan.vision.ocr import JAPANESE_REC_MODEL, japanese_reader
from bglm.plugins.wingspan.vision.prompt import (
    PromptKind,
    classify_text,
    expected_prompts,
    phrase_score,
    read_prompt,
)

P = PromptKind
DATA = Path("datasets/raw/wingspan/feasibility")

# (OCR の実測, 期待する種類)
MEASURED = [
    ("鳥をタップして産卵してください。", P.LAY_EGGS),
    ("餌箱から館を選んでください。", P.PICK_DIE),  # 餌 → 館
    ("餌箱から館を選んでください / 1つ選ぶ", P.PICK_DIE),  # 2 種の目の小窓つき
    ("コスト / 払う / 変更", P.PAY_FOOD),
    ("コスト+ / 払う / 変更", P.PAY_FOOD),
    ("ユウガモ / 1枚カードを選ぶ。 / 残りカード:", P.PICK_CARD),  # 札名の断片が混ざる
    ("ユウガモ / 1枚カードを選ぶ. / 残りカード:", P.PICK_CARD),  # 「。」が「.」
    ("いすれかの生息地の鳥をタップして卵を使う。", P.PAY_EGGS),  # いずれか → いすれか
    ("オアマルドメ / いすれかの生息地の鳥をタップして卵を使う。", P.PAY_EGGS),
    ("ヒガシハイエボシガ-1 / 卵を捨てる / 23Mー捨てられた / 卵:", P.DISCARD_EGG),
    ("アンナハ / 手札からカードを差し込む。 / 13m / 残りカード:", P.TUCK),
    ("カードを捨てる / 息地のオ / 残りカード:", P.DISCARD_CARD),
    ("捨てる館を選ぶ。", P.DISCARD_FOOD),
    ("アカハシリュウキユウガモ / 鳥をプレイする生息地を選んでください。 / +1ć", P.CHOOSE_HABITAT),
    (
        "あなたは朗箱からつを1個獲得する。それをこの鳥 / の上に蓄えてもよい。 / を蓄えるを取る",
        P.POWER_FEEDER_CACHE,
    ),
    ("アンナ / を共通在庫から獲得してこの力一ドに蓄 / 13ćm-える。", P.POWER_GAIN_CACHE),
    ("アカハシリ / 2円を共通在庫から獲得してこの力一ドに蓄 / 76M-える。", P.POWER_GAIN_CACHE),
    ("アンナ / を共通在庫から獲得する。 / 13m", P.POWER_GAIN),
    ("を共通在庫から獲得する。 / 全てのいを / 獲得する", P.POWER_GAIN),
    ("ヒメウタスズメを別の生息地に移動させる", P.POWER_MOVE),
    ("310ヒメウタスズメを別の生息地に移動させる / 30cM-", P.POWER_MOVE),
]


@pytest.mark.parametrize(("text", "kind"), MEASURED)
def test_measured_ocr_texts_are_classified(text: str, kind: PromptKind) -> None:
    assert classify_text(text) is kind


def test_unrelated_or_empty_text_is_unknown() -> None:
    assert classify_text("") is P.UNKNOWN
    assert classify_text("ラウンド 2/4 残り 7 手番") is P.UNKNOWN
    assert classify_text("オウゴンヒワ") is P.UNKNOWN


def test_phrase_score_tolerates_one_or_two_misread_characters() -> None:
    assert (
        phrase_score("xx鳥をタップして産卵して下さいxx", "鳥をタップして産卵してください") >= 0.78
    )
    assert phrase_score("全く別の文章です", "鳥をタップして産卵してください") < 0.6


needs_real = pytest.mark.skipif(
    not JAPANESE_REC_MODEL.exists() or not (DATA / "046_grass_slot.png").exists(),
    reason="日本語の認識モデルまたは実画面が無い(Git 管理外)",
)

REAL = [
    ("046_grass_slot", P.LAY_EGGS),
    ("030_forest_action", P.PICK_DIE),
    ("151_swift", P.PAY_FOOD),
    ("235_draw", P.PICK_CARD),
    ("152_eggs", P.PAY_EGGS),
    ("091_egg_convert", P.DISCARD_EGG),
    ("159_tuck", P.TUCK),
    ("105_pay_fruit", P.DISCARD_FOOD),
    ("249_drag", P.CHOOSE_HABITAT),
    ("163a", P.POWER_FEEDER_CACHE),
    ("160_tuck_ok", P.POWER_GAIN),
    ("136_ok", P.POWER_MOVE),
]


@needs_real
@pytest.mark.parametrize(("name", "kind"), REAL)
def test_real_screens_prompt_kind(name: str, kind: PromptKind) -> None:
    image = cv2.imread(str(DATA / f"{name}.png"))
    assert read_prompt(image, japanese_reader()).kind is kind


def test_each_decision_expects_its_prompt() -> None:
    # logic の決定(Task)ごとに、画面に出てよい案内(RESULT.md §9〜§10 の操作と対応)
    assert expected_prompts(GainFoodTask(2)) == {P.PICK_DIE}
    # 変換の決定の間も、パネルは元の案内のまま(餌の選択 / 産卵 / 札を選ぶ)か、変換のボタンを押した後の案内
    assert expected_prompts(ConvertFoodTask()) == {P.PICK_DIE, P.DISCARD_CARD}
    assert expected_prompts(LayEggsTask(2)) == {P.LAY_EGGS}
    assert expected_prompts(EggBonusTask()) == {P.LAY_EGGS, P.DISCARD_FOOD}
    assert expected_prompts(DrawTask(1)) == {
        P.PICK_CARD,
        P.DRAW_DECK,
    }  # 山札だけを引く案内も、同じ決定
    assert expected_prompts(DrawBonusTask()) == {P.PICK_CARD, P.DISCARD_EGG}
    assert expected_prompts(TuckTask(at=Placement(Habitat.FOREST, 0))) == {P.TUCK}
    assert expected_prompts(SetupTask()) == frozenset()


def test_power_decision_accepts_any_power_prompt_including_unmodeled() -> None:
    expected = expected_prompts(PowersTask(Habitat.FOREST, 0))
    assert {
        P.POWER_GAIN,
        P.POWER_FEEDER_CACHE,
        P.POWER_GAIN_CACHE,
        P.POWER_MOVE,
        P.TUCK,
    } <= expected
    assert (
        P.UNKNOWN in expected
    )  # 実装していない能力は文言が決まらない。executor はスキップで進める
    assert P.LAY_EGGS not in expected and P.PICK_DIE not in expected


def test_nothing_to_do_prompt_is_recognized() -> None:
    # 実機: 産卵できる鳥がいないとき、アプリは「このアクションをスキップしてください」を求める
    text = "ミサゴ -- 160ćM-産卵できる鳥がいません。このアク ションをスキップしてください。"
    assert classify_text(text) is P.NOTHING_TO_DO
