#!/bin/bash
# 生成 OpenCompanion 的发布签名证书（只需执行一次）
#
# 证书一旦丢失，已发布的 App 将永远无法升级（签名不一致系统会拒绝覆盖安装）。
# 请务必备份 signing/release.keystore 并记住密码。
set -e

export JAVA_HOME=${JAVA_HOME_21:-/Library/Java/JavaVirtualMachines/jdk-21.jdk/Contents/Home}
[ -d "$JAVA_HOME" ] || export JAVA_HOME=$(/usr/libexec/java_home -v 21 2>/dev/null || /usr/libexec/java_home)
mkdir -p signing

KS=signing/release.keystore
if [ -f "$KS" ]; then
  echo "证书已存在：$KS（不覆盖，避免破坏已有安装的升级路径）"
  exit 0
fi

echo "生成新证书…"
"$JAVA_HOME/bin/keytool" -genkeypair \
  -keystore "$KS" -alias opencompanion \
  -keyalg RSA -keysize 4096 -validity 10000 \
  -storepass "${OC_KS_PASS:-opencompanion123}" \
  -keypass "${OC_KS_PASS:-opencompanion123}" \
  -dname "CN=CollinsLiu, OU=Benzene AI Studio, O=Eight Pixel, L=Shanghai, ST=Shanghai, C=CN"

echo
echo "✓ 已生成 $KS"
"$JAVA_HOME/bin/keytool" -list -v -keystore "$KS" \
  -storepass "${OC_KS_PASS:-opencompanion123}" -alias opencompanion 2>/dev/null \
  | grep -E "SHA256|SHA1|失效" | sed 's/^/  /'
echo
echo "  请备份该文件，并把它公布在发布页上供用户核对。"
