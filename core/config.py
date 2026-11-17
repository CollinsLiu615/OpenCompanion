"""OpenCompanion 核心：配置、人设、角色的持久化与 AI 调用。

设计原则
--------
1. 零锁死厂商：任何 OpenAI 兼容接口都能用（OpenAI / DeepSeek / Moonshot /
   通义 / 智谱 / 本地 Ollama / 学校网关 …），只要填 base_url + key + model。
2. 数据全在本地：全部是 data/ 目录下的明文 JSON，用户随时能看能备份。
3. 多角色：一个实例可以养好几个伴侣，各自独立的人设、头像、记忆、提醒。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("OC_DATA") or Path(__file__).resolve().parent.parent / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"
PERSONA_DIR = DATA_DIR / "personas"
AVATAR_DIR = DATA_DIR / "avatars"
PERSONA_DIR.mkdir(exist_ok=True)
AVATAR_DIR.mkdir(exist_ok=True)


# ── 通用读写 ──────────────────────────────────────────────
def _read_json(path: Path, default: Any):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # 原子写，避免断电写坏


# ── 配置 ────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "base_url": "",
    "api_key": "",
    "model": "",
    "temperature": 0.9,
    "max_tokens": 800,
    "configured": False,
}

# 不预设任何服务商：用户必须自己填写接口地址与模型名。
# 早期版本会预填 OpenAI 地址，容易让用户误以为"填了就能用"，
# 也容易在换厂商时忘记改地址，反而制造困惑。
PROVIDER_PRESETS: list[dict] = []


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_read_json(CONFIG_FILE, {}))
    return cfg


def save_config(cfg: dict) -> None:
    cur = load_config()
    for k in ("base_url", "api_key", "model", "temperature", "max_tokens"):
        if k in cfg and cfg[k] is not None:
            cur[k] = cfg[k]
    cur["configured"] = bool(cur.get("api_key") and cur.get("base_url") and cur.get("model"))
    _write_json(CONFIG_FILE, cur)


# ── AI 调用（OpenAI 兼容）─────────────────────────────────
def chat_completion(messages: list[dict], cfg: dict | None = None,
                    temperature: float | None = None,
                    max_tokens: int | None = None) -> str:
    """调用任意 OpenAI 兼容接口，返回纯文本。失败抛异常，由上层转成友好提示。"""
    cfg = cfg or load_config()
    if not cfg.get("api_key"):
        raise RuntimeError("还没配置 API Key，请先完成第 1 步")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("缺少 openai 库，请运行 pip install -r requirements.txt") from e

    client = OpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        timeout=120.0,
        max_retries=1,
    )
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=messages,
        temperature=cfg.get("temperature", 0.9) if temperature is None else temperature,
        max_tokens=cfg.get("max_tokens", 800) if max_tokens is None else max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def test_connection(cfg: dict | None = None) -> tuple[bool, str]:
    """测试 API 是否可用。返回 (是否成功, 说明)。"""
    cfg = cfg or load_config()
    try:
        reply = chat_completion(
            [{"role": "user", "content": "回复两个字：正常"}],
            cfg=cfg, temperature=0, max_tokens=20,
        )
        return True, f"连接成功，模型回复：{reply[:40]}"
    except Exception as e:
        return False, _friendly_error(e)


def _friendly_error(e: Exception) -> str:
    """把各种 SDK 报错翻译成人话，非技术用户才看得懂。"""
    s = f"{type(e).__name__}: {e}"
    low = s.lower()
    if "401" in low or "unauthorized" in low or "invalid api key" in low or "authentication" in low:
        return "API Key 不对（401）。请检查是否复制完整，有没有多余空格。"
    if "404" in low or "not found" in low:
        return ("接口地址或模型名不对（404）。请确认 base_url 结尾是否带 /v1，"
                "以及模型名是否拼对。")
    if "429" in low or "rate limit" in low or "quota" in low:
        return "被限流或额度不足（429）。稍后再试，或检查账户余额。"
    if "timeout" in low or "timed out" in low:
        return "请求超时。可能是网络不通，或该接口响应太慢。"
    if "connect" in low or "name or service" in low or "nodename" in low:
        return "连不上这个地址。请检查 base_url 是否写错、网络是否正常。"
    if "model" in low and ("exist" in low or "not found" in low or "invalid" in low):
        return "模型名不存在。请确认你的服务商提供这个模型。"
    return s[:300]


# ── 角色（人设）──────────────────────────────────────────
DEFAULT_PERSONA = {
    "id": "",
    "name": "",
    "avatar": "",          # 头像文件名，存在 data/avatars/
    "brief": "",           # 用户最初的一句话描述
    "persona": "",         # 打磨后的完整人设
    "greeting_style": "",  # 问候语气（留空则用默认）
    "created": 0,
    "history": [],         # 真实对话（只有 user 与紧随的 assistant）
    "reminders": [],
}


def list_personas() -> list[dict]:
    out = []
    for f in sorted(PERSONA_DIR.glob("*.json")):
        p = _read_json(f, None)
        if not p:
            continue
        out.append({
            "id": p.get("id") or f.stem,
            "name": p.get("name") or f.stem,
            "avatar": p.get("avatar", ""),
            "brief": p.get("brief", ""),
            "has_persona": bool(p.get("persona")),
            "history_count": len(p.get("history") or []),
        })
    return out


def slugify(name: str) -> str:
    """把角色名变成安全 id。

    只用 ASCII：中文名直接做 id 会在 URL 里触发编码问题
    （UnicodeEncodeError: ascii codec），也让第三方工具难处理。
    中文名保留在 name 字段里用于显示，id 走 ascii slug。
    """
    import hashlib
    ascii_part = "".join(c for c in (name or "") if c.isalnum() and c.isascii() or c in "-_")
    ascii_part = ascii_part.strip("-_")[:24]
    # 用名字哈希保证唯一，且同一名字总能得到同一 id
    h = hashlib.md5((name or "").encode("utf-8")).hexdigest()[:8]
    return f"{ascii_part}-{h}" if ascii_part else f"c-{h}"


def load_persona(pid: str) -> dict | None:
    f = PERSONA_DIR / f"{pid}.json"
    p = _read_json(f, None)
    if p is None:
        return None
    base = dict(DEFAULT_PERSONA)
    base.update(p)
    base.setdefault("id", pid)
    return base


def save_persona(p: dict) -> str:
    pid = p.get("id") or slugify(p.get("name", ""))
    p["id"] = pid
    if not p.get("created"):
        p["created"] = time.time()
    _write_json(PERSONA_DIR / f"{pid}.json", p)
    return pid


def delete_persona(pid: str) -> bool:
    f = PERSONA_DIR / f"{pid}.json"
    if f.exists():
        f.unlink()
        return True
    return False


# ── 人设打磨 ─────────────────────────────────────────────
PERSONA_ARCHITECT_PROMPT = """你是一位角色设计专家。用户会用一两句大白话描述他想要的 AI 伴侣，
你的任务是把这段描述扩写成一份**完整、可直接用于驱动对话**的人设文档。

