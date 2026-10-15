from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCACTIVATE = 0x0086
HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

GWL_STYLE = -16
WS_MAXIMIZEBOX = 0x0001_0000
WS_MINIMIZEBOX = 0x0002_0000
WS_THICKFRAME = 0x0004_0000
WS_CAPTION = 0x00C0_0000
SM_CXSIZEFRAME = 32
SM_CXPADDEDBORDER = 92

SW_MAXIMIZE = 3

SWP_NOSIZE = 0x1
SWP_NOMOVE = 0x2
SWP_NOZORDER = 0x4
SWP_NOACTIVATE = 0x10
SWP_FRAMECHANGED = 0x20

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def parse_message(address: int) -> tuple[int, int, int, int]:
    msg = MSG.from_address(address)
    return (int(msg.hwnd or 0), int(msg.message),
            int(msg.wParam), int(msg.lParam))


if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi")
    try:
        _GetWLP = _user32.GetWindowLongPtrW
    except AttributeError:
        _GetWLP = _user32.GetWindowLongW
    _SetWLP = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
    _GetWLP.restype = ctypes.c_ssize_t
    _GetWLP.argtypes = [wintypes.HWND, ctypes.c_int]
    _SetWLP.restype = ctypes.c_ssize_t
    _SetWLP.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.DefWindowProcW.restype = ctypes.c_ssize_t
    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetClientRect.restype = wintypes.BOOL
    _user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]


def get_window_style(hwnd: int) -> int:
    return int(_GetWLP(hwnd, GWL_STYLE))


def set_window_style(hwnd: int, style: int) -> None:
    _SetWLP(hwnd, GWL_STYLE, style)


def enable_native_chrome(hwnd: int) -> None:
    if not IS_WINDOWS:
        return
    style = get_window_style(hwnd)
    style |= WS_THICKFRAME | WS_CAPTION | WS_MAXIMIZEBOX | WS_MINIMIZEBOX
    set_window_style(hwnd, style)
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                         SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE |
                         SWP_NOZORDER | SWP_NOACTIVATE)


def apply_dwm_preferences(hwnd: int) -> None:
    if not IS_WINDOWS:
        return
    for attr, value in ((DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
                        (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)):
        raw = ctypes.c_int(value)
        _dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(raw), ctypes.sizeof(raw))


def is_zoomed(hwnd: int) -> bool:
    return bool(IS_WINDOWS and _user32.IsZoomed(hwnd))


def resize_border_thickness() -> int:
    if not IS_WINDOWS:
        return 8
    return int(_user32.GetSystemMetrics(SM_CXSIZEFRAME) +
               _user32.GetSystemMetrics(SM_CXPADDEDBORDER))


def lparam_to_point(lparam: int) -> tuple[int, int]:
    return (ctypes.c_short(lparam & 0xFFFF).value,
            ctypes.c_short((lparam >> 16) & 0xFFFF).value)


def deflate_client_rect(nc_lparam: int, thickness: int) -> None:
    rect = wintypes.RECT.from_address(nc_lparam)
    rect.left += thickness
    rect.top += thickness
    rect.right -= thickness
    rect.bottom -= thickness


def def_window_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    return int(_user32.DefWindowProcW(hwnd, msg, wparam, lparam))


def _make_lparam(x: int, y: int) -> int:
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


def post_click(hwnd: int, x: int, y: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    lp = _make_lparam(x, y)
    ok_down = _user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    ok_up = _user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    return bool(ok_down and ok_up)


def focus_window(hwnd: int) -> None:
    if IS_WINDOWS and hwnd:
        _user32.ShowWindow(hwnd, SW_MAXIMIZE)
        _user32.SetForegroundWindow(hwnd)


def client_size(hwnd: int) -> tuple[int, int]:
    if not IS_WINDOWS or not hwnd:
        return (0, 0)
    rect = wintypes.RECT()
    if _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return (rect.right - rect.left, rect.bottom - rect.top)
    return (0, 0)


def find_window_by_title(title_fragment: str) -> int:
    if not IS_WINDOWS:
        return 0
    results: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_ssize_t, ctypes.c_ssize_t)
    def callback(hwnd: int, _lparam: int) -> bool:
        if _user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(hwnd, buf, 256)
            if title_fragment.casefold() in buf.value.casefold():
                results.append(hwnd)
        return True

    _user32.EnumWindows(callback, 0)
    return results[0] if results else 0