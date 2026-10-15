from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtGui import QImage, QPixmap

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"


class _ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL),
                ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_byte), ("rgbGreen", ctypes.c_byte),
                ("rgbRed", ctypes.c_byte), ("rgbReserved", ctypes.c_byte)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", _RGBQUAD * 1)]


def extract_exe_icon(exe_path: str, size: int = 256) -> QPixmap | None:
    if not IS_WINDOWS or not exe_path or not Path(exe_path).is_file():
        return None

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        user32.PrivateExtractIconsW.restype = ctypes.c_uint
        user32.PrivateExtractIconsW.argtypes = [
            wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(wintypes.HICON), ctypes.POINTER(ctypes.c_uint),
            ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
        user32.DestroyIcon.restype = wintypes.BOOL
        user32.DestroyIcon.argtypes = [wintypes.HICON]

        icons = (wintypes.HICON * 1)()
        loaded = ctypes.c_uint(0)
        count = user32.PrivateExtractIconsW(str(exe_path), 0, size, size,
                                            icons, ctypes.byref(loaded), 1, None)
        if count == 0 or loaded.value == 0:
            return None
        hicon = icons[0]

        info = _ICONINFO()
        if not user32.GetIconInfo(hicon, ctypes.byref(info)):
            user32.DestroyIcon(hicon)
            return None

        bmp = _BITMAP()
        if not gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(_BITMAP), ctypes.byref(bmp)):
            gdi32.DeleteObject(info.hbmColor)
            gdi32.DeleteObject(info.hbmMask)
            user32.DestroyIcon(hicon)
            return None
        width, height = bmp.bmWidth, bmp.bmHeight
        if width <= 0 or height <= 0:
            gdi32.DeleteObject(info.hbmColor)
            gdi32.DeleteObject(info.hbmMask)
            user32.DestroyIcon(hicon)
            return None

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        hdc_screen = user32.GetDC(None)
        buf = (ctypes.c_ubyte * (width * height * 4))()
        ok = gdi32.GetDIBits(hdc_screen, info.hbmColor, 0, height, buf,
                             ctypes.byref(bmi), 0)
        user32.ReleaseDC(None, hdc_screen)
        gdi32.DeleteObject(info.hbmColor)
        gdi32.DeleteObject(info.hbmMask)
        user32.DestroyIcon(hicon)
        if not ok:
            return None

        raw = bytes(buf)
        image = QImage(raw, width, height, width * 4, QImage.Format.Format_ARGB32)
        image = image.copy()
        if image.isNull():
            return None
        return QPixmap.fromImage(image)
    except Exception:
        log.debug("Icon extraction failed for %s", exe_path, exc_info=True)
        return None