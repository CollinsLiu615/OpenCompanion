#!/bin/bash
# OpenCompanion 电脑端启动器（macOS / Linux）
#
# 不用 python xxx.py 来启动：直接双击这个脚本或桌面图标即可。
# 它负责：找 Python → 装缺的依赖 → 后台起服务 → 等就绪 → 打开浏览器窗口。

set -o pipefail

# 项目根目录（本脚本在 desktop/scripts/ 下，往上两级）
OC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OC_PORT="${OC_PORT:-8800}"
OC_URL="http://127.0.0.1:${OC_PORT}"
OC_DATA="$OC_ROOT/data"
OC_LOG="$OC_DATA/server.log"
mkdir -p "$OC_DATA"

say() { printf '%s\n' "$*"; }
fail() { printf '\n  ✗ %s\n\n' "$*"; exit 1; }

say ""
say "  OpenCompanion"
say "  Benzene AI Studio"
say "  ────────────────────────────"
say ""

# ── 1. 找 Python 3 ─────────────────────────────────────
PY=""
for c in python3 python3.12 python3.11 python3.10 python; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null)
    if [ -n "$v" ] && [ "$v" -ge 308 ]; then PY="$c"; break; fi
  fi
done
[ -n "$PY" ] || fail "没找到 Python 3.8 以上版本。请先安装 Python：https://www.python.org/downloads/"
say "  Python: $("$PY" -c 'import sys;print(sys.version.split()[0])')"

# ── 2. 依赖检查 ────────────────────────────────────────
missing=$("$PY" - <<'PYEOF'
mods = {"flask": "Flask", "openai": "openai", "PIL": "pillow"}
out = []
for m, pkg in mods.items():
    try:
        __import__(m)
    except ImportError:
        out.append(pkg)
print(" ".join(out))
PYEOF
)
if [ -n "$missing" ]; then
  say "  缺少依赖：$missing，正在安装…"
  "$PY" -m pip install --quiet $missing || fail "依赖安装失败，请手动执行：$PY -m pip install $missing"
  say "  ✓ 依赖已装好"
fi

# ── 3. 已经在跑就直接开浏览器 ──────────────────────────
if curl -s -m 2 "$OC_URL/healthz" 2>/dev/null | grep -q '"ok":true'; then
  say "  服务已在运行 → $OC_URL"
  open "$OC_URL" 2>/dev/null || xdg-open "$OC_URL" 2>/dev/null
  exit 0
fi

# ── 4. 端口占用检查 ────────────────────────────────────
if lsof -nP -iTCP:"$OC_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "端口 $OC_PORT 被其他程序占用。可换端口启动：OC_PORT=8801 \"$0\""
fi

# ── 5. 后台启动服务 ────────────────────────────────────
say "  正在启动服务…"
cd "$OC_ROOT" || fail "无法进入项目目录"
OC_PORT="$OC_PORT" OC_HOST="0.0.0.0" nohup "$PY" core/server.py >> "$OC_LOG" 2>&1 &
echo $! > "$OC_DATA/server.pid"

# ── 6. 等就绪（最多 30 秒）─────────────────────────────
i=0
while [ $i -lt 60 ]; do
  if curl -s -m 2 "$OC_URL/healthz" 2>/dev/null | grep -q '"ok":true'; then
    say "  ✓ 已就绪"
    say ""
    say "  电脑上打开:  $OC_URL"
    LAN=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
    if [ -n "$LAN" ]; then
      say "  手机上打开:  http://$LAN:$OC_PORT   （手机需与电脑连同一个 WiFi）"
    fi
    say ""
    open "$OC_URL" 2>/dev/null || xdg-open "$OC_URL" 2>/dev/null || true
    exit 0
  fi
  sleep 0.5
  i=$((i + 1))
done

fail "启动超时。请查看日志：$OC_LOG"
