"""出来事の記録から、競り(direct=False の落札)の一覧を作る(作業用)。使い方: auction_table.py"""
import re
from bglm.plugins.monopoly.logic.catalogue import CATALOGUE

base = ".steering/20261104-monopoly-autoplay-handoff/scripts/"
pat = re.compile(r"AuctionWon\(winner=<Player\.(\w+): '\w+'>, square='([^']+)', price=(\w+), direct=False\)")
start = re.compile(r"AuctionStarted\(player=<Player\.(\w+): '\w+'>, square='([^']+)'\)")
for name, label in (("events_game2_easy_final.log", "2 局目 Easy"), ("events_game3_veryeasy.log", "3 局目 Very Easy")):
    rows = []; passer = {}
    for line in open(base + name, encoding="utf-8"):
        m = start.search(line)
        if m: passer[m.group(2)] = m.group(1)
        m = pat.search(line)
        if m and m.group(3) != "None":
            sq = m.group(2); price = int(m.group(3)); lp = CATALOGUE[sq].price
            rows.append((sq, lp, m.group(1), price, passer.get(sq, "?")))
    print(f"## {label}({len(rows)} 件)")
    print("| 土地 | 定価 | 見送った側 | 落札者 | 落札額 | 落札額 ÷ 定価 |")
    print("|---|---|---|---|---|---|")
    for sq, lp, w, price, ps in rows:
        who = {"SELF": "自分", "AI": "AI"}
        print(f"| {sq} | {lp} | {who.get(ps, '?')} | {who[w]} | {price} | {price/lp:.2f} |")
    print()
