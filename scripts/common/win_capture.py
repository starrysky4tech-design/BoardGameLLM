"""PCゲームウィンドウの取得と入力の検証スクリプト(Phase 0)。

使い方:
    uv run python -m scripts.common.win_capture info
    uv run python -m scripts.common.win_capture capture out.png [--method mss|printwindow]
    uv run python -m scripts.common.win_capture click 640 360
    uv run python -m scripts.common.win_capture key e

座標はウィンドウのクライアント領域の左上を原点とする。入力は対象ウィンドウが前面にある
ときだけ送る(別のアプリへの誤クリックを防ぐため)。
"""

import argparse
import ctypes
import sys
import time
from pathlib import Path

import cv2
import mss
import numpy as np
import pydirectinput
import pywintypes
import win32api
import win32con
import win32gui
import win32ui

TITLE = "大戦略SSB2"  # 完全一致。VS Codeなど、題名に含むだけのウィンドウを除く

pydirectinput.FAILSAFE = False
pydirectinput.PAUSE = 0.05


def _enable_dpi_awareness() -> None:
    """DPI仮想化を切り、座標を実ピクセルで扱う。"""
    ctypes.windll.shcore.SetProcessDpiAwareness(2)


def find_window() -> int:
    found: list[int] = []

    def callback(hwnd: int, _: object) -> None:
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == TITLE:
            found.append(hwnd)

    win32gui.EnumWindows(callback, None)
    if len(found) != 1:
        raise SystemExit(f"ウィンドウ「{TITLE}」が{len(found)}個見つかった")
    return found[0]


def client_rect_on_screen(hwnd: int) -> tuple[int, int, int, int]:
    """クライアント領域の (left, top, width, height) をスクリーン座標で返す。"""
    _, _, width, height = win32gui.GetClientRect(hwnd)
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    return left, top, width, height


def capture_mss(hwnd: int) -> np.ndarray:
    left, top, width, height = client_rect_on_screen(hwnd)
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    return np.asarray(cv2.cvtColor(np.array(shot), cv2.COLOR_BGRA2BGR))


def capture_printwindow(hwnd: int) -> np.ndarray:
    """他のウィンドウに隠れていても取得できる方式。GPU描画のゲームでは黒くなることがある。"""
    _, _, width, height = win32gui.GetClientRect(hwnd)
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    mem_dc = src_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(src_dc, width, height)
    mem_dc.SelectObject(bitmap)
    # PW_CLIENTONLY(1) | PW_RENDERFULLCONTENT(2)
    ctypes.windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 3)
    raw = bitmap.GetBitmapBits(True)
    image = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
    mem_dc.DeleteDC()
    src_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    win32gui.DeleteObject(bitmap.GetHandle())
    return np.asarray(cv2.cvtColor(image, cv2.COLOR_BGRA2BGR))


def bring_to_front(hwnd: int) -> bool:
    """ゲームを前面に出す。Windowsは別プロセスからの前面化を拒むことがあるため、
    失敗したらAltキーの押し離しを挟んで再試行する。"""
    for _ in range(3):
        try:
            win32gui.SetForegroundWindow(hwnd)
        except pywintypes.error:
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.2)
        if win32gui.GetForegroundWindow() == hwnd:
            return True
    return False


def require_foreground(hwnd: int) -> None:
    """前面に出し、出なければ入力を送らない。"""
    bring_to_front(hwnd)
    if win32gui.GetForegroundWindow() != hwnd:
        raise SystemExit("対象ウィンドウが前面にない。入力を送らず中止する")


def click(hwnd: int, x: int, y: int) -> None:
    require_foreground(hwnd)
    left, top, width, height = client_rect_on_screen(hwnd)
    if not (0 <= x < width and 0 <= y < height):
        raise SystemExit(f"座標({x},{y})がクライアント領域 {width}x{height} の外")
    # 移動と押し離しの間に待ちを入れる。即時のクリックはゲーム側に拾われないことがある
    pydirectinput.moveTo(left + x, top + y)
    time.sleep(0.15)
    pydirectinput.mouseDown()
    time.sleep(0.1)
    pydirectinput.mouseUp()


def scroll(hwnd: int, x: int, y: int, notches: int) -> None:
    """指定位置でマウスホイールを回す。正が上、負が下。"""
    require_foreground(hwnd)
    left, top, _, _ = client_rect_on_screen(hwnd)
    pydirectinput.moveTo(left + x, top + y)
    time.sleep(0.15)
    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, notches * 120, 0)


def key(hwnd: int, name: str) -> None:
    require_foreground(hwnd)
    pydirectinput.press(name)


def main() -> int:
    _enable_dpi_awareness()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info")
    p_cap = sub.add_parser("capture")
    p_cap.add_argument("out", type=Path)
    p_cap.add_argument("--method", choices=["mss", "printwindow"], default="mss")
    p_click = sub.add_parser("click")
    p_click.add_argument("x", type=int)
    p_click.add_argument("y", type=int)
    p_scroll = sub.add_parser("scroll")
    p_scroll.add_argument("x", type=int)
    p_scroll.add_argument("y", type=int)
    p_scroll.add_argument("notches", type=int)
    p_key = sub.add_parser("key")
    p_key.add_argument("name")
    p_front = sub.add_parser("foreground")
    p_front.add_argument("--wait", type=float, default=0.5)
    args = parser.parse_args()

    hwnd = find_window()

    if args.command == "info":
        left, top, width, height = client_rect_on_screen(hwnd)
        outer = win32gui.GetWindowRect(hwnd)
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        print(f"hwnd={hwnd} client=({left},{top}) {width}x{height} outer={outer}")
        print(
            f"枠あり={bool(style & win32con.WS_CAPTION)} 前面={win32gui.GetForegroundWindow() == hwnd}"
        )
    elif args.command == "capture":
        started = time.perf_counter()
        image = capture_mss(hwnd) if args.method == "mss" else capture_printwindow(hwnd)
        elapsed_ms = (time.perf_counter() - started) * 1000
        args.out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.out), image)
        print(
            f"{args.out} {image.shape[1]}x{image.shape[0]} 平均輝度{image.mean():.1f} {elapsed_ms:.0f}ms"
        )
    elif args.command == "click":
        click(hwnd, args.x, args.y)
        print(f"click {args.x},{args.y}")
    elif args.command == "scroll":
        scroll(hwnd, args.x, args.y, args.notches)
        print(f"scroll {args.notches}")
    elif args.command == "key":
        key(hwnd, args.name)
        print(f"key {args.name}")
    else:
        print(f"前面={bring_to_front(hwnd)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
