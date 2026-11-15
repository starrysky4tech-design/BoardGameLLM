"""board_scan を、手で作った正解(labels.json)と比べる(作業用)。"""
import json, time
import cv2
from bglm.plugins.monopoly.vision.board_scan import scan_board
from bglm.plugins.monopoly.vision.ownership import Owner

base = "datasets/eval/monopoly/board_scan/"
labels = json.load(open(base + "labels.json", encoding="utf-8"))
for item in labels["images"]:
    im = cv2.imread(base + item["image"])
    t = time.time(); scan = scan_board(im); dt = time.time() - t
    wrong = []
    for name, want in item["owners"].items():
        got = scan.tiles[name].owner
        if got is None or got.value != want: wrong.append(("owner", name, want, got))
    for name, t_ in scan.tiles.items():
        want = name in item["mortgaged"]
        if t_.mortgaged is not want: wrong.append(("mortgage", name, want, t_.mortgaged))
    for g, b in (scan.groups or {}).items():
        wu = item["house_units"].get(g, 0); wh = item["hotels"].get(g, 0)
        flag = "" if abs(b.house_units - wu) < 0.6 and b.hotels == wh else "  <-- NG"
        if wu or wh or b.house_units > 0.3 or b.hotels: print(f"   {g:10} units={b.house_units:5.2f} (want {wu}) hotels={b.hotels} (want {wh}){flag}")
    print(item["image"], f"{dt*1000:.0f}ms", "wrong:", wrong or "なし")