必须包含以下小节，用 Markdown 标题分隔：

## 身份与背景
姓名、年龄、身份、与用户的关系、世界观设定。

## 性格特质
3-5 个核心性格，每个配一句"具体表现"（不要只写形容词）。

## 说话风格
句长、语气词习惯、用词偏好、标点习惯、称呼用户的方式。
请给出 **3 句示例台词**，让用户直观感受语气。

## 相处方式
怎么关心人、什么时候撒娇、什么时候认真、被冒犯时的反应。

## 边界与禁区
不会做的事、不会说的话、遇到越界话题如何回应。

要求：
- 直接输出人设文档本身，不要任何前言、解释或"以下是"。
- 具体、可执行，避免"善良""温柔"这类空泛形容词堆砌。
- 用户描述里没提到的部分，做合理补充，但不要编造用户本人的隐私。
- 全程使用中文。"""


def refine_persona(brief: str, cfg: dict | None = None) -> str:
    """把用户的一句话描述，用 AI 扩写成完整人设。"""
    if not (brief or "").strip():
        raise RuntimeError("请先描述你想要的人设（哪怕一句话也行）")
    return chat_completion(
        messages=[
            {"role": "system", "content": PERSONA_ARCHITECT_PROMPT},
            {"role": "user", "content": brief.strip()},
        ],
        cfg=cfg,
        temperature=0.85,
        max_tokens=2000,
    )


def chat_with_persona(pid: str, user_msg: str, cfg: dict | None = None) -> str:
    """和某个角色对话。只带真实对话历史，绝不写入通知类消息。"""
    p = load_persona(pid)
    if not p:
        raise RuntimeError("角色不存在")
    cfg = cfg or load_config()

    system = _build_system_prompt(p)
    msgs = [{"role": "system", "content": system}]
    # 只带最近 20 轮，避免上下文膨胀
    for m in (p.get("history") or [])[-40:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": user_msg})

    reply = chat_completion(msgs, cfg=cfg)

    p["history"].append({"role": "user", "content": user_msg})
    p["history"].append({"role": "assistant", "content": reply})
    p["history"] = p["history"][-200:]  # 只留最近 200 条
    save_persona(p)
    return reply


def _build_system_prompt(p: dict) -> str:
    from datetime import datetime
    now = datetime.now()
    wd = "一二三四五六日"[now.weekday()]
    head = (f"【当前时间】{now.strftime('%Y-%m-%d %H:%M')} 星期{wd}\n"
            "你可以参考这个时间调整语气（早上说早安、深夜提醒休息），"
            "但不要像机器人一样念时间数据。\n\n")
    persona = p.get("persona") or p.get("brief") or ""
    name = p.get("name") or "AI 伴侣"
    return (head + f"你现在扮演「{name}」。以下是你的人设，请完全按照它来回应：\n\n"
            + persona + "\n\n"
            "始终以角色身份说话，不要提及自己是 AI 模型或语言模型。"
            "回答自然、口语化，不要用列表格式，不要长篇大论。")


# ── 用户协议同意状态 ──────────────────────────────────────
AGREEMENT_FILE = DATA_DIR / "agreement.json"
AGREEMENT_VERSION = "1.0"


def has_agreed() -> bool:
    d = _read_json(AGREEMENT_FILE, {})
    return bool(d.get("agreed")) and d.get("version") == AGREEMENT_VERSION


def record_agreement() -> None:
    _write_json(AGREEMENT_FILE, {
        "agreed": True,
        "version": AGREEMENT_VERSION,
        "at": time.time(),
        "at_readable": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
