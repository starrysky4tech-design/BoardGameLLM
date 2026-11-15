"""対局の開始: メインメニュー → プレイ → カスタムゲーム →「次へ」で、カスタムゲームを始める。

使い方: uv run python -m scripts.wingspan.start_game --yes
- **対局を始めると、保護区の記録・アチーブメントが変わりうる**(CLAUDE.md「ユーザーのアカウントに影響する操作は事前に確認する」)。
  `--yes` が無ければ、何も押さない。繰り返しの自動対局の前に、記録への影響をユーザーと確認すること
- カスタムゲームの設定(人間 1 + AI イージー、基本 + スウィフトスタート)は、前に使った値のまま始まる。画面からは確かめきれないので、
  設定を変えていないことを、呼び出す側が保証する(RESULT.md §2、§10)
- メインメニューでなければ、何も押さない(起動直後のストアの案内・ニュースは、先に閉じる)
- 「次へ」を押すと、確認なしで対局が始まる(RESULT.md §2)
"""

import argparse
import sys
import time

from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.wingspan.vision.executor import press
from bglm.plugins.wingspan.vision.ocr import japanese_reader
from bglm.plugins.wingspan.vision.prompt import MIN_SCORE, phrase_score

SERIAL = "355092380222016"
PLAY = (752, 496)
CUSTOM_GAME = (690, 840)
NEXT = (2310, 990)
WAIT_SEC = 12.0
FULL = (0, 0, 2432, 1080)


def screen_text(io: AdbDevice, reader) -> str:  # type: ignore[no-untyped-def]
    return " ".join(reader(io.capture().image, FULL))


def has(text: str, phrase: str) -> bool:
    return phrase_score(text, phrase) >= MIN_SCORE


def wait_until(io: AdbDevice, reader, phrase: str) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + WAIT_SEC
    while time.monotonic() < deadline:
        if has(screen_text(io, reader), phrase):
            return True
        time.sleep(1.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--yes", action="store_true", help="対局を始めてよい(アカウントの記録に影響しうる)"
    )
    args = parser.parse_args()
    if not args.yes:
        print(
            "--yes が無いので何も押さない。対局の開始は、記録に影響しうるため、ユーザーの確認が要る"
        )
        return 2
    io = AdbDevice(AndroidTarget(serial=SERIAL))
    reader = japanese_reader(scale=1)
    text = screen_text(io, reader)
    if not (has(text, "保護区の記録") and has(text, "アチーブメント")):
        print("メインメニューではない。何も押さない")
        return 1
    io.perform(press(*PLAY))
    if not wait_until(io, reader, "あなたのゲーム"):
        print("「あなたのゲーム」の画面が出ない。止まる")
        return 1
    io.perform(press(*CUSTOM_GAME))
    if not wait_until(io, reader, "目的ボード"):
        print("カスタムゲームの設定の画面が出ない。止まる")
        return 1
    io.perform(press(*NEXT))
    time.sleep(8.0)
    print("対局を開始した。次: bglm run --game wingspan(初期選択から始まる)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
