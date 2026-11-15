"""実機の現在の画面を保存し、画面の種類を表示する(作業用)。使い方: shot.py <出力名>"""
import sys, time
import cv2
from bglm.core.config import AndroidTarget
from bglm.infrastructure.adb_device import AdbDevice
from bglm.plugins.monopoly.vision.screens import classify
dev = AdbDevice(AndroidTarget(serial="355092380222016"))
t = time.time()
img = dev.capture().image
dt = time.time() - t
name = sys.argv[1] if len(sys.argv) > 1 else "shot"
cv2.imwrite(f"datasets/eval/monopoly/board_scan/{name}.png", img)
print(classify(img).name, f"capture={dt:.2f}s")
