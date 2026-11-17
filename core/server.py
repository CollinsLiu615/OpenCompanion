"""OpenCompanion 主服务。

启动后打开 http://127.0.0.1:<端口> 就能用。
首次访问会被引导到设置向导：配 API → 写人设 → AI 打磨 → 上传头像。
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import (Flask, jsonify, redirect, render_template, request,
                   send_file, session, url_for)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, template_folder=str(_ROOT / "templates"),
            static_folder=str(_ROOT / "static"))
app.secret_key = os.environ.get("OC_SECRET") or os.urandom(24)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 头像最大 8MB


# ── 页面 ────────────────────────────────────────────────
@app.route("/")
def splash():
    """启动页：品牌动画 → 息屏 → 品牌动画 → 息屏 → 应用。
    首次访问还会弹出用户协议，必须同意才能继续。
    """
    return render_template("splash.html")


@app.route("/app")
def index():
    """真实应用入口。未同意协议则一律退回启动页。"""
    if not C.has_agreed():
        return redirect(url_for("splash"))
    cfg = C.load_config()
    personas = C.list_personas()
    # 没配 API 或一个人设都没有 → 进向导
    if not cfg.get("configured") or not personas:
        return redirect(url_for("wizard"))
    return render_template("index.html",
                           personas=personas,
                           cfg={"model": cfg.get("model"), "base_url": cfg.get("base_url")})


@app.route("/wizard")
def wizard():
    if not C.has_agreed():
        return redirect(url_for("splash"))
    return render_template("wizard.html", presets=C.PROVIDER_PRESETS)


@app.route("/chat/<pid>")
def chat_page(pid):
    if not C.has_agreed():
        return redirect(url_for("splash"))
    p = C.load_persona(pid)
    if not p:
        return redirect(url_for("index"))
    return render_template("chat.html", persona=p)


# ── API：用户协议 ───────────────────────────────────────
@app.get("/api/agreement")
def api_agreement_status():
    return jsonify({"agreed": C.has_agreed(), "version": C.AGREEMENT_VERSION})


@app.post("/api/agreement/agree")
def api_agreement_agree():
    C.record_agreement()
    return jsonify({"ok": True})


@app.get("/api/agreement/text")
def api_agreement_text():
    f = _ROOT / "docs" / "用户协议.md"
    try:
        return jsonify({"ok": True, "text": f.read_text(encoding="utf-8")})
    except Exception:
        return jsonify({"ok": False, "text": ""}), 404


# ── API：配置 ───────────────────────────────────────────
@app.get("/api/config")
def api_get_config():
    cfg = C.load_config()
    # 永远不把完整 key 发给前端
    k = cfg.get("api_key") or ""
    safe = dict(cfg)
    safe["api_key"] = (k[:4] + "…" + k[-4:]) if len(k) > 12 else ("已保存" if k else "")
    safe["configured"] = bool(k)
    return jsonify(safe)


@app.post("/api/config")
def api_save_config():
    data = request.get_json(force=True) or {}
    if data.get("api_key") == "":
        data.pop("api_key", None)  # 空字符串 = 不修改
    C.save_config(data)
    return jsonify({"ok": True})


@app.post("/api/test-connection")
def api_test_connection():
    data = request.get_json(force=True) or {}
    cfg = C.load_config()
    # 允许用表单里的临时值测试，不污染已保存配置
    for k in ("base_url", "api_key", "model"):
        if data.get(k):
            cfg[k] = data[k]
    ok, msg = C.test_connection(cfg)
    return jsonify({"ok": ok, "message": msg})


# ── API：人设 ───────────────────────────────────────────
@app.post("/api/persona/refine")
def api_refine():
    data = request.get_json(force=True) or {}
    try:
        text = C.refine_persona(data.get("brief", ""), name=data.get("name", ""))
        return jsonify({"ok": True, "persona": text})
    except Exception as e:
        return jsonify({"ok": False, "message": C._friendly_error(e)}), 400


@app.post("/api/persona/save")
def api_persona_save():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "message": "请给角色起个名字"}), 400
    pid = (data.get("id") or "").strip() or C.slugify(name)
    p = C.load_persona(pid) or dict(C.DEFAULT_PERSONA)
    p["id"] = pid
    p["name"] = name
    p["brief"] = data.get("brief", p.get("brief", ""))
    p["persona"] = data.get("persona", p.get("persona", ""))
    if data.get("avatar"):
        p["avatar"] = data["avatar"]
    C.save_persona(p)
    return jsonify({"ok": True, "id": pid})


@app.get("/api/personas")
def api_personas():
    return jsonify(C.list_personas())


@app.get("/api/persona/<pid>")
def api_persona(pid):
    p = C.load_persona(pid)
    if not p:
        return jsonify({"ok": False, "message": "角色不存在"}), 404
    return jsonify(p)


@app.delete("/api/persona/<pid>")
def api_persona_delete(pid):
    return jsonify({"ok": C.delete_persona(pid)})


@app.post("/api/persona/<pid>/avatar")
def api_upload_avatar(pid):
    f = request.files.get("avatar")
    if not f:
        return jsonify({"ok": False, "message": "没有收到文件"}), 400
    try:
        from PIL import Image
    except ImportError:
        return jsonify({"ok": False, "message": "缺少 Pillow，请 pip install pillow"}), 500
    raw = f.read()
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return jsonify({"ok": False, "message": "这不是有效的图片文件"}), 400

    # 统一裁成正方形并缩到 512，避免巨大原图拖慢页面
    side = min(im.size)
    left = (im.width - side) // 2
    top = (im.height - side) // 2
    im = im.crop((left, top, left + side, top + side)).resize((512, 512), Image.LANCZOS)
    fname = f"{pid}.png"
    im.save(C.AVATAR_DIR / fname)

    p = C.load_persona(pid) or dict(C.DEFAULT_PERSONA)
    p["id"] = pid
    p["avatar"] = fname
    C.save_persona(p)
    return jsonify({"ok": True, "avatar": fname})


@app.get("/avatar/<path:fname>")
def avatar(fname):
    path = (C.AVATAR_DIR / fname).resolve()
    if not str(path).startswith(str(C.AVATAR_DIR.resolve())) or not path.exists():
        return "", 404
    return send_file(path)


# ── API：对话 ───────────────────────────────────────────
@app.post("/api/chat/<pid>")
def api_chat(pid):
    data = request.get_json(force=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "message": "消息为空"}), 400
    try:
        reply = C.chat_with_persona(pid, msg)
        return jsonify({"ok": True, "reply": reply})
    except Exception as e:
        return jsonify({"ok": False, "message": C._friendly_error(e)}), 400


@app.get("/api/chat/<pid>/history")
def api_history(pid):
    p = C.load_persona(pid) or {}
    return jsonify(p.get("history") or [])


@app.delete("/api/chat/<pid>/history")
def api_clear_history(pid):
    p = C.load_persona(pid)
    if p:
        p["history"] = []
        C.save_persona(p)
    return jsonify({"ok": True})


# ── 定时问候（进程内排程，不依赖 cron/launchd）──────────────
# 每个角色可以自定义问候时刻；默认给一套常见的。
DEFAULT_SCHEDULE = [
    {"at": "08:00", "kind": "morning", "name": "早安"},
    {"at": "12:00", "kind": "noon",    "name": "午安"},
    {"at": "19:00", "kind": "dinner",  "name": "晚饭"},
    {"at": "23:00", "kind": "night",   "name": "晚安"},
]

GREET_TEMPLATES = {
    "morning": "现在是早上，对方可能刚醒。说一句早安，自然地开始新的一天。",
    "noon":    "现在是中午。问一下对方吃午饭了吗，关心一下，不要长篇大论。",
    "dinner":  "现在是晚上。轻松聊两句今天过得怎么样，提醒对方好好吃饭。",
    "night":   "现在是深夜。温柔地催对方早点休息，不要熬夜。",
}


def _sched_state_file():
    return C.DATA_DIR / "schedule_state.json"


def _load_state():
    return C._read_json(_sched_state_file(), {})


def _save_state(st):
    C._write_json(_sched_state_file(), st)


def _fire_greeting(pid, kind, custom=""):
    """生成并记录一次问候。注意：问候是通知，**不写入对话历史**。

    支持两种模式：
      1. 预设 kind（morning/noon/dinner/night）
      2. 用户自定义内容 custom —— 例如「提醒我喝水」「问我今天有没有好好吃饭」
    """
    p = C.load_persona(pid)
    if not p:
        return
    cfg = C.load_config()
    if (custom or "").strip():
        instr = (f"请以你的身份，围绕这个主题主动发一条消息给对方：{custom.strip()}\n"
                 "只说一条，语气自然，像平时聊天那样，不要用列表，不要解释你在做什么。")
    else:
        instr = GREET_TEMPLATES.get(kind, GREET_TEMPLATES["morning"])
        instr += " 一句话即可，不要用列表，只输出问候本身。"
    msgs = [
        {"role": "system", "content": C._build_system_prompt(p)},
        {"role": "user", "content": "[系统指令，不是用户消息] " + instr},
    ]
    reply = C.chat_completion(msgs, cfg=cfg, temperature=0.95, max_tokens=200)
    # 存到独立的 greetings.log，不进 history
    with open(C.DATA_DIR / "greetings.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{pid}\t{kind}\t{custom or ''}\t{reply}\n")
    try:
        from notify import push  # 可选推送模块
        push(f"{p.get('name','伴侣')}", reply)
    except Exception:
        pass


def scheduler_worker():
    """每分钟检查一次。状态存盘，重启不会重复发同一条。"""
    time.sleep(15)
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            st = _load_state()
            changed = False
            for item in C.list_personas():
                pid = item["id"]
                p = C.load_persona(pid) or {}
                sched = p.get("schedule") or DEFAULT_SCHEDULE
                for job in sched:
                    key = f"{pid}|{job.get('at')}|{job.get('kind')}|{job.get('text','')}"
                    if st.get(key) == today:
                        continue
                    hh, mm = (int(x) for x in job["at"].split(":"))
                    if now.hour == hh and now.minute == mm:
                        st[key] = today
                        changed = True
                        threading.Thread(target=_safe_fire,
                                         args=(pid, job.get("kind", "morning"),
                                               job.get("text", "")),
                                         daemon=True).start()
            if changed:
                # 清掉旧日期，文件不会无限长
                st = {k: v for k, v in st.items() if v == today}
                _save_state(st)
        except Exception as e:
            print("[sched] error:", repr(e), flush=True)
        time.sleep(30)


def _safe_fire(pid, kind, text=""):
    try:
        _fire_greeting(pid, kind, text)
        print(f"[sched] ✓ {pid} {kind}", flush=True)
    except Exception as e:
        print(f"[sched] ✗ {pid} {kind}: {e!r}", flush=True)


@app.get("/api/schedule/<pid>")
def api_get_schedule(pid):
    p = C.load_persona(pid) or {}
    return jsonify(p.get("schedule") or DEFAULT_SCHEDULE)


@app.post("/api/schedule/<pid>")
def api_set_schedule(pid):
    data = request.get_json(force=True) or {}
    rows = data.get("schedule") or []
    clean = []
    for r in rows:
        at = (r.get("at") or "").strip()
        if len(at) != 5 or at[2] != ":":
            continue
        try:
            hh, mm = int(at[:2]), int(at[3:])
        except ValueError:
            continue
        if not (0 <= hh < 24 and 0 <= mm < 60):
            continue
        kind = r.get("kind") if r.get("kind") in GREET_TEMPLATES else "morning"
        text = (r.get("text") or "").strip()
        if len(text) > 500:
            text = text[:500]
        item = {"at": f"{hh:02d}:{mm:02d}", "kind": kind, "text": text}
        if r.get("name"):
            item["name"] = r["name"]
        clean.append(item)
    p = C.load_persona(pid)
    if not p:
        return jsonify({"ok": False, "message": "角色不存在"}), 404
    p["schedule"] = clean
    C.save_persona(p)
    return jsonify({"ok": True, "schedule": clean})


@app.get("/api/greetings")
def api_greetings():
    """最近发过的问候，方便用户确认定时任务真的在工作。"""
    f = C.DATA_DIR / "greetings.log"
    if not f.exists():
        return jsonify([])
    lines = f.read_text(encoding="utf-8").splitlines()[-50:]
    out = []
    for ln in reversed(lines):
        parts = ln.split("\t")
        if len(parts) >= 4:
            out.append({"time": parts[0], "pid": parts[1], "kind": parts[2], "text": parts[3]})
    return jsonify(out)


# ── 定位（浏览器定位上报，跨平台）────────────────────────
@app.post("/api/location/<pid>")
def api_set_location(pid):
    data = request.get_json(force=True) or {}
    loc = {"lat": data.get("lat"), "lon": data.get("lon"),
           "label": data.get("label", ""), "ts": time.time()}
    C._write_json(C.DATA_DIR / f"location_{pid}.json", loc)
    return jsonify({"ok": True})


@app.get("/api/location/<pid>")
def api_get_location(pid):
    return jsonify(C._read_json(C.DATA_DIR / f"location_{pid}.json", {}))


# ── API：设置面板所需 ───────────────────────────────────
@app.get("/api/chat/<pid>/export")
def api_export_chat(pid):
    """把对话导出成 Markdown 或 JSON，直接下载。"""
    p = C.load_persona(pid)
    if not p:
        return jsonify({"ok": False, "message": "角色不存在"}), 404
    fmt = (request.args.get("format") or "md").lower()
    name = p.get("name") or pid
    hist = p.get("history") or []

    if fmt == "json":
        payload = json.dumps({
            "name": name, "brief": p.get("brief", ""),
            "persona": p.get("persona", ""),
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "history": hist,
        }, ensure_ascii=False, indent=2)
        mime, ext = "application/json", "json"
    else:
        lines = [f"# 与 {name} 的对话", "",
                 f"导出于 {datetime.now():%Y-%m-%d %H:%M:%S}", ""]
        if p.get("brief"):
            lines += [f"> {p['brief']}", ""]
        lines.append("---")
        lines.append("")
        for m in hist:
            who = "我" if m.get("role") == "user" else name
            lines.append(f"**{who}**：{m.get('content','')}")
            lines.append("")
        payload = "\n".join(lines)
        mime, ext = "text/markdown", "md"

    buf = io.BytesIO(payload.encode("utf-8"))
    buf.seek(0)
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or pid
    return send_file(buf, mimetype=mime, as_attachment=True,
                     download_name=f"{safe}_对话.{ext}")


@app.post("/api/persona/<pid>/update")
def api_persona_update(pid):
    """设置面板里修改名字、简介、人设正文。"""
    p = C.load_persona(pid)
    if not p:
        return jsonify({"ok": False, "message": "角色不存在"}), 404
    data = request.get_json(force=True) or {}
    if "name" in data:
        n = (data["name"] or "").strip()
        if not n:
            return jsonify({"ok": False, "message": "名字不能为空"}), 400
        p["name"] = n
    if "brief" in data:
        p["brief"] = data["brief"]
    if "persona" in data:
        p["persona"] = data["persona"]
    C.save_persona(p)
    return jsonify({"ok": True})


# ── 版本与关于 ──────────────────────────────────────
APP_VERSION = "0.1.0-beta"
APP_NAME = "OpenCompanion"
DEVELOPER = "CollinsLiu"
STUDIO = "Benzene AI Studio"
FEEDBACK_EMAIL = "collinsliu9@gmail.com"


@app.get("/api/about")
def api_about():
    return jsonify({
        "name": APP_NAME,
        "version": APP_VERSION,
        "developer": DEVELOPER,
        "studio": STUDIO,
        "email": FEEDBACK_EMAIL,
    })


@app.post("/api/account/delete")
def api_account_delete():
    """注销：删除本地全部数据（API 配置、人设、头像、对话、提醒）。

    这是不可逆操作，前端会做两道确认后才调用。
    """
    import shutil
    confirm_text = ((request.get_json(force=True) or {}).get("confirm") or "").strip()
    expected = "我已确认我要注销我的OpenCompanion账号"
    if confirm_text != expected:
        return jsonify({"ok": False, "message": "确认文字不正确"}), 400

    removed = []
    try:
        for child in C.DATA_DIR.iterdir():
            # 保留 server.log 与 pid，避免把正在写的日志删掉
            if child.name in ("server.log", "server.pid"):
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            removed.append(child.name)
        # 重建必需目录
        C.PERSONA_DIR.mkdir(exist_ok=True)
        C.AVATAR_DIR.mkdir(exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "message": f"删除失败：{e}"}), 500

    return jsonify({"ok": True, "removed": removed})


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "time": datetime.now().isoformat()})


def main():
    port = int(os.environ.get("OC_PORT", "8800"))
    host = os.environ.get("OC_HOST", "0.0.0.0")
    threading.Thread(target=scheduler_worker, daemon=True).start()
    print(f"\n  OpenCompanion 已启动", flush=True)
    print(f"  本机访问:   http://127.0.0.1:{port}", flush=True)
    # 打印局域网地址，手机用这个打开
    import socket as _sk
    try:
        _tmp = _sk.socket(_sk.AF_INET, _sk.SOCK_DGRAM)
        _tmp.connect(("8.8.8.8", 80))
        _lan = _tmp.getsockname()[0]
        _tmp.close()
        print(f"  手机访问:   http://{_lan}:{port}   （需与电脑同一 WiFi）", flush=True)
    except Exception:
        pass
    print("", flush=True)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
