import json, shutil, sys
name, a, b, src = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
shutil.copy(rf"{sys.argv[5]}", f"datasets/eval/monopoly/dice3/{name}.png")
p = "datasets/eval/monopoly/dice3/labels.json"
d = json.load(open(p, encoding="utf-8"))
d[f"{name}.png"] = {"dice": sorted([a, b]), "source": src}
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(d), "samples")
