#!/usr/bin/env python3
"""OpenCompanion 电脑端启动器。

做三件事：
  1. 检查配置是否就绪（没有就开浏览器走向导）
  2. 在后台起本机服务
  3. 自动打开浏览器

也可以用来生成桌面图标：`python launcher.py --install-shortcut`
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # open-companion/
CORE = ROOT / "core"
DATA = ROOT / "data"
PORT = int(os.environ.get("OC_PORT", "8800"))
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def already_running() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/healthz", timeout=3) as r:
            return b'"ok":true' in r.read()
    except Exception:
        return False


def wait_ready(timeout: float = 30.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if already_running():
            return True
        time.sleep(0.4)
    return False


def ensure_deps() -> bool:
    missing = []
    for mod, pkg in (("flask", "Flask"), ("openai", "openai"), ("PIL", "pillow")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return True
    print(f"缺少依赖：{', '.join(missing)}")
    ans = input("现在自动安装？[Y/n] ").strip().lower()
    if ans in ("", "y", "yes"):
        r = subprocess.run([sys.executable, "-m", "pip", "install", *missing])
        return r.returncode == 0
    return False


def start_server(log_path: Path | None = None) -> subprocess.Popen:
    env = dict(os.environ, OC_PORT=str(PORT))
    log = open(log_path, "a", encoding="utf-8") if log_path else subprocess.DEVNULL
    return subprocess.Popen(
        [sys.executable, str(CORE / "server.py")],
        env=env, stdout=log, stderr=subprocess.STDOUT,
        cwd=str(ROOT), start_new_session=True,
    )


# ── 桌面图标（macOS .app / Linux .desktop / Windows .vbs）──────────
def install_shortcut() -> None:
    name = "OpenCompanion"
    launcher = Path(__file__).resolve()
    py = sys.executable

    if sys.platform == "darwin":
        app = Path.home() / "Desktop" / f"{name}.app"
        macos = app / "Contents" / "MacOS"
        macos.mkdir(parents=True, exist_ok=True)
        run = macos / "run"
        run.write_text(
            "#!/bin/bash\n"
            f'cd "{ROOT}"\n'
            f'exec "{py}" "{launcher}" "$@"\n', encoding="utf-8")
        run.chmod(0o755)
        (app / "Contents" / "Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>'
            f'<key>CFBundleName</key><string>{name}</string>'
            f'<key>CFBundleExecutable</key><string>run</string>'
            f'<key>CFBundleIdentifier</key><string>com.opencompanion.launcher</string>'
            '<key>CFBundlePackageType</key><string>APPL</string>'
            '</dict></plist>\n', encoding="utf-8")
        print(f"✓ 桌面图标已创建：{app}")
        print("  若图标显示为空白，注销重登或重启访达即可刷新缓存。")

    elif sys.platform.startswith("linux"):
        desk = Path.home() / "Desktop" / f"{name}.desktop"
        desk.parent.mkdir(parents=True, exist_ok=True)
        desk.write_text(
            "[Desktop Entry]\nType=Application\n"
            f"Name={name}\nExec={py} {launcher}\n"
            "Terminal=true\nCategories=Utility;\n", encoding="utf-8")
        desk.chmod(0o755)
        print(f"✓ 桌面图标已创建：{desk}")

    elif sys.platform == "win32":
        vbs = Path.home() / "Desktop" / f"{name}.vbs"
        vbs.write_text(
            'Set s = CreateObject("WScript.Shell")\r\n'
            f's.CurrentDirectory = "{ROOT}"\r\n'
            f's.Run """{py}"" ""{launcher}""", 0, False\r\n', encoding="utf-8")
        print(f"✓ 桌面图标已创建：{vbs}")
    else:
        print("未知系统，跳过图标创建。")


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenCompanion 启动器")
    ap.add_argument("--install-shortcut", action="store_true", help="在桌面创建图标")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--foreground", action="store_true", help="前台运行（可看日志）")
    args = ap.parse_args()

    if args.install_shortcut:
        install_shortcut()
        return 0

    if not ensure_deps():
        print("依赖不全，无法启动。")
        return 1

    if already_running():
        print(f"已经在运行 → {URL}")
        if not args.no_browser:
            webbrowser.open(URL)
        return 0

    if port_in_use(PORT):
        print(f"端口 {PORT} 被别的程序占用了。")
        print(f"换个端口：OC_PORT=8801 python {Path(__file__).name}")
        return 1

    DATA.mkdir(parents=True, exist_ok=True)
    log_path = DATA / "server.log"
    print(f"正在启动服务（日志：{log_path}）…")

    if args.foreground:
        os.environ["OC_PORT"] = str(PORT)
        if not args.no_browser:
            import threading
            threading.Timer(2.0, lambda: webbrowser.open(URL)).start()
        os.execv(sys.executable, [sys.executable, str(CORE / "server.py")])

    start_server(log_path)
    if wait_ready():
        print(f"✓ 已就绪 → {URL}")
        if not args.no_browser:
            webbrowser.open(URL)
        return 0

    print("启动超时。请查看日志：", log_path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
