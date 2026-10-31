"""ログに保存するための変換。手や盤面は、プラグインごとのデータクラスをそのまま JSON にできる形へ変える。"""

import dataclasses
from collections.abc import Mapping
from enum import Enum
from typing import Any

from bglm.core.models import Recognition


def jsonable(value: object) -> Any:
    """データクラス・Enum・タプル・辞書を、JSON で書ける形へ再帰的に変換する。

    データクラスは {"type": クラス名, ...フィールド} にする。辞書の鍵は文字列にする。
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        data = {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
        return {"type": type(value).__name__, **data}
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(v) for v in value]
    return repr(value)


def recognition_to_dict(recognition: Recognition[Any]) -> dict[str, Any]:
    return {
        "ui": {"kind": recognition.ui.kind.value, "screen": recognition.ui.screen},
        "state": jsonable(recognition.state),
        "confidence": recognition.confidence,
        "low_confidence": list(recognition.low_confidence),
    }
