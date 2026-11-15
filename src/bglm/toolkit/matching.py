"""テンプレートとの照合(正規化相関 `TM_CCOEFF_NORMED`)。

相関の最大値と位置を求める処理と、相関の山を周囲を消しながら高い順に拾う処理を持つ。
閾値や消す範囲は、ゲームの知識なので呼び出し側が渡す。
"""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class Match:
    score: float
    x: int  # テンプレートの左上の位置
    y: int


NO_MATCH = Match(0.0, 0, 0)


def _fits(image: NDArray[np.uint8], template: NDArray[np.uint8]) -> bool:
    return bool(image.shape[0] >= template.shape[0] and image.shape[1] >= template.shape[1])


def correlation(image: NDArray[np.uint8], template: NDArray[np.uint8]) -> NDArray[np.float32]:
    """各位置の相関(`cv2.matchTemplate` の結果)。テンプレートが画像より大きいときは ValueError。"""
    if not _fits(image, template):
        raise ValueError(f"テンプレート {template.shape} が画像 {image.shape} より大きい")
    return np.asarray(cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED), dtype=np.float32)


def best_match(image: NDArray[np.uint8], template: NDArray[np.uint8]) -> Match:
    """相関の最大値と位置。テンプレートが画像より大きければ NO_MATCH(相関 0.0)。"""
    if not _fits(image, template):
        return NO_MATCH
    _, best, _, (x, y) = cv2.minMaxLoc(correlation(image, template))
    return Match(float(best), int(x), int(y))


def match_score(image: NDArray[np.uint8], template: NDArray[np.uint8]) -> float:
    """相関の最大値。テンプレートが画像より大きければ 0.0。"""
    return best_match(image, template).score


def find_peaks(
    result: NDArray[np.float32], threshold: float, half_width: int, half_height: int
) -> list[Match]:
    """相関が threshold 以上の山を、高い順に拾う。拾った山の周りの
    [x - half_width, x + half_width) × [y - half_height, y + half_height) を消してから、次を探す。

    result は書き換えない。
    """
    work = result.copy()
    found: list[Match] = []
    while True:
        _, best, _, (x, y) = cv2.minMaxLoc(work)
        if best < threshold:
            return found
        found.append(Match(float(best), int(x), int(y)))
        work[
            max(0, y - half_height) : y + half_height, max(0, x - half_width) : x + half_width
        ] = -1
