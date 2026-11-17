# 安全说明

## 签名指纹

发布包使用固定证书签名。**证书丢失将导致已安装用户永远无法升级**
（签名不一致，系统会拒绝覆盖安装），请务必备份 `android/signing/release.keystore`。

| 项目 | 值 |
| :--- | :--- |
| 签名证书 SHA-256 | `85:55:C8:92:F1:BC:E9:DF:45:BB:26:01:95:C8:DA:A1:C9:01:94:3D:56:20:30:82:9C:62:C1:78:D7:66:48:93` |
| 签名证书 SHA-1 | `F1:3E:41:E4:52:5A:C1:F3:DA:54:EF:E2:76:4E:E7:33:88:96:04:81` |
| 主体 | `CN=CollinsLiu, OU=Benzene AI Studio, O=Eight Pixel` |
| 有效期至 | 2054-04-04 |

> 这是**自签名**证书。开源项目无法使用受信任 CA 签发 APK 签名证书，
> 因此安装时系统无法自动验证"这个包确实来自 CollinsLiu"。
> 请通过上面的指纹自行核对，或从官方发布页下载。
> 想要系统级信任，需上架 Google Play 或国内应用商店由商店背书。

核对方法：

```bash
apksigner verify --print-certs OpenCompanion.apk
```

## 数据处理

**不收集任何用户数据，没有埋点，没有硬编码服务器。**

- 无第三方统计 SDK（无 Firebase / 友盟 / Bugly / Sentry 等）
- 安卓端源码中**不存在任何硬编码的服务端地址**
- 网络请求只发往一处：你自己填写的 `base_url`
- 除你配置的 AI 接口外，本软件不会主动连接任何服务器

### API Key 存储

- 使用 **Android Keystore** 生成 AES-256 主密钥，该密钥保存在系统安全区（TEE/StrongBox），
  App 本身无法导出
- API Key、人设、聊天记录均以 **AES/GCM/NoPadding** 加密后写入本地
- `allowBackup="false"`，禁止通过 adb backup 或云端备份导出
- **局限（必须明确）**：Keystore 加密挡的是「把文件拷走直接读」这一种攻击。
  它挡不住：
  - 已 root 且能在本 App 进程内执行代码的攻击者（可直接调用解密接口拿到明文）
  - 通过 Xposed/Frida 等 hook 运行时内存的攻击
  手机上不存在绝对安全，这是行业通用做法。不要在不可信的设备上保存高价值 Key。

### 网络传输

- 默认**禁止明文 HTTP**（`usesCleartextTraffic="false"`）
- 仅放行 `localhost` / `127.0.0.1` / `10.0.2.2`，供本地 Ollama 等自建服务使用
- **其余接口必须使用 https://**，否则 API Key 与聊天内容会在网络上明文传输

### WebView 加固

- `setAllowFileAccess(false)`、`setAllowContentAccess(false)`
- `setAllowFileAccessFromFileURLs(false)`、`setAllowUniversalAccessFromFileURLs(false)`
- `MIXED_CONTENT_NEVER_ALLOW`
- **JS 桥仅对本地页面暴露**：导航到任何外部页面时立即调用
  `removeJavascriptInterface("Native")`，并交系统浏览器打开，
  防止远程页面调用 `Native.chat` 读走 API Key

## 权限说明

| 权限 | 用途 |
| :--- | :--- |
| INTERNET | 调用你自己配置的 AI 接口 |
| POST_NOTIFICATIONS | 定时问候弹出通知 |
| VIBRATE | 通知震动 |
| READ_MEDIA_IMAGES / READ_EXTERNAL_STORAGE | 选择头像（仅读取你主动选的那张；后者限 API ≤ 32） |
| SCHEDULE_EXACT_ALARM / USE_EXACT_ALARM | 让问候准点触发 |
| RECEIVE_BOOT_COMPLETED | 重启后重建闹钟 |
| REQUEST_IGNORE_BATTERY_OPTIMIZATIONS | 防止息屏后被杀导致问候不发 |

**未申请**：定位、通讯录、短信、电话、摄像头、麦克风、读取已安装应用列表。

其余未使用的权限（`ACCESS_NETWORK_STATE`、`WAKE_LOCK`、`FOREGROUND_SERVICE*`）
已在 v0.1.0-beta (versionCode 4) 中移除，遵循最小权限原则。

## 关于定时通知

支持两种内容模式，**逐条可开关**：

| 模式 | 行为 | 联网 |
| :--- | :--- | :--- |
| 固定文本（默认关闭 AI） | 到点直接弹出你写的文字 | ❌ 不联网 |
| AI 生成（手动开启） | 本机把该角色设定 + 问候主题发给**你自己配置的** AI 服务，弹回生成结果 | ✅ 仅发往你的 base_url |

- **AI 失败自动回落**：无网络、超时（25 秒）、接口报错时，改为弹出你填写的原文，
  不会静默失败
- **密钥不进 Intent**：`AlarmManager` 的 Intent 只携带 pid/name/text/useAI，
  API Key 与人设在闹钟触发时按 pid 从 Keystore 加密存储中现场读取。
  这样避免把已加密的密钥再以明文复制到系统服务里
- 本版本不提供任何第三方推送服务（无 Bark / ntfy / FCM）

## 关于签名与升级

- 签名证书固定存放于 `android/signing/release.keystore`，已加入 `.gitignore`
- 每次构建使用同一证书，**连续两次打包指纹完全一致**（已验证）
- 早期版本曾把 keystore 生成在 `build/` 目录，每次清理重建都会换新证书，
  会导致已安装用户无法覆盖升级、甚至数据丢失。该问题已修复。

> ⚠️ **证书丢失 = 永远无法升级**。请备份 `release.keystore` 并妥善保管密码。

## 内容责任

AI 生成内容不代表开发者观点。用户需对创建的角色与输入内容负责，
禁止使用真实人物未授权建号，禁止违法内容。详见 `docs/用户协议.md`。

## 报告问题

发现安全漏洞请邮件联系：collinsliu9@gmail.com
