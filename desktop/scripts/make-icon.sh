#!/bin/bash
# 把品牌图标做成 macOS 用的 .icns（浏览器外壳 App 的图标）
# 注意：像素画必须用 NEAREST 放大，否则边缘会糊。
set -e
OC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$OC_ROOT/assets/brand/icon.png"
OUT="$1"
[ -f "$SRC" ] || { echo "找不到源图标 $SRC"; exit 1; }

TMP=$(mktemp -d)
mkdir -p "$TMP/icon.iconset"
# 用 Python 生成各尺寸（sips 对像素画会糊）
python3 - "$SRC" "$TMP/icon.iconset" <<'PY'
import sys, os
from PIL import Image
src, out = sys.argv[1], sys.argv[2]
base = Image.open(src).convert("RGBA")
sizes = [(16,"icon_16x16"),(32,"icon_16x16@2x"),(32,"icon_32x32"),(64,"icon_32x32@2x"),
         (128,"icon_128x128"),(256,"icon_128x128@2x"),(256,"icon_256x256"),
         (512,"icon_256x256@2x"),(512,"icon_512x512"),(1024,"icon_512x512@2x")]
for px, name in sizes:
    base.resize((px,px), Image.NEAREST).save(os.path.join(out, name + ".png"))
print(f"  生成 {len(sizes)} 个尺寸")
PY
iconutil -c icns "$TMP/icon.iconset" -o "$OUT"
rm -rf "$TMP"
echo "  ✓ $OUT ($(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT") 字节)"
