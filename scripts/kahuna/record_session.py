"""人が遊んでいる間、端末の画面を記録する(Kahuna の Phase 5 の素材集め)。

中身は scripts/common/record_session.py と同じ。使い方は次のとおり:
    uv run python -m scripts.common.record_session --serial <serial> --out datasets/raw/kahuna/session1
"""

import sys

from scripts.common.record_session import main

if __name__ == "__main__":
    sys.exit(main())
