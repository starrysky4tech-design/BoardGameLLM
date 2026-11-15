"""札の表(birds.json)の検査。値そのものの正しさは、画像で人が確かめた(source の画像)。

ここでは「表の形が壊れていない」ことと、画像から確かめた代表的な札の値を固定する。
"""

import pytest

from bglm.plugins.wingspan.logic.cards import UnknownCardError, default_table, load_birds
from bglm.plugins.wingspan.logic.models import Food, Habitat, Nest, Timing

TABLE = default_table()


def test_table_is_not_empty_and_has_sources() -> None:
    assert len(TABLE.birds) >= 20
    assert all(b.source for b in TABLE.birds.values())


def test_every_bird_is_well_formed() -> None:
    for b in TABLE.birds.values():
        assert b.habitats, b.name
        assert 0 <= b.points <= 9, b.name  # 札の点は 0〜9 の範囲(見えた札の最大は 9)
        assert 0 <= b.egg_limit <= 6, b.name
        assert 5 <= b.wingspan_cm <= 400, (
            b.name
        )  # 札の翼長は 8cm(ノドグロハチドリ)〜 201cm(イヌワシ)まで見えた
        assert b.cost.total() <= 5, b.name
        if b.cost.either:
            assert len(b.cost.foods) >= 2, b.name  # 「/」は選べる餌が 2 つ以上
        if b.power.timing is not Timing.NONE:
            assert b.power.kind and b.power.text, b.name


def test_card_values_read_from_images() -> None:
    # 画像(source)から人が読んだ値。ヤマセミ(203_select.png): 湿地、魚 + 何でも、4 点、星の巣、卵 4、53cm、桃色
    kingfisher = TABLE.bird("アメリカヤマセミ")
    assert kingfisher.habitats == frozenset({Habitat.WETLAND})
    assert kingfisher.cost.foods == (Food.FISH,) and kingfisher.cost.wild == 1
    assert (kingfisher.points, kingfisher.nest, kingfisher.egg_limit, kingfisher.wingspan_cm) == (
        4,
        Nest.STAR,
        4,
        53,
    )
    assert kingfisher.power.timing is Timing.BETWEEN_TURNS


def test_either_cost_and_multi_habitat() -> None:
    # コマツグミ(248_hand.png): 森林・草原、果実 / 虫(どちらか)、1 点、椀、卵 4、43cm
    robin = TABLE.bird("コマツグミ")
    assert robin.habitats == frozenset({Habitat.FOREST, Habitat.GRASSLAND})
    assert robin.cost.either and set(robin.cost.foods) == {Food.FRUIT, Food.INVERTEBRATE}


def test_unknown_card_raises() -> None:
    with pytest.raises(UnknownCardError):
        TABLE.bird("存在しない鳥")
    assert not TABLE.known("存在しない鳥")


def test_duplicate_names_are_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bird = (
        '{"name":"a","habitats":["forest"],"cost":{"foods":[],"wild":0,"either":false},'
        '"points":1,"nest":"bowl","egg_limit":1,"wingspan_cm":20,"source":"x"}'
    )
    path = tmp_path / "birds.json"
    path.write_text('{"birds":[' + bird + "," + bird + "]}", encoding="utf-8")
    with pytest.raises(ValueError, match="重複"):
        load_birds(path)
