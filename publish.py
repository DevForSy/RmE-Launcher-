from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_NAME = "RmE-Launcher"
VERSION = "1.0.0"


def run(cmd: list[str], **kw) -> int:
    print("[cmd]", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, **kw).returncode


def must(cmd: list[str]) -> None:
    if run(cmd) != 0:
        print(f"[X] Command failed: {cmd[0]}")
        sys.exit(1)


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print("[+] wrote", path.name)


def ensure_files() -> None:
    write_file(ROOT / ".gitignore", """\
.venv/
venv/
dist/
build/
__pycache__/
*.pyc
*.spec
assets/icon.ico
""")

    write_file(ROOT / "LICENSE",
               "Copyright (c) 2026-2030 RmE. All rights reserved.")

    username = input("GitHub username: ").strip()
    write_file(ROOT / "latest.json", json.dumps({
        "version": VERSION,
        "url": f"https://github.com/{username}/{REPO_NAME}/releases/latest",
        "notes": f"RmE Launcher v{VERSION}",
    }, indent=2))
    return username


def ensure_git() -> None:
    git_dir = ROOT / ".git"
    if git_dir.is_dir():
        return
    must(["git", "init"])
    must(["git", "branch", "-M", "main"])


def push_code(username: str) -> None:
    ensure_git()
    ensure_files()

    remote = f"https://github.com/{username}/{REPO_NAME}.git"
    run(["git", "remote", "remove", "origin"])
    must(["git", "remote", "add", "origin", remote])

    must(["git", "add", "-A"])
    run(["git", "commit", "-m", f"RmE Launcher v{VERSION}"])
    print("[*] A browser window will open - log in to GitHub to authorize the push...")
    must(["git", "push", "-u", "origin", "main"])
    print("[OK] Code pushed to GitHub")


def create_release(username: str) -> None:
    release_url = (f"https://github.com/{username}/{REPO_NAME}/releases/new?"
                   f"tag=v{VERSION}&title=RmE+Launcher+v{VERSION}")
    print("[*] Opening GitHub release page in your browser...")
    if sys.platform == "win32":
        os.startfile(release_url)
    else:
        subprocess.run(["xdg-open", release_url])
    print("[i] Attach this file to the release: dist\\RmELauncher.exe")
    print("[i] Then click 'Publish release' - updates will reach all users.")


def main() -> int:
    username = input("GitHub username: ").strip()
    if not username:
        print("[X] Username is required")
        return 1

    must(["git", "--version"])
    ensure_git()
    username = ensure_files()
    push_code(username)
    create_release(username)
    print("\n[DONE] Update notifications will reach all users automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())