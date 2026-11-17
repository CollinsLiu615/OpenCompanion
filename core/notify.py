"""可选的推送通道：让问候能推到手机上。

不配置就静默跳过（只写本地 greetings.log），配置了就发出去。
支持 Bark（iOS）和任意 Webhook（安卓可用 ntfy / Gotify / Telegram 等）。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from config import DATA_DIR, _read_json, _write_json

PUSH_FILE = DATA_DIR / "push.json"

DEFAULT_PUSH = {
    "bark": "",        # 例如 https://api.day.app/YOUR_KEY
    "webhook": "",     # 任意 POST JSON 的地址，如 https://ntfy.sh/yourtopic
    "enabled": False,
}


def load_push() -> dict:
    cfg = dict(DEFAULT_PUSH)
    cfg.update(_read_json(PUSH_FILE, {}))
    return cfg


def save_push(cfg: dict) -> None:
    cur = load_push()
    for k in ("bark", "webhook", "enabled"):
        if k in cfg:
            cur[k] = cfg[k]
    _write_json(PUSH_FILE, cur)


def push(title: str, body: str) -> bool:
    """尽力推送。任何失败都静默吞掉，绝不能影响主流程。"""
    cfg = load_push()
    if not cfg.get("enabled"):
        return False
    sent = False

    bark = (cfg.get("bark") or "").strip().rstrip("/")
    if bark:
        try:
            url = f"{bark}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
            urllib.request.urlopen(url, timeout=10).read()
            sent = True
        except Exception as e:
            print("[push] bark 失败:", repr(e), flush=True)

    hook = (cfg.get("webhook") or "").strip()
    if hook:
        try:
            data = json.dumps({"title": title, "body": body}).encode("utf-8")
            req = urllib.request.Request(
                hook, data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
            sent = True
        except Exception as e:
            print("[push] webhook 失败:", repr(e), flush=True)

    return sent
