"""全体盤の特徴量を、全 28 マスで表示する(閾値を決める作業用)。使い方: features.py <画像パス>..."""
import sys
import cv2, numpy as np
from bglm.plugins.monopoly.vision import board_geometry as g
from bglm.plugins.monopoly.logic.board import BOARD, SquareKind

for path in sys.argv[1:]:
    im = cv2.imread(path)
    w = g.warp(im)
    hsv = cv2.cvtColor(w, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    blue = (H >= 95) & (H <= 125) & (S > 120) & (V > 120)
    yellow = (H >= 22) & (H <= 36) & (S > 150) & (V > 200)
    red = ((H <= 8) | (H >= 170)) & (S > 150) & (V > 100)
    mint = (H >= 72) & (H <= 90) & (S > 100) & (V >= 200)
    print("==", path)
    print(f"{'pos':>3} {'name':22} {'blue':>5} {'yell':>5} {'red':>5} {'mint':>5} comps")
    for sq in BOARD:
        if sq.kind is not SquareKind.DEED: continue
        r = g.tile_regions(sq.position)
        def frac(m, rect): return m[rect.y0:rect.y1, rect.x0:rect.x1].mean()
        band = r.band
        mm = mint[band.y0:band.y1, band.x0:band.x1].astype(np.uint8)
        n, _, st, _ = cv2.connectedComponentsWithStats(mm)
        comps = [(int(s[2]), int(s[3]), int(s[4])) for s in st[1:] if s[4] >= 40]
        print(f"{sq.position:>3} {sq.name:22} {frac(blue, r.bar):5.2f} {frac(yellow, r.bar):5.2f} {frac(red, r.body):5.2f} {frac(mint, band):5.2f} {comps}")
