"""保存画面から、肖像の下に出る印のテンプレートを切り出す(グレースケール。実画面で測った位置)。

使い方: uv run python -m scripts.wingspan.build_eye_template
- 目の印: 相手の盤を表示中に出る。233_opp.png の (1146,79)-(1176,101)
- 砂時計: 相手の手番の間、橙の肖像の下に出る。302_opp_turn_1.png の (1260,96)-(1286,132)
"""

from pathlib import Path

import cv2

DATA = Path("datasets/raw/wingspan/feasibility")
OUT_DIR = Path("src/bglm/plugins/wingspan/data/templates/viewing")
TEMPLATES = {
    "eye": (DATA / "233_opp.png", (1146, 79, 1176, 101)),
    "hourglass": (DATA / "302_opp_turn_1.png", (1260, 96, 1286, 132)),
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (source, (x0, y0, x1, y1)) in TEMPLATES.items():
        image = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise SystemExit(f"画像を読めない: {source}")
        cv2.imwrite(str(OUT_DIR / f"{name}.png"), image[y0:y1, x0:x1])
        print(OUT_DIR / f"{name}.png")


if __name__ == "__main__":
    main()
