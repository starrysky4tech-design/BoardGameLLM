r"""土地・鉄道・会社の定義(全 28 件)。

出典: マスのカードのキャプチャー(K:\monopoly_img\マス)。購入・抵当の画面の金額とも照合済み。
賃料表は (基本, 家1, 家2, 家3, 家4, ホテル)。抵当価値はカードの記載をそのまま入れる
(価格の半額と一致することは、テストで確かめる)。
"""

from collections.abc import Mapping

from bglm.plugins.monopoly.logic.models import Deed, DeedKind


def _street(
    name: str,
    group: str,
    size: int,
    price: int,
    mortgage: int,
    rent: tuple[int, int, int, int, int, int],
    house_cost: int,
) -> Deed:
    return Deed(
        name=name,
        kind=DeedKind.STREET,
        group=group,
        group_size=size,
        price=price,
        mortgage=mortgage,
        rent=rent,
        house_cost=house_cost,
    )


def _railroad(name: str) -> Deed:
    return Deed(
        name=name,
        kind=DeedKind.RAILROAD,
        group="railroad",
        group_size=4,
        price=200,
        mortgage=100,
        rent=(25, 50, 100, 200),
    )


def _utility(name: str) -> Deed:
    return Deed(
        name=name,
        kind=DeedKind.UTILITY,
        group="utility",
        group_size=2,
        price=150,
        mortgage=75,
    )


DEEDS: tuple[Deed, ...] = (
    _street("Mediterranean Avenue", "brown", 2, 60, 30, (2, 10, 30, 90, 160, 250), 50),
    _street("Baltic Avenue", "brown", 2, 60, 30, (4, 20, 60, 180, 320, 450), 50),
    _railroad("Reading Railroad"),
    _street("Oriental Avenue", "light_blue", 3, 100, 50, (6, 30, 90, 270, 400, 550), 50),
    _street("Vermont Avenue", "light_blue", 3, 100, 50, (6, 30, 90, 270, 400, 550), 50),
    _street("Connecticut Avenue", "light_blue", 3, 120, 60, (8, 40, 100, 300, 450, 600), 50),
    _street("St. Charles Place", "pink", 3, 140, 70, (10, 50, 150, 450, 625, 750), 100),
    _utility("Electric Company"),
    _street("States Avenue", "pink", 3, 140, 70, (10, 50, 150, 450, 625, 750), 100),
    _street("Virginia Avenue", "pink", 3, 160, 80, (12, 60, 180, 500, 700, 900), 100),
    _railroad("Pennsylvania Railroad"),
    _street("St. James Place", "orange", 3, 180, 90, (14, 70, 200, 550, 750, 950), 100),
    _street("Tennessee Avenue", "orange", 3, 180, 90, (14, 70, 200, 550, 750, 950), 100),
    _street("New York Avenue", "orange", 3, 200, 100, (16, 80, 220, 600, 800, 1000), 100),
    _street("Kentucky Avenue", "red", 3, 220, 110, (18, 90, 250, 700, 875, 1050), 150),
    _street("Indiana Avenue", "red", 3, 220, 110, (18, 90, 250, 700, 875, 1050), 150),
    _street("Illinois Avenue", "red", 3, 240, 120, (20, 100, 300, 750, 925, 1100), 150),
    _railroad("B&O Railroad"),
    _street("Atlantic Avenue", "yellow", 3, 260, 130, (22, 110, 330, 800, 975, 1150), 150),
    _street("Ventnor Avenue", "yellow", 3, 260, 130, (22, 110, 330, 800, 975, 1150), 150),
    _utility("Water Works"),
    _street("Marvin Gardens", "yellow", 3, 280, 140, (24, 120, 360, 850, 1025, 1200), 150),
    _street("Pacific Avenue", "green", 3, 300, 150, (26, 130, 390, 900, 1100, 1275), 200),
    _street("North Carolina Avenue", "green", 3, 300, 150, (26, 130, 390, 900, 1100, 1275), 200),
    _street("Pennsylvania Avenue", "green", 3, 320, 160, (28, 150, 450, 1000, 1200, 1400), 200),
    _railroad("Short Line"),
    _street("Park Place", "dark_blue", 2, 350, 175, (35, 175, 500, 1100, 1300, 1500), 200),
    _street("Boardwalk", "dark_blue", 2, 400, 200, (50, 200, 600, 1400, 1700, 2000), 200),
)

CATALOGUE: Mapping[str, Deed] = {deed.name: deed for deed in DEEDS}


def street_groups(catalogue: Mapping[str, Deed]) -> dict[str, list[Deed]]:
    """色グループ → 街(土地。鉄道・会社を除く)。カタログの並びのまま。"""
    groups: dict[str, list[Deed]] = {}
    for deed in catalogue.values():
        if deed.kind is DeedKind.STREET:
            groups.setdefault(deed.group, []).append(deed)
    return groups


STREET_GROUPS = street_groups(CATALOGUE)
