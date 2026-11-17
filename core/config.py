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
    "summary": "",         # 早期对话的压缩摘要
    "summarized_count": 0, # 已被压缩进摘要的消息条数
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
- **角色名字必须使用用户给定的名字，一字不差，不要另起名字或换称呼。**
- 直接输出人设文档本身，不要任何前言、解释或"以下是"。
- 具体、可执行，避免"善良""温柔"这类空泛形容词堆砌。
- 用户描述里没提到的部分，做合理补充，但不要编造用户本人的隐私。
- 全程使用中文。"""


def refine_persona(brief: str, cfg: dict | None = None, name: str = "") -> str:
    """把用户的一句话描述，用 AI 扩写成完整人设。

    name 必须一起传：只给描述的话模型不知道角色叫什么，会自己编一个名字，
    导致生成的人设与用户设定的名字对不上。
    """
    if not (brief or "").strip():
        raise RuntimeError("请先描述你想要的人设（哪怕一句话也行）")

    parts = []
    if (name or "").strip():
        parts.append(f"角色名字：{name.strip()}")
    parts.append(f"简短描述：{brief.strip()}")
    user_msg = "\n".join(parts)

    return chat_completion(
        messages=[
            {"role": "system", "content": PERSONA_ARCHITECT_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        cfg=cfg,
        temperature=0.85,
        max_tokens=2000,
    )


# ── 上下文管理 ────────────────────────────────────────────
# 按 token 而非条数控制：同样 40 条，闲聊可能只有 2k token，
# 长回复能到 30k，按条数切会导致「要么没用满、要么直接超限」。
#
# 中文约 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token。
# 不引入 tiktoken：它下载词表要联网，且各厂商分词器不同，
# 用一个保守的启发式估算反而更稳（宁可少算不少算）。

# 这三个值是配合关系，改一个要一起看：
#   历史涨到 TRIGGER     → 触发压缩
#   压缩后只保留 KEEP    → 留出 (TRIGGER - KEEP) 的缓冲
#   送入模型最多 BUDGET   → 留出余量给 system prompt 与本次提问
#
# 缓冲太小会导致「刚压缩完很快又满」，频繁调用摘要 = 频繁花钱。
# 取 TRIGGER 是 BUDGET 的 2/3、KEEP 是 TRIGGER 的 1/2，
# 这样一次压缩后要再聊很久才会再次触发。
CONTEXT_TOKEN_BUDGET = 6000      # 送入模型的历史对话预算
SUMMARY_TRIGGER_TOKENS = 4000    # 未摘要的历史超过这个值就压缩
KEEP_RECENT_TOKENS = 2000        # 压缩时保留最近多少 token 的原文
MAX_HISTORY_ITEMS = 400          # 硬上限，防止文件无限膨胀


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数。

    中日韩字符按 1 token/字，其余按 4 字符/token。
    故意偏高估计，避免超出模型上下文导致请求失败。
    """
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff' \
                or '\uac00' <= ch <= '\ud7af':
            cjk += 1
        else:
            other += 1
    return cjk + max(1, other // 3)


def _msg_tokens(m: dict) -> int:
    return estimate_tokens(m.get("content") or "") + 4  # 4 为角色标记开销


def _take_recent_within(history: list[dict], budget: int) -> list[dict]:
    """从最近往前取消息，直到用满预算。返回按时间正序的列表。"""
    picked = []
    used = 0
    for m in reversed(history):
        t = _msg_tokens(m)
        if used + t > budget:
            break
        picked.append(m)
        used += t
    picked.reverse()
    # 确保以 user 开头，避免出现孤立的 assistant 消息
    while picked and picked[0].get("role") != "user":
        picked.pop(0)
    return picked


def _summarize(older: list[dict], persona: dict, cfg: dict) -> str:
    """把一段较早的对话压缩成要点，供后续请求作为背景注入。

    AI 失败时退回为「截取每条消息前 40 字」的机械摘要，
    保证不会因为摘要失败而中断对话。
    """
    if not older:
        return ""

    lines = []
    for m in older:
        role = "对方" if m.get("role") == "user" else (persona.get("name") or "我")
        text = (m.get("content") or "").strip().replace("\n", " ")
        lines.append(f"{role}: {text}")
    transcript = "\n".join(lines)

    try:
        return chat_completion(
            messages=[
                {"role": "system", "content":
                 "你是一个对话摘要助手。把下面的对话压缩成简洁的要点，"
                 "保留：双方的重要信息、约定、情绪变化、关系进展。"
                 "用第三人称陈述，不超过 300 字。不要评论，只输出摘要。"},
                {"role": "user", "content": transcript},
            ],
            cfg=cfg, temperature=0.3, max_tokens=500,
        ).strip()
    except Exception:
        # 兜底：机械截取
        bits = []
        for m in older[-20:]:
            text = (m.get("content") or "").strip().replace("\n", " ")
            if text:
                bits.append(text[:40])
        return "（较早的对话）" + " / ".join(bits)


def prepare_context(persona: dict, cfg: dict) -> tuple[list[dict], dict]:
    """构建发给模型的历史消息，必要时触发滚动摘要。

    返回 (messages, persona)，persona 可能因摘要而更新，调用方需保存。
    """
    history = persona.get("history") or []

    # 未摘要部分的 token 量
    total = sum(_msg_tokens(m) for m in history)

    if total > SUMMARY_TRIGGER_TOKENS and len(history) > 6:
        recent = _take_recent_within(history, KEEP_RECENT_TOKENS)
        cut = len(history) - len(recent)
        older = history[:cut]

        if older:
            new_summary = _summarize(older, persona, cfg)
            if new_summary:
                old_summary = (persona.get("summary") or "").strip()
                merged = (old_summary + "\n" + new_summary).strip() if old_summary else new_summary
                # 摘要本身也限长，防止无限累积
                if estimate_tokens(merged) > 1200:
                    merged = merged[-2400:]
                persona["summary"] = merged
                persona["history"] = recent
                persona["summarized_count"] = (persona.get("summarized_count") or 0) + len(older)
                history = recent

    return _take_recent_within(history, CONTEXT_TOKEN_BUDGET), persona


def chat_with_persona(pid: str, user_msg: str, cfg: dict | None = None) -> str:
    """和某个角色对话。只带真实对话历史，绝不写入通知类消息。"""
    p = load_persona(pid)
    if not p:
        raise RuntimeError("角色不存在")
    cfg = cfg or load_config()

    # 按 token 预算取历史，必要时先做滚动摘要（会更新 p 的 summary / history）
    history, p = prepare_context(p, cfg)

    system = _build_system_prompt(p)
    msgs = [{"role": "system", "content": system}]
    for m in history:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": user_msg})

    reply = chat_completion(msgs, cfg=cfg)

    p.setdefault("history", [])
    p["history"].append({"role": "user", "content": user_msg})
    p["history"].append({"role": "assistant", "content": reply})
    if len(p["history"]) > MAX_HISTORY_ITEMS:
        p["history"] = p["history"][-MAX_HISTORY_ITEMS:]
    save_persona(p)
    return reply


def _build_system_prompt(p: dict) -> str:
    """构建 system prompt。

    **前缀必须稳定**：同一个角色无论何时发起请求，返回内容的开头都要完全一致，
    否则服务商的 prompt 缓存会全部失效。

    各家缓存（OpenAI automatic caching / DeepSeek context caching /
    Anthropic prompt caching）的判据都是「请求前缀字节级相同」。
    因此把随请求变化的内容（当前时间）放到**最后**，
    把人设这种固定内容放在**最前**，让最长的公共前缀能被命中。
    """
    persona = p.get("persona") or p.get("brief") or ""
    name = p.get("name") or "AI 伴侣"

    # ── 静态部分：同一角色永远相同，可被缓存 ──
    static = (f"你现在扮演「{name}」。以下是你的人设，请完全按照它来回应：\n\n"
              + persona + "\n\n"
              "始终以角色身份说话，不要提及自己是 AI 模型或语言模型。"
              "回答自然、口语化，不要用列表格式，不要长篇大论。")

    # ── 摘要部分：变动频率低（仅在压缩时更新），放在人设之后 ──
    summary = (p.get("summary") or "").strip()
    if summary:
        static += ("\n\n【此前对话的摘要】（用于延续记忆，不需要在回复里复述）\n" + summary)

    # ── 动态部分：放末尾，不破坏前面的缓存前缀 ──
    from datetime import datetime
    now = datetime.now()
    wd = "一二三四五六日"[now.weekday()]
    dynamic = (f"\n\n【当前时间】{now.strftime('%Y-%m-%d %H:%M')} 星期{wd}\n"
               "你可以参考这个时间调整语气（早上说早安、深夜提醒休息），"
               "但不要像机器人一样念时间数据。")

    return static + dynamic


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
