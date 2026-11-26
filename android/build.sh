#!/bin/bash
# 打包 OpenCompanion 安卓 APK（无需 Gradle，直接用 SDK 自带工具）
# 用法：./build.sh
set -e

: "${ANDROID_HOME:=$HOME/android-sdk}"
# 必须用 JDK 21：Gradle/d8 对 25 支持不完整
# 找 JDK 21：按顺序试环境变量、macOS 默认路径、Linux 下 setup-java 的位置。
# 之前只写了 macOS 路径，在 CI 的 ubuntu 上会变成空值。
if [ -z "$JAVA_HOME" ] || [ ! -d "$JAVA_HOME" ]; then
  for _cand in \
    "${JAVA_HOME_21:-}" \
    /Library/Java/JavaVirtualMachines/jdk-21.jdk/Contents/Home \
    "$(command -v javac >/dev/null 2>&1 && dirname "$(dirname "$(readlink -f "$(command -v javac)" 2>/dev/null || command -v javac)")")"; do
    if [ -n "$_cand" ] && [ -x "$_cand/bin/javac" ]; then
      export JAVA_HOME="$_cand"
      break
    fi
  done
fi
if [ ! -x "${JAVA_HOME:-/nonexistent}/bin/javac" ]; then
  echo "  ✗ 找不到 JDK 21（JAVA_HOME=$JAVA_HOME）"
  exit 1
fi
BT="$ANDROID_HOME/build-tools/36.1.0"
PLATFORM="$ANDROID_HOME/platforms/android-36/android.jar"
OUT=build
mkdir -p "$OUT/res" "$OUT/classes" "$OUT/dex"

echo "── 1/6 编译资源 ──"
"$BT/aapt2" compile --dir app/res -o "$OUT/res/res.zip"

echo "── 2/6 链接资源 ──"
"$BT/aapt2" link -o "$OUT/base.apk" \
  -I "$PLATFORM" \
  --manifest app/AndroidManifest.xml \
  -A assets \
  --java "$OUT/gen" \
  "$OUT/res/res.zip"

echo "── 3/6 编译 Java ──"
find app/src "$OUT/gen" -name "*.java" > "$OUT/sources.txt"
"$JAVA_HOME/bin/javac" --release 8 -nowarn \
  -classpath "$PLATFORM" -d "$OUT/classes" @"$OUT/sources.txt" 2>&1 | grep -v "bootstrap class path" || true

echo "── 4/6 转 dex ──"
find "$OUT/classes" -name "*.class" > "$OUT/classes.txt"
"$BT/d8" --lib "$PLATFORM" --min-api 24 --output "$OUT/dex" @"$OUT/classes.txt"

echo "── 5/6 打包 ──"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q -X "../unsigned.apk" classes.dex)

echo "── 6/6 签名 ──"
# 证书必须固定：放在 signing/ 而不是 build/。
# 早期版本把 keystore 生成在 build/ 里，每次清空重打包都会换新证书，
# 导致已安装用户无法覆盖升级（签名不一致系统会拒绝安装）。
KS="signing/release.keystore"
KS_PASS="${OC_KS_PASS:-opencompanion123}"
KS_ALIAS="${OC_KS_ALIAS:-opencompanion}"

if [ ! -f "$KS" ]; then
  echo "  ✗ 找不到签名证书 $KS"
  echo "    首次构建请先执行：./make-keystore.sh"
  exit 1
fi

"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
"$BT/apksigner" sign --ks "$KS" --ks-pass "pass:$KS_PASS" \
  --ks-key-alias "$KS_ALIAS" --key-pass "pass:$KS_PASS" \
  --out OpenCompanion.apk "$OUT/aligned.apk"

# v4 方案需要单独的 idsig 文件，对普通安装非必需，这里顺手生成
"$BT/apksigner" verify --print-certs OpenCompanion.apk 2>/dev/null | grep "SHA-256 digest" | sed 's/^/  /'

echo
echo "✓ 完成：$(pwd)/OpenCompanion.apk"
ls -lh OpenCompanion.apk
