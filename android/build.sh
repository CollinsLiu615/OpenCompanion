#!/bin/bash
# 打包 OpenCompanion 安卓 APK（无需 Gradle，直接用 SDK 自带工具）
# 用法：./build.sh
set -e

: "${ANDROID_HOME:=$HOME/android-sdk}"
# 必须用 JDK 21：Gradle/d8 对 25 支持不完整
export JAVA_HOME=${JAVA_HOME_21:-/Library/Java/JavaVirtualMachines/jdk-21.jdk/Contents/Home}
[ -d "$JAVA_HOME" ] || export JAVA_HOME=$(/usr/libexec/java_home -v 21 2>/dev/null || echo "")
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
KS="$OUT/oc.keystore"
if [ ! -f "$KS" ]; then
  "$JAVA_HOME/bin/keytool" -genkeypair -v -keystore "$KS" -alias oc \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass opencompanion -keypass opencompanion \
    -dname "CN=OpenCompanion, OU=App, O=OpenSource, L=NA, ST=NA, C=CN" >/dev/null 2>&1
fi
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:opencompanion \
  --key-pass pass:opencompanion --out OpenCompanion.apk "$OUT/aligned.apk"

echo
echo "✓ 完成：$(pwd)/OpenCompanion.apk"
ls -lh OpenCompanion.apk
