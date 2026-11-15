"""全体ボードの 1 画面から、見えるものをまとめて読む(札、卵、バッジ、数、ダイス、トレイ)。

読むのは「何も重なっていない全体ボード」だけ(`screens.classify` が MAT で案内パネルが無いとき)。
追跡している状態との照合は `recognizer.py`。ここでは画面の読み取り結果と、読めなかった要素の名前を返す。
"""

from dataclasses import dataclass

from bglm.plugins.wingspan.logic.cards import CardTable
from bglm.plugins.wingspan.logic.models import HABITATS, Habitat
from bglm.plugins.wingspan.vision import mat
from bglm.plugins.wingspan.vision.badges import Badge, read_badge
from bglm.plugins.wingspan.vision.counters import Counters, read_counters
from bglm.plugins.wingspan.vision.digits import Glyph
from bglm.plugins.wingspan.vision.feeder import UNKNOWN_FACE, feeder_faces
from bglm.plugins.wingspan.vision.mat import Image, LineReader
from bglm.plugins.wingspan.vision.tray import read_tray


@dataclass(frozen=True)
class BirdRead:
    name: str  # 札の表の札名、読めなければ UNKNOWN_CARD
    text: str  # OCR の生の文字列
    eggs: int
    badge: Badge | None


@dataclass(frozen=True)
class MatRead:
    rows: dict[Habitat, tuple[BirdRead, ...]]
    counters: Counters
    feeder: tuple[str, ...]
    tray: tuple[str, ...]  # 札名(UNKNOWN_CARD を含む)。取られた枠は空文字
    problems: tuple[str, ...]  # 読めなかった要素の名前


def read_mat(
    image: Image,
    read_lines: LineReader,
    table: CardTable,
    templates: dict[str, Glyph] | None = None,
) -> MatRead:
    problems: list[str] = []
    rows: dict[Habitat, tuple[BirdRead, ...]] = {}
    for habitat, slots in mat.read_rows(image, read_lines, table.birds).items():
        birds: list[BirdRead] = []
        for slot in slots:
            badge = read_badge(image, habitat, slot.column, templates)
            if badge is not None and (badge.kind is None or badge.count is None):
                problems.append(f"badge:{habitat.value}[{slot.column}]")
            birds.append(
                BirdRead(slot.name, slot.text, mat.count_eggs(image, habitat, slot.column), badge)
            )
        rows[habitat] = tuple(birds)
    for habitat in HABITATS:
        rows.setdefault(habitat, ())
    counters = read_counters(image, templates)
    if counters.cubes is None:
        problems.append("cubes")
    if counters.food is None:
        problems.append("food")
    feeder = feeder_faces(image)
    if UNKNOWN_FACE in feeder:
        problems.append("feeder")
    tray = tuple(slot.name if slot else "" for slot in read_tray(image, read_lines, table.birds))
    return MatRead(rows, counters, feeder, tray, tuple(problems))
