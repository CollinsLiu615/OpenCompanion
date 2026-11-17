#!/bin/bash
# 在桌面创建 OpenCompanion 图标（macOS）。双击图标即启动，无需命令行。
set -e
OC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$HOME/Desktop/OpenCompanion.app"
NAME="OpenCompanion"

echo ""
echo "  创建桌面图标…"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# 启动脚本：双击后直接跑 start.sh
cat > "$APP/Contents/MacOS/run" <<EOF
#!/bin/bash
exec "$OC_ROOT/desktop/scripts/start.sh"
EOF
chmod +x "$APP/Contents/MacOS/run"

# 图标
"$OC_ROOT/desktop/scripts/make-icon.sh" "$APP/Contents/Resources/Icon.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>CFBundleIconFile</key><string>Icon</string>
  <key>CFBundleIdentifier</key><string>studio.benzeneai.opencompanion</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF

# 刷新图标缓存，避免显示空白
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true

echo "  ✓ 已创建：$APP"
echo ""
echo "  双击它就能启动 OpenCompanion。"
