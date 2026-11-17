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

**不收集任何用户数据。** 本软件没有服务器，全部内容存于本机。

### API Key 存储

- 使用 **Android Keystore** 生成 AES-256 主密钥，该密钥保存在系统安全区（TEE/StrongBox），
  App 本身无法导出
- API Key、人设、聊天记录均以 **AES/GCM/NoPadding** 加密后写入本地
- `allowBackup="false"`，禁止通过 adb backup 或云端备份导出
- **局限**：能防住"直接读取文件"，防不住"设备已 root 且攻击者能在 App 进程内执行代码"。
  手机上不存在绝对安全，这是行业通用做法。

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
| READ_MEDIA_IMAGES | 选择头像（仅读取你主动选的那张） |
| SCHEDULE_EXACT_ALARM / USE_EXACT_ALARM | 让问候准点触发 |
| RECEIVE_BOOT_COMPLETED | 重启后重建闹钟 |
| REQUEST_IGNORE_BATTERY_OPTIMIZATIONS | 防止息屏后被杀导致问候不发 |

**未申请**：定位、通讯录、短信、电话、摄像头、麦克风。

## 内容责任

AI 生成内容不代表开发者观点。用户需对创建的角色与输入内容负责，
禁止使用真实人物未授权建号，禁止违法内容。详见 `docs/用户协议.md`。

## 报告问题

发现安全漏洞请邮件联系：collinsliu9@gmail.com
