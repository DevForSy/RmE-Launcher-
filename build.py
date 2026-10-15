from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "RmELauncher"
ICON = ROOT / "assets" / "icon.ico"


def ensure_icon() -> Path | None:
    if ICON.is_file():
        return ICON
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return None
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 12, 244, 244], radius=60, fill=(245, 245, 247, 255))
    font = None
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, 138)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), "R", font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    d.text(((256 - w) / 2 - bbox[0], (256 - h) / 2 - bbox[1]),
           "R", font=font, fill=(10, 10, 12, 255))
    ICON.parent.mkdir(parents=True, exist_ok=True)
    img.save(ICON, sizes=[(16, 16), (32, 32), (48, 48), (64, 64),
                          (128, 128), (256, 256)])
    return ICON


def main() -> int:
    try:
        import PyInstaller
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    icon_path = ensure_icon()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        f"--name={NAME}",
        f"--add-data={ROOT / 'assets'};assets",
    ]
    if icon_path is not None:
        cmd.append(f"--icon={icon_path}")
    cmd.append(str(ROOT / "main.py"))

    print("[*] Building single-file EXE (3-8 minutes)...")
    result = subprocess.run(cmd, cwd=ROOT)
    exe = ROOT / "dist" / f"{NAME}.exe"
    if result.returncode == 0 and exe.is_file():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\n[OK] Built: {exe} ({size_mb:.1f} MB)")
        print("[OK] Single file - send ONLY this exe. Nothing else needed.")
        return 0
    print("[X] Build failed - read the errors above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())