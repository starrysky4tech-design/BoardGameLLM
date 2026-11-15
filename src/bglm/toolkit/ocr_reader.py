"""RapidOCR のエンジンと、画像の一部を読む `recognize`(ゲームをまたいで共有する)。

エンジンの読み込みは重い(モデルの読み込み)ので、認識モデルごとにプロセスで 1 度だけ行う。
`rec_model` に認識モデル(onnx)のパスを渡すと、既定の中国語・英語のモデルの代わりに使える
(Wingspan は日本語のモデルで札名を読む。既定のモデルはカタカナを読めない)。外部ライブラリは型情報が無い。
"""

from dataclasses import dataclass
from functools import cache
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray


@cache
def get_engine(rec_model: str | None = None) -> Any:
    """RapidOCR のエンジン。rec_model が None なら既定のモデル。"""
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR(rec_model_path=rec_model) if rec_model else RapidOCR()


@dataclass(frozen=True)
class RawLine:
    y: float  # 行の上端の y(画像の原寸の画素)
    text: str
    confidence: float
    x: float = 0.0  # 行の左端の x(画像の原寸の画素)


def recognize(
    image: NDArray[np.uint8],
    box: tuple[int, int, int, int],
    scale: int,
    *,
    rec_model: str | None = None,
) -> list[RawLine]:
    """画像の box(x0, y0, x1, y1)を scale 倍に拡大して読む。エンジンが返す順のまま返す。"""
    x0, y0, x1, y1 = box
    crop = cv2.resize(image[y0:y1, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    result, _ = get_engine(rec_model)(crop)
    return [
        RawLine(
            y=min(float(p[1]) for p in points) / scale + y0,
            text=str(text),
            confidence=float(conf),
            x=min(float(p[0]) for p in points) / scale + x0,
        )
        for points, text, conf in result or []
    ]
