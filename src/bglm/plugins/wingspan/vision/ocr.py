"""日本語の OCR で領域を読み、行ごとの文字列にする(`mat.LineReader` の実装)。

認識モデルは日本語のもの(`models/ocr/japan_PP-OCRv4_rec_infer.onnx`。Git 管理外)。
OCR は 1 行の名前を断片に分けて返す(例: 「コマ」「ツグミ」)ので、同じ高さの断片を x の順につなぐ。
札名は 2 行になることがあるので、高さが離れた断片は別の行にする。
"""

from pathlib import Path

from bglm.plugins.wingspan.vision.mat import Image, LineReader
from bglm.toolkit.ocr_reader import RawLine, recognize

JAPANESE_REC_MODEL = Path("models/ocr/japan_PP-OCRv4_rec_infer.onnx")
SAME_LINE_PX = 18  # 高さの差がこれ以内の断片は同じ行(原寸の画素)
SCALE = 3  # 小さい札名は、3 倍に拡大すると読みやすい


def group_lines(lines: list[RawLine]) -> list[str]:
    """断片を、高さで行に分け、行ごとに x の順につないで、上の行から返す。"""
    rows: list[list[RawLine]] = []
    for line in sorted(lines, key=lambda r: r.y):
        if rows and line.y - rows[-1][0].y <= SAME_LINE_PX:
            rows[-1].append(line)
        else:
            rows.append([line])
    return ["".join(r.text for r in sorted(row, key=lambda r: r.x)) for row in rows]


def japanese_reader(model: Path = JAPANESE_REC_MODEL, scale: int = SCALE) -> LineReader:
    """日本語の認識モデルで領域を読む読み取り器。"""
    rec_model = str(model)

    def read(image: Image, box: tuple[int, int, int, int]) -> list[str]:
        return group_lines(recognize(image, box, scale, rec_model=rec_model))

    return read
