"""例外の定義。予期されるエラーはここの例外で表す(docs/05)。"""


class BglmError(Exception):
    """本プロジェクトの例外の基底。"""


class ConfigError(BglmError):
    """設定が不正。起動前に検出して止める。"""


class SourceLostError(BglmError):
    """ウィンドウの消失、端末の切断など、画面を取得できない。StopReason.SOURCE_LOST に対応する。"""


class InputRejectedError(BglmError):
    """入力を送れない(対象が前面にないなど)。入力は送られていない。"""


class PluginNotFoundError(BglmError):
    """設定のゲーム名に対応するプラグインが無い。"""


class UserAbortError(BglmError):
    """緊急停止が要求された。入力は送られていない。StopReason.USER_ABORT に対応する。"""


class ReplayExhaustedError(BglmError):
    """リプレイ用の画像を使い切った。"""
